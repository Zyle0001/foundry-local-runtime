from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock

from ..config import get_audio_module_enabled
from .graph import infer_route_direction
from .schemas import (
    DUPLEX_POLICY_MODES,
    STREAM_STATES,
    AudioMeterSnapshot,
    AudioRouteRecord,
    AudioStreamControlRecord,
    AudioStreamRecord,
)


class AudioStateNotFoundError(KeyError):
    pass


class AudioPolicyViolationError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AudioModuleState:
    audio_enabled: bool
    default_input_device_id: str | None = None
    default_output_device_id: str | None = None
    routes: dict[str, AudioRouteRecord] = field(default_factory=dict)
    streams: dict[str, AudioStreamRecord] = field(default_factory=dict)
    controls: dict[str, AudioStreamControlRecord] = field(default_factory=dict)
    meters: dict[str, AudioMeterSnapshot] = field(default_factory=dict)
    duplex_policy: str = "allow_overlap"
    push_to_talk: bool = False


class AudioStateStore:
    def __init__(self, audio_enabled: bool):
        self._lock = RLock()
        self._state = AudioModuleState(audio_enabled=audio_enabled)

    def snapshot(self) -> AudioModuleState:
        with self._lock:
            return AudioModuleState(
                audio_enabled=self._state.audio_enabled,
                default_input_device_id=self._state.default_input_device_id,
                default_output_device_id=self._state.default_output_device_id,
                routes={k: v.copy(deep=True) for k, v in self._state.routes.items()},
                streams={k: v.copy(deep=True) for k, v in self._state.streams.items()},
                controls={k: v.copy(deep=True) for k, v in self._state.controls.items()},
                meters={k: v.copy(deep=True) for k, v in self._state.meters.items()},
                duplex_policy=self._state.duplex_policy,
                push_to_talk=self._state.push_to_talk,
            )

    def set_defaults(
        self,
        *,
        default_input_device_id: str | None,
        default_output_device_id: str | None,
        update_input: bool,
        update_output: bool,
    ) -> AudioModuleState:
        with self._lock:
            if update_input:
                self._state.default_input_device_id = default_input_device_id
            if update_output:
                self._state.default_output_device_id = default_output_device_id
            return self.snapshot()

    def set_audio_enabled(self, enabled: bool) -> AudioModuleState:
        with self._lock:
            self._state.audio_enabled = bool(enabled)
            if not enabled:
                now = _utc_now()
                self._state.push_to_talk = False
                for stream in self._state.streams.values():
                    stream.state = "stopped"
                    stream.last_transition_utc = now
                for meter in self._state.meters.values():
                    meter.peak = 0.0
                    meter.rms = 0.0
                    meter.clipped = False
                    meter.updated_at_utc = now
            return self.snapshot()

    def list_routes(self) -> list[AudioRouteRecord]:
        with self._lock:
            return [route.copy(deep=True) for route in self._state.routes.values()]

    def get_route(self, route_id: str) -> AudioRouteRecord:
        with self._lock:
            route = self._state.routes.get(route_id)
            if route is None:
                raise AudioStateNotFoundError(f"Route not found: {route_id}")
            return route.copy(deep=True)

    def upsert_route(self, route: AudioRouteRecord) -> AudioRouteRecord:
        with self._lock:
            saved = route.copy(deep=True)
            self._state.routes[saved.route_id] = saved
            self._ensure_stream_for_route_unlocked(saved)
            return saved.copy(deep=True)

    def delete_route(self, route_id: str) -> bool:
        with self._lock:
            deleted = self._state.routes.pop(route_id, None) is not None
            self._state.streams.pop(route_id, None)
            self._state.controls.pop(route_id, None)
            self._state.meters.pop(route_id, None)
            return deleted

    def set_duplex_policy(self, mode: str) -> AudioModuleState:
        with self._lock:
            if mode not in DUPLEX_POLICY_MODES:
                allowed = ", ".join(sorted(DUPLEX_POLICY_MODES))
                raise ValueError(f"Invalid duplex policy '{mode}'. Allowed: {allowed}")
            self._state.duplex_policy = mode
            return self.snapshot()

    def get_stream(self, stream_id: str) -> AudioStreamRecord:
        with self._lock:
            stream = self._state.streams.get(stream_id)
            if stream is None:
                route = self._state.routes.get(stream_id)
                if route is None:
                    raise AudioStateNotFoundError(f"Stream not found: {stream_id}")
                stream = self._ensure_stream_for_route_unlocked(route)
            return stream.copy(deep=True)

    def set_stream_state(self, stream_id: str, target_state: str) -> tuple[AudioStreamRecord, list[str]]:
        with self._lock:
            if target_state not in STREAM_STATES:
                allowed = ", ".join(sorted(STREAM_STATES))
                raise ValueError(f"Invalid stream state '{target_state}'. Allowed: {allowed}")

            stream = self._state.streams.get(stream_id)
            if stream is None:
                route = self._state.routes.get(stream_id)
                if route is None:
                    raise AudioStateNotFoundError(f"Stream not found: {stream_id}")
                stream = self._ensure_stream_for_route_unlocked(route)

            interrupted: list[str] = []
            if target_state == "running":
                interrupted = self._apply_duplex_policy_before_start_unlocked(stream)

            stream.state = target_state
            now = _utc_now()
            stream.last_transition_utc = now
            meter = self._state.meters.get(stream_id)
            if meter is None:
                meter = AudioMeterSnapshot(stream_id=stream_id)
                self._state.meters[stream_id] = meter
            if target_state != "running":
                meter.peak = 0.0
                meter.rms = 0.0
                meter.clipped = False
            meter.updated_at_utc = now
            return stream.copy(deep=True), interrupted

    def set_stream_state_force(self, stream_id: str, target_state: str) -> AudioStreamRecord:
        with self._lock:
            if target_state not in STREAM_STATES:
                allowed = ", ".join(sorted(STREAM_STATES))
                raise ValueError(f"Invalid stream state '{target_state}'. Allowed: {allowed}")

            stream = self._state.streams.get(stream_id)
            if stream is None:
                route = self._state.routes.get(stream_id)
                if route is None:
                    raise AudioStateNotFoundError(f"Stream not found: {stream_id}")
                stream = self._ensure_stream_for_route_unlocked(route)

            stream.state = target_state
            now = _utc_now()
            stream.last_transition_utc = now
            meter = self._state.meters.get(stream_id)
            if meter is None:
                meter = AudioMeterSnapshot(stream_id=stream_id)
                self._state.meters[stream_id] = meter
            if target_state != "running":
                meter.peak = 0.0
                meter.rms = 0.0
                meter.clipped = False
            meter.updated_at_utc = now
            return stream.copy(deep=True)

    def set_controls(
        self,
        *,
        stream_id: str,
        gain_db: float | None,
        muted: bool | None,
        push_to_talk: bool | None,
        update_gain: bool,
        update_muted: bool,
        update_push_to_talk: bool,
    ) -> tuple[AudioStreamControlRecord, bool]:
        with self._lock:
            if stream_id not in self._state.streams:
                route = self._state.routes.get(stream_id)
                if route is None:
                    raise AudioStateNotFoundError(f"Stream not found: {stream_id}")
                self._ensure_stream_for_route_unlocked(route)

            control = self._state.controls.get(stream_id)
            if control is None:
                control = AudioStreamControlRecord(stream_id=stream_id)
                self._state.controls[stream_id] = control

            if update_gain:
                control.gain_db = float(gain_db or 0.0)
            if update_muted:
                control.muted = bool(muted)
            if update_push_to_talk:
                self._state.push_to_talk = bool(push_to_talk)

            return control.copy(deep=True), self._state.push_to_talk

    def set_push_to_talk(self, enabled: bool) -> bool:
        with self._lock:
            self._state.push_to_talk = bool(enabled)
            return self._state.push_to_talk

    def get_control(self, stream_id: str) -> AudioStreamControlRecord:
        with self._lock:
            control = self._state.controls.get(stream_id)
            if control is None:
                return AudioStreamControlRecord(stream_id=stream_id)
            return control.copy(deep=True)

    def upsert_meter(self, meter: AudioMeterSnapshot) -> AudioMeterSnapshot:
        with self._lock:
            self._state.meters[meter.stream_id] = meter.copy(deep=True)
            return meter.copy(deep=True)

    def list_meters(self) -> list[AudioMeterSnapshot]:
        with self._lock:
            return [meter.copy(deep=True) for meter in self._state.meters.values()]

    def any_running_streams(self) -> bool:
        with self._lock:
            for stream in self._state.streams.values():
                if stream.state == "running":
                    return True
            return False

    def _ensure_stream_for_route_unlocked(self, route: AudioRouteRecord) -> AudioStreamRecord:
        stream = self._state.streams.get(route.route_id)
        direction = infer_route_direction(route)
        if stream is None:
            stream = AudioStreamRecord(
                stream_id=route.route_id,
                route_id=route.route_id,
                direction=direction,
            )
            self._state.streams[route.route_id] = stream
        else:
            stream.direction = direction
            stream.route_id = route.route_id

        if route.route_id not in self._state.controls:
            self._state.controls[route.route_id] = AudioStreamControlRecord(stream_id=route.route_id)
        if route.route_id not in self._state.meters:
            self._state.meters[route.route_id] = AudioMeterSnapshot(
                stream_id=route.route_id,
                updated_at_utc=_utc_now(),
            )
        return stream

    @staticmethod
    def _is_capture_direction(direction: str) -> bool:
        return direction in {"capture", "hybrid"}

    @staticmethod
    def _is_playback_direction(direction: str) -> bool:
        return direction in {"playback", "hybrid"}

    def _apply_duplex_policy_before_start_unlocked(self, stream: AudioStreamRecord) -> list[str]:
        mode = self._state.duplex_policy
        running_streams = [s for s in self._state.streams.values() if s.state == "running" and s.stream_id != stream.stream_id]

        running_capture = [s for s in running_streams if self._is_capture_direction(s.direction)]
        running_playback = [s for s in running_streams if self._is_playback_direction(s.direction)]

        stream_is_capture = self._is_capture_direction(stream.direction)
        stream_is_playback = self._is_playback_direction(stream.direction)

        if mode == "capture_gated_by_playback" and stream_is_capture and running_playback:
            raise AudioPolicyViolationError(
                "Capture start blocked by active playback under capture_gated_by_playback policy"
            )

        if mode == "playback_gated_by_capture" and stream_is_playback and running_capture:
            raise AudioPolicyViolationError(
                "Playback start blocked by active capture under playback_gated_by_capture policy"
            )

        if mode == "barge_in_enabled" and stream_is_capture and running_playback:
            interrupted: list[str] = []
            for active in running_playback:
                active.state = "paused"
                active.last_transition_utc = _utc_now()
                interrupted.append(active.stream_id)
            return interrupted

        return []


audio_state_store = AudioStateStore(audio_enabled=get_audio_module_enabled())
