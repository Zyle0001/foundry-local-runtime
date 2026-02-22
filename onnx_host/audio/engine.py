from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
from pathlib import Path
from threading import Event, RLock, Thread
import time
from typing import TYPE_CHECKING, Any
import wave

import numpy as np

from .adapters import ingest_asr_frame, synthesize_tts_signal
from .format import compute_levels, convert_asr_ingress, resample_linear
from .schemas import AudioMeterSnapshot, AudioRouteRecord

if TYPE_CHECKING:
    from .state import AudioStateStore


LOGGER = logging.getLogger(__name__)
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_BLOCKSIZE = 1024


class AudioEngineRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _as_float(value: Any, default: float, *, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    return parsed


def _resolve_device(device_id: Any) -> int | str | None:
    if device_id is None:
        return None
    if isinstance(device_id, str) and not device_id.strip():
        return None
    try:
        return int(device_id)
    except (TypeError, ValueError):
        return str(device_id)


def _to_float32_mono(samples: np.ndarray) -> np.ndarray:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2:
        return data.mean(axis=1, dtype=np.float32)
    if data.ndim == 1:
        return data
    raise ValueError("Expected 1D or 2D sample data")


def _to_pcm16_bytes(samples: np.ndarray, channels: int) -> bytes:
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 1 and channels > 1:
        data = np.repeat(data[:, None], channels, axis=1)
    if data.ndim == 1:
        data = data[:, None]
    clipped = np.clip(data, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


@dataclass
class _WorkerHandle:
    thread: Thread
    stop_event: Event = field(default_factory=Event)
    pause_event: Event = field(default_factory=Event)


@dataclass
class _RuntimeStream:
    stream_id: str
    route: AudioRouteRecord
    sample_rate: int
    channels: int
    blocksize: int
    backend: str
    stream: Any = None
    worker: _WorkerHandle | None = None
    file_writer: wave.Wave_write | None = None
    signal: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float32))
    signal_cursor: int = 0
    asr_dispatch_counter: int = 0
    asr_dispatch_interval: int = 8
    active: bool = False


class AudioEngine:
    """
    Phase 2 runtime manager.
    Owns real stream lifecycle and meter publication for running routes.
    """

    def __init__(self):
        self._lock = RLock()
        self._running = False
        self._streams: dict[str, _RuntimeStream] = {}
        self._asr_buffers: dict[str, deque[np.ndarray]] = {}
        self._last_asr_adapter_result: dict[str, dict[str, object]] = {}
        self._last_tts_adapter_result: dict[str, dict[str, object]] = {}

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start_if_needed(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def stop_if_idle(self, *, has_running_streams: bool) -> bool:
        with self._lock:
            if has_running_streams:
                return False
            if not self._running:
                return False
            self._running = False
            return True

    def shutdown_all(self) -> None:
        with self._lock:
            stream_ids = list(self._streams.keys())
        for stream_id in stream_ids:
            try:
                self.stop_stream(stream_id)
            except Exception:  # pragma: no cover - defensive cleanup
                LOGGER.exception("Failed to stop audio stream during shutdown: %s", stream_id)
        with self._lock:
            self._running = False

    def read_asr_frames(self, stream_id: str, *, max_frames: int = 1) -> list[np.ndarray]:
        with self._lock:
            buffer = self._asr_buffers.get(stream_id)
            if buffer is None:
                return []
            out: list[np.ndarray] = []
            for _ in range(max(0, max_frames)):
                if not buffer:
                    break
                out.append(buffer.popleft())
            return out

    def get_adapter_diagnostics(self) -> dict[str, dict[str, dict[str, object]]]:
        with self._lock:
            return {
                "asr": {stream_id: dict(payload) for stream_id, payload in self._last_asr_adapter_result.items()},
                "tts": {stream_id: dict(payload) for stream_id, payload in self._last_tts_adapter_result.items()},
            }

    def start_stream(self, stream_id: str, *, state_store: AudioStateStore) -> bool:
        with self._lock:
            existing = self._streams.get(stream_id)
            if existing is not None:
                if existing.active:
                    return False
                try:
                    self._resume_runtime_unlocked(existing)
                except Exception as exc:
                    raise AudioEngineRuntimeError(f"Failed to resume stream '{stream_id}': {exc}") from exc
                self._refresh_running_flag_unlocked()
                return True

            snapshot = state_store.snapshot()
            route = snapshot.routes.get(stream_id)
            if route is None:
                raise AudioEngineRuntimeError(f"Route not found for stream: {stream_id}")

            try:
                runtime = self._build_runtime_unlocked(
                    stream_id=stream_id,
                    route=route,
                    default_input_device_id=snapshot.default_input_device_id,
                    default_output_device_id=snapshot.default_output_device_id,
                    state_store=state_store,
                )
            except AudioEngineRuntimeError:
                raise
            except Exception as exc:
                raise AudioEngineRuntimeError(f"Failed to initialize stream '{stream_id}': {exc}") from exc
            runtime.active = True
            self._streams[stream_id] = runtime
            self._refresh_running_flag_unlocked()
            return True

    def pause_stream(self, stream_id: str) -> bool:
        with self._lock:
            runtime = self._streams.get(stream_id)
            if runtime is None:
                return False
            if not runtime.active:
                return False
            try:
                if runtime.stream is not None:
                    runtime.stream.stop()
                if runtime.worker is not None:
                    runtime.worker.pause_event.set()
            except Exception as exc:
                raise AudioEngineRuntimeError(f"Failed to pause stream '{stream_id}': {exc}") from exc
            runtime.active = False
            self._refresh_running_flag_unlocked()
            return True

    def stop_stream(self, stream_id: str) -> bool:
        with self._lock:
            runtime = self._streams.pop(stream_id, None)
            if runtime is None:
                return False
            self._asr_buffers.pop(stream_id, None)
            self._last_asr_adapter_result.pop(stream_id, None)
            self._last_tts_adapter_result.pop(stream_id, None)
            self._close_runtime_unlocked(runtime)
            self._refresh_running_flag_unlocked()
            return True

    def process_asr_ingress(
        self,
        samples,
        *,
        sample_rate: int,
        channels: int | None = None,
    ) -> tuple[object, dict[str, object]]:
        converted = convert_asr_ingress(
            samples,
            sample_rate=sample_rate,
            channels=channels,
            target_sample_rate=16000,
        )
        peak, rms, clipped = compute_levels(converted)
        return converted, {
            "peak": peak,
            "rms": rms,
            "clipped": clipped,
            "updated_at_utc": _utc_now(),
        }

    def _build_runtime_unlocked(
        self,
        *,
        stream_id: str,
        route: AudioRouteRecord,
        default_input_device_id: str | None,
        default_output_device_id: str | None,
        state_store: AudioStateStore,
    ) -> _RuntimeStream:
        source_config = route.source.config or {}
        sink_config = route.sink.config or {}
        sample_rate = _as_int(
            source_config.get("sample_rate", sink_config.get("sample_rate", DEFAULT_SAMPLE_RATE)),
            DEFAULT_SAMPLE_RATE,
        )
        channels = _as_int(
            source_config.get("channels", sink_config.get("channels", DEFAULT_CHANNELS)),
            DEFAULT_CHANNELS,
        )
        blocksize = _as_int(
            source_config.get("blocksize", sink_config.get("blocksize", DEFAULT_BLOCKSIZE)),
            DEFAULT_BLOCKSIZE,
        )

        if route.source.kind in {"mic", "loopback"}:
            return self._build_capture_runtime_unlocked(
                stream_id=stream_id,
                route=route,
                sample_rate=sample_rate,
                channels=channels,
                blocksize=blocksize,
                default_input_device_id=default_input_device_id,
                default_output_device_id=default_output_device_id,
                state_store=state_store,
            )

        return self._build_playback_runtime_unlocked(
            stream_id=stream_id,
            route=route,
            sample_rate=sample_rate,
            channels=channels,
            blocksize=blocksize,
            default_output_device_id=default_output_device_id,
            state_store=state_store,
        )

    def _build_capture_runtime_unlocked(
        self,
        *,
        stream_id: str,
        route: AudioRouteRecord,
        sample_rate: int,
        channels: int,
        blocksize: int,
        default_input_device_id: str | None,
        default_output_device_id: str | None,
        state_store: AudioStateStore,
    ) -> _RuntimeStream:
        try:
            import sounddevice as sd  # type: ignore
        except ModuleNotFoundError as exc:
            raise AudioEngineRuntimeError(
                "Audio runtime backend is unavailable. Install 'sounddevice' for capture routes."
            ) from exc

        source_config = route.source.config or {}
        sink_config = route.sink.config or {}

        input_device = _resolve_device(route.source.device_id or default_input_device_id)
        output_device = _resolve_device(route.sink.device_id or default_output_device_id)

        runtime = _RuntimeStream(
            stream_id=stream_id,
            route=route,
            sample_rate=sample_rate,
            channels=channels,
            blocksize=blocksize,
            backend="sounddevice_input",
        )
        runtime.asr_dispatch_interval = _as_int(
            source_config.get("asr_dispatch_every", sink_config.get("asr_dispatch_every", 8)),
            8,
        )
        runtime.file_writer = self._open_optional_sink_file_unlocked(stream_id, route, sample_rate, channels)

        needs_asr_conversion = route.sink.kind == "asr" or any(
            proc.kind == "asr_ingress" for proc in route.processors
        )
        self._asr_buffers[stream_id] = deque(maxlen=64)
        try:
            if route.sink.kind in {"speakers", "virtual_output"}:
                runtime.backend = "sounddevice_duplex_passthrough"

                def duplex_callback(indata, outdata, frames, timing, status) -> None:
                    del timing
                    if status:
                        LOGGER.debug("Audio duplex callback status for %s: %s", stream_id, status)
                    samples = np.asarray(indata, dtype=np.float32)
                    processed = self._apply_stream_controls_unlocked(stream_id, samples, state_store)
                    out = processed
                    if out.ndim == 1:
                        out = out[:, None]
                    if out.shape[1] != channels:
                        out = np.repeat(_to_float32_mono(out)[:, None], channels, axis=1)
                    outdata[:] = out[:frames]

                    if needs_asr_conversion:
                        converted, _ = self.process_asr_ingress(
                            processed,
                            sample_rate=sample_rate,
                            channels=channels,
                        )
                        ingress_buffer = self._asr_buffers.get(stream_id)
                        if ingress_buffer is not None:
                            ingress_buffer.append(np.asarray(converted, dtype=np.float32))
                        self._maybe_dispatch_asr_adapter(runtime, converted)

                    self._write_optional_file_chunk_unlocked(runtime, processed)
                    self._publish_meter_unlocked(stream_id, processed, state_store)

                stream = sd.Stream(
                    samplerate=sample_rate,
                    blocksize=blocksize,
                    device=(input_device, output_device),
                    channels=channels,
                    dtype="float32",
                    callback=duplex_callback,
                )
                stream.start()
                runtime.stream = stream
                return runtime

            def capture_callback(indata, frames, timing, status) -> None:
                del frames, timing
                if status:
                    LOGGER.debug("Audio capture callback status for %s: %s", stream_id, status)
                samples = np.asarray(indata, dtype=np.float32)
                processed = self._apply_stream_controls_unlocked(stream_id, samples, state_store)

                if needs_asr_conversion:
                    converted, _ = self.process_asr_ingress(
                        processed,
                        sample_rate=sample_rate,
                        channels=channels,
                    )
                    ingress_buffer = self._asr_buffers.get(stream_id)
                    if ingress_buffer is not None:
                        ingress_buffer.append(np.asarray(converted, dtype=np.float32))
                    self._maybe_dispatch_asr_adapter(runtime, converted)

                self._write_optional_file_chunk_unlocked(runtime, processed)
                self._publish_meter_unlocked(stream_id, processed, state_store)

            stream = sd.InputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                device=input_device,
                channels=channels,
                dtype="float32",
                callback=capture_callback,
            )
            stream.start()
            runtime.stream = stream
            return runtime
        except Exception:
            if runtime.file_writer is not None:
                runtime.file_writer.close()
                runtime.file_writer = None
            raise

    def _build_playback_runtime_unlocked(
        self,
        *,
        stream_id: str,
        route: AudioRouteRecord,
        sample_rate: int,
        channels: int,
        blocksize: int,
        default_output_device_id: str | None,
        state_store: AudioStateStore,
    ) -> _RuntimeStream:
        runtime = _RuntimeStream(
            stream_id=stream_id,
            route=route,
            sample_rate=sample_rate,
            channels=channels,
            blocksize=blocksize,
            backend="playback_worker",
        )
        runtime.signal = self._materialize_playback_signal_unlocked(
            route=route,
            sample_rate=sample_rate,
        )

        if runtime.signal.size == 0:
            runtime.signal = np.zeros(blocksize, dtype=np.float32)

        try:
            if route.sink.kind == "file":
                runtime.file_writer = self._open_optional_sink_file_unlocked(
                    stream_id=stream_id,
                    route=route,
                    sample_rate=sample_rate,
                    channels=channels,
                )
                worker = _WorkerHandle(thread=Thread(target=lambda: None))
                worker.thread = Thread(
                    target=self._file_playback_worker_loop,
                    kwargs={
                        "runtime": runtime,
                        "state_store": state_store,
                        "worker": worker,
                    },
                    name=f"audio-file-worker-{stream_id}",
                    daemon=True,
                )
                worker.thread.start()
                runtime.worker = worker
                return runtime

            if route.sink.kind == "asr":
                self._asr_buffers[stream_id] = deque(maxlen=64)
                worker = _WorkerHandle(thread=Thread(target=lambda: None))
                worker.thread = Thread(
                    target=self._asr_ingress_worker_loop,
                    kwargs={
                        "runtime": runtime,
                        "state_store": state_store,
                        "worker": worker,
                    },
                    name=f"audio-asr-worker-{stream_id}",
                    daemon=True,
                )
                worker.thread.start()
                runtime.worker = worker
                runtime.backend = "asr_ingress_worker"
                return runtime

            if route.sink.kind not in {"speakers", "virtual_output"}:
                raise AudioEngineRuntimeError(
                    f"Unsupported sink kind '{route.sink.kind}' for source '{route.source.kind}'"
                )

            try:
                import sounddevice as sd  # type: ignore
            except ModuleNotFoundError as exc:
                raise AudioEngineRuntimeError(
                    "Audio runtime backend is unavailable. Install 'sounddevice' for playback routes."
                ) from exc

            runtime.backend = "sounddevice_output"
            output_device = _resolve_device(route.sink.device_id or default_output_device_id)

            def output_callback(outdata, frames, timing, status) -> None:
                del timing
                if status:
                    LOGGER.debug("Audio output callback status for %s: %s", stream_id, status)
                chunk = self._next_signal_chunk_unlocked(runtime, frames)
                chunk = self._apply_stream_controls_unlocked(stream_id, chunk, state_store)
                if channels > 1:
                    out = np.repeat(chunk[:, None], channels, axis=1)
                else:
                    out = chunk[:, None]
                outdata[:] = out
                self._publish_meter_unlocked(stream_id, chunk, state_store)

            stream = sd.OutputStream(
                samplerate=sample_rate,
                blocksize=blocksize,
                device=output_device,
                channels=channels,
                dtype="float32",
                callback=output_callback,
            )
            stream.start()
            runtime.stream = stream
            return runtime
        except Exception:
            if runtime.stream is not None:
                try:
                    runtime.stream.stop()
                except Exception:
                    pass
                try:
                    runtime.stream.close()
                except Exception:
                    pass
                runtime.stream = None
            if runtime.file_writer is not None:
                runtime.file_writer.close()
                runtime.file_writer = None
            if runtime.worker is not None:
                runtime.worker.stop_event.set()
                runtime.worker.pause_event.clear()
                runtime.worker.thread.join(timeout=1.0)
                runtime.worker = None
            self._asr_buffers.pop(stream_id, None)
            raise

    def _file_playback_worker_loop(
        self,
        *,
        runtime: _RuntimeStream,
        state_store: AudioStateStore,
        worker: _WorkerHandle,
    ) -> None:
        frame_seconds = runtime.blocksize / float(runtime.sample_rate)
        while not worker.stop_event.is_set():
            if worker.pause_event.is_set():
                time.sleep(0.05)
                continue
            chunk = self._next_signal_chunk_unlocked(runtime, runtime.blocksize)
            chunk = self._apply_stream_controls_unlocked(runtime.stream_id, chunk, state_store)
            self._write_optional_file_chunk_unlocked(runtime, chunk)
            self._publish_meter_unlocked(runtime.stream_id, chunk, state_store)
            time.sleep(frame_seconds)

    def _asr_ingress_worker_loop(
        self,
        *,
        runtime: _RuntimeStream,
        state_store: AudioStateStore,
        worker: _WorkerHandle,
    ) -> None:
        frame_seconds = runtime.blocksize / float(runtime.sample_rate)
        while not worker.stop_event.is_set():
            if worker.pause_event.is_set():
                time.sleep(0.05)
                continue
            chunk = self._next_signal_chunk_unlocked(runtime, runtime.blocksize)
            chunk = self._apply_stream_controls_unlocked(runtime.stream_id, chunk, state_store)
            converted, _ = self.process_asr_ingress(
                chunk,
                sample_rate=runtime.sample_rate,
                channels=1,
            )
            ingress_buffer = self._asr_buffers.get(runtime.stream_id)
            if ingress_buffer is not None:
                ingress_buffer.append(np.asarray(converted, dtype=np.float32))
            self._maybe_dispatch_asr_adapter(runtime, converted)
            self._publish_meter_unlocked(runtime.stream_id, chunk, state_store)
            time.sleep(frame_seconds)

    def _materialize_playback_signal_unlocked(self, *, route: AudioRouteRecord, sample_rate: int) -> np.ndarray:
        source_config = route.source.config or {}
        kind = route.source.kind

        if kind == "tts":
            text = str(source_config.get("text") or route.source.name or "").strip()
            if not text:
                text = "hello"
            preferred_model_id = source_config.get("model_id")
            model_id = str(preferred_model_id) if preferred_model_id is not None else None
            tts_signal, tts_meta = synthesize_tts_signal(
                text=text,
                model_id=model_id,
            )
            self._last_tts_adapter_result[route.route_id] = tts_meta
            if tts_signal.size > 0:
                return tts_signal.astype(np.float32, copy=False)

        if kind == "file_input":
            path_value = source_config.get("path")
            if not path_value:
                raise AudioEngineRuntimeError("file_input source requires config.path")
            path = Path(str(path_value))
            if not path.exists():
                raise AudioEngineRuntimeError(f"file_input source path does not exist: {path}")
            with wave.open(str(path), "rb") as handle:
                src_channels = max(1, int(handle.getnchannels()))
                src_rate = max(1, int(handle.getframerate()))
                raw = handle.readframes(handle.getnframes())
            pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
            if src_channels > 1 and pcm.size >= src_channels:
                pcm = pcm.reshape(-1, src_channels).mean(axis=1, dtype=np.float32)
            if src_rate != sample_rate:
                pcm = resample_linear(pcm, src_rate, sample_rate)
            return pcm.astype(np.float32, copy=False)

        raw_samples = source_config.get("samples")
        if isinstance(raw_samples, list) and raw_samples:
            return _to_float32_mono(np.asarray(raw_samples, dtype=np.float32))

        frequency_hz = _as_float(source_config.get("tone_hz"), 220.0, minimum=20.0)
        amplitude = _as_float(source_config.get("amplitude"), 0.2, minimum=0.0)
        duration_seconds = _as_float(source_config.get("duration_seconds"), 1.0, minimum=0.1)
        frame_count = max(1, int(round(duration_seconds * sample_rate)))
        t = np.arange(frame_count, dtype=np.float32) / float(sample_rate)
        return (amplitude * np.sin(2.0 * math.pi * frequency_hz * t)).astype(np.float32)

    def _next_signal_chunk_unlocked(self, runtime: _RuntimeStream, frames: int) -> np.ndarray:
        signal = runtime.signal
        if signal.size == 0:
            return np.zeros(frames, dtype=np.float32)
        out = np.empty(frames, dtype=np.float32)
        cursor = runtime.signal_cursor
        signal_len = signal.size
        filled = 0
        while filled < frames:
            remaining = frames - filled
            take = min(remaining, signal_len - cursor)
            out[filled : filled + take] = signal[cursor : cursor + take]
            filled += take
            cursor = (cursor + take) % signal_len
        runtime.signal_cursor = cursor
        return out

    def _open_optional_sink_file_unlocked(
        self,
        stream_id: str,
        route: AudioRouteRecord,
        sample_rate: int,
        channels: int,
    ) -> wave.Wave_write | None:
        if route.sink.kind != "file":
            return None

        sink_config = route.sink.config or {}
        path_value = sink_config.get("path")
        if path_value:
            output_path = Path(str(path_value))
        else:
            output_path = Path("audio_outputs") / f"{stream_id}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer = wave.open(str(output_path), "wb")
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        return writer

    def _write_optional_file_chunk_unlocked(self, runtime: _RuntimeStream, samples: np.ndarray) -> None:
        if runtime.file_writer is None:
            return
        try:
            runtime.file_writer.writeframes(_to_pcm16_bytes(samples, runtime.channels))
        except Exception:
            LOGGER.debug("Audio file write failed for %s", runtime.stream_id, exc_info=True)

    def _apply_stream_controls_unlocked(
        self,
        stream_id: str,
        samples: np.ndarray,
        state_store: AudioStateStore,
    ) -> np.ndarray:
        control = state_store.get_control(stream_id)
        data = np.asarray(samples, dtype=np.float32)
        if control.muted:
            return np.zeros_like(data, dtype=np.float32)
        if control.gain_db:
            gain = float(10 ** (control.gain_db / 20.0))
            data = data * gain
        return np.clip(data, -1.0, 1.0)

    @staticmethod
    def _route_has_asr_ingress(route: AudioRouteRecord) -> bool:
        return route.sink.kind == "asr" or any(proc.kind == "asr_ingress" for proc in route.processors)

    @staticmethod
    def _resolve_asr_model_id(route: AudioRouteRecord) -> str | None:
        sink_model_id = (route.sink.config or {}).get("model_id")
        if sink_model_id:
            return str(sink_model_id)
        for proc in route.processors:
            if proc.kind != "asr_ingress":
                continue
            model_id = (proc.config or {}).get("model_id")
            if model_id:
                return str(model_id)
        return None

    def _maybe_dispatch_asr_adapter(self, runtime: _RuntimeStream, converted_samples: np.ndarray) -> None:
        if not self._route_has_asr_ingress(runtime.route):
            return

        runtime.asr_dispatch_counter += 1
        if runtime.asr_dispatch_counter % runtime.asr_dispatch_interval != 0:
            return

        result = ingest_asr_frame(
            np.asarray(converted_samples, dtype=np.float32),
            model_id=self._resolve_asr_model_id(runtime.route),
        )
        with self._lock:
            self._last_asr_adapter_result[runtime.stream_id] = result

    def _publish_meter_unlocked(
        self,
        stream_id: str,
        samples: np.ndarray,
        state_store: AudioStateStore,
    ) -> None:
        peak, rms, clipped = compute_levels(_to_float32_mono(np.asarray(samples, dtype=np.float32)))
        state_store.upsert_meter(
            AudioMeterSnapshot(
                stream_id=stream_id,
                peak=peak,
                rms=rms,
                clipped=clipped,
                updated_at_utc=_utc_now(),
            )
        )

    def _resume_runtime_unlocked(self, runtime: _RuntimeStream) -> None:
        if runtime.stream is not None:
            runtime.stream.start()
        if runtime.worker is not None:
            runtime.worker.pause_event.clear()
        runtime.active = True

    def _close_runtime_unlocked(self, runtime: _RuntimeStream) -> None:
        if runtime.worker is not None:
            runtime.worker.stop_event.set()
            runtime.worker.pause_event.clear()
            runtime.worker.thread.join(timeout=1.5)
            runtime.worker = None
        if runtime.stream is not None:
            try:
                runtime.stream.stop()
            except Exception:
                LOGGER.debug("Audio stream stop raised for %s", runtime.stream_id, exc_info=True)
            try:
                runtime.stream.close()
            except Exception:
                LOGGER.debug("Audio stream close raised for %s", runtime.stream_id, exc_info=True)
            runtime.stream = None
        if runtime.file_writer is not None:
            try:
                runtime.file_writer.close()
            except Exception:
                LOGGER.debug("Audio file close raised for %s", runtime.stream_id, exc_info=True)
            runtime.file_writer = None
        runtime.active = False

    def _refresh_running_flag_unlocked(self) -> None:
        self._running = any(runtime.active for runtime in self._streams.values())


audio_engine = AudioEngine()
