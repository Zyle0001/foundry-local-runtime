from fastapi import APIRouter, HTTPException

from ..audio import (
    AudioEngineRuntimeError,
    AudioPolicyViolationError,
    AudioRouteValidationError,
    AudioStateNotFoundError,
    audio_engine,
    audio_state_store,
    enumerate_audio_devices,
    materialize_route,
)
from ..config import get_audio_module_enabled, set_audio_module_enabled
from ..audio.schemas import (
    AudioControlsUpdateRequest,
    AudioDefaultsUpdateRequest,
    AudioModuleToggleRequest,
    AudioPolicyUpdateRequest,
    AudioRouteUpsertRequest,
)


router = APIRouter(prefix="/audio", tags=["audio"])


def _ensure_audio_enabled() -> None:
    if not get_audio_module_enabled():
        raise HTTPException(409, "Audio module disabled. Enable it with POST /audio/module.")


@router.get("/module")
def get_audio_module_status():
    return {"enabled": get_audio_module_enabled()}


@router.post("/module")
def set_audio_module_status(req: AudioModuleToggleRequest):
    enabled = set_audio_module_enabled(req.enabled)
    snapshot = audio_state_store.set_audio_enabled(enabled)
    if not enabled:
        audio_engine.shutdown_all()
    return {
        "enabled": enabled,
        "audio_enabled": snapshot.audio_enabled,
        "engine_running": audio_engine.is_running,
    }


@router.get("/devices")
def get_audio_devices():
    devices = enumerate_audio_devices()
    snapshot = audio_state_store.snapshot()
    default_input = snapshot.default_input_device_id or devices.default_input_device_id
    default_output = snapshot.default_output_device_id or devices.default_output_device_id
    return {
        "backend": devices.backend,
        "input_devices": [d.dict() for d in devices.input_devices],
        "output_devices": [d.dict() for d in devices.output_devices],
        "default_input_device_id": default_input,
        "default_output_device_id": default_output,
        "error": devices.error,
        "error_code": devices.error_code,
        "hint": devices.hint,
    }


@router.post("/defaults")
def set_audio_defaults(req: AudioDefaultsUpdateRequest):
    _ensure_audio_enabled()
    payload = req.dict(exclude_unset=True)
    update_input = "default_input_device_id" in payload
    update_output = "default_output_device_id" in payload
    if not update_input and not update_output:
        raise HTTPException(400, "No fields provided for update")

    devices = enumerate_audio_devices()
    input_ids = {d.id for d in devices.input_devices}
    output_ids = {d.id for d in devices.output_devices}

    if (
        update_input
        and req.default_input_device_id is not None
        and input_ids
        and req.default_input_device_id not in input_ids
    ):
        raise HTTPException(400, f"Unknown input device id: {req.default_input_device_id}")

    if (
        update_output
        and req.default_output_device_id is not None
        and output_ids
        and req.default_output_device_id not in output_ids
    ):
        raise HTTPException(400, f"Unknown output device id: {req.default_output_device_id}")

    snapshot = audio_state_store.set_defaults(
        default_input_device_id=req.default_input_device_id,
        default_output_device_id=req.default_output_device_id,
        update_input=update_input,
        update_output=update_output,
    )
    return {
        "default_input_device_id": snapshot.default_input_device_id,
        "default_output_device_id": snapshot.default_output_device_id,
    }


@router.post("/policy")
def set_audio_policy(req: AudioPolicyUpdateRequest):
    _ensure_audio_enabled()
    try:
        snapshot = audio_state_store.set_duplex_policy(req.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"duplex_policy": snapshot.duplex_policy}


@router.get("/state")
def get_audio_state():
    snapshot = audio_state_store.snapshot()
    return {
        "audio_enabled": snapshot.audio_enabled,
        "defaults": {
            "default_input_device_id": snapshot.default_input_device_id,
            "default_output_device_id": snapshot.default_output_device_id,
        },
        "duplex_policy": snapshot.duplex_policy,
        "push_to_talk": snapshot.push_to_talk,
        "routes": [route.dict() for route in snapshot.routes.values()],
        "streams": [stream.dict() for stream in snapshot.streams.values()],
        "controls": [control.dict() for control in snapshot.controls.values()],
        "meters": [meter.dict() for meter in snapshot.meters.values()],
        "adapter_diagnostics": audio_engine.get_adapter_diagnostics(),
        "engine_running": audio_engine.is_running,
    }


@router.get("/routes")
def list_audio_routes():
    return {"routes": [route.dict() for route in audio_state_store.list_routes()]}


@router.post("/routes")
def upsert_audio_route(req: AudioRouteUpsertRequest):
    _ensure_audio_enabled()
    try:
        route = materialize_route(req)
    except AudioRouteValidationError as exc:
        raise HTTPException(400, str(exc))
    saved = audio_state_store.upsert_route(route)
    return {"route": saved.dict()}


@router.delete("/routes/{route_id}")
def delete_audio_route(route_id: str):
    _ensure_audio_enabled()
    audio_engine.stop_stream(route_id)
    deleted = audio_state_store.delete_route(route_id)
    if not deleted:
        raise HTTPException(404, "Route not found")
    return {"status": "deleted", "route_id": route_id}


@router.post("/streams/{stream_id}/start")
def start_audio_stream(stream_id: str):
    _ensure_audio_enabled()
    previous_state: str | None = None
    try:
        previous_state = audio_state_store.get_stream(stream_id).state
    except AudioStateNotFoundError:
        previous_state = None

    try:
        stream, interrupted = audio_state_store.set_stream_state(stream_id, "running")
    except AudioStateNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except AudioPolicyViolationError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    try:
        audio_engine.start_stream(stream_id, state_store=audio_state_store)
        for interrupted_id in interrupted:
            audio_engine.pause_stream(interrupted_id)
    except AudioEngineRuntimeError as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
            for interrupted_id in interrupted:
                audio_state_store.set_stream_state_force(interrupted_id, "running")
        audio_engine.stop_stream(stream_id)
        raise HTTPException(500, str(exc))
    except Exception as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
            for interrupted_id in interrupted:
                audio_state_store.set_stream_state_force(interrupted_id, "running")
        audio_engine.stop_stream(stream_id)
        raise HTTPException(500, f"Failed to start stream runtime: {exc}")

    return {
        "stream": stream.dict(),
        "interrupted_stream_ids": interrupted,
        "engine_running": audio_engine.is_running,
    }


@router.post("/streams/{stream_id}/pause")
def pause_audio_stream(stream_id: str):
    _ensure_audio_enabled()
    previous_state: str | None = None
    try:
        previous_state = audio_state_store.get_stream(stream_id).state
    except AudioStateNotFoundError:
        previous_state = None

    try:
        stream, _ = audio_state_store.set_stream_state(stream_id, "paused")
    except AudioStateNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    try:
        audio_engine.pause_stream(stream_id)
    except AudioEngineRuntimeError as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
        raise HTTPException(500, str(exc))
    except Exception as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
        raise HTTPException(500, f"Failed to pause stream runtime: {exc}")

    engine_stopped = audio_engine.stop_if_idle(has_running_streams=audio_state_store.any_running_streams())
    return {
        "stream": stream.dict(),
        "engine_running": audio_engine.is_running,
        "engine_stopped": engine_stopped,
    }


@router.post("/streams/{stream_id}/stop")
def stop_audio_stream(stream_id: str):
    _ensure_audio_enabled()
    previous_state: str | None = None
    try:
        previous_state = audio_state_store.get_stream(stream_id).state
    except AudioStateNotFoundError:
        previous_state = None

    try:
        stream, _ = audio_state_store.set_stream_state(stream_id, "stopped")
    except AudioStateNotFoundError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    try:
        audio_engine.stop_stream(stream_id)
    except AudioEngineRuntimeError as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
        raise HTTPException(500, str(exc))
    except Exception as exc:
        if previous_state is not None:
            audio_state_store.set_stream_state_force(stream_id, previous_state)
        raise HTTPException(500, f"Failed to stop stream runtime: {exc}")

    engine_stopped = audio_engine.stop_if_idle(has_running_streams=audio_state_store.any_running_streams())
    return {
        "stream": stream.dict(),
        "engine_running": audio_engine.is_running,
        "engine_stopped": engine_stopped,
    }


@router.post("/controls")
def update_audio_controls(req: AudioControlsUpdateRequest):
    _ensure_audio_enabled()
    payload = req.dict(exclude_unset=True)
    update_gain = "gain_db" in payload
    update_muted = "muted" in payload
    update_push_to_talk = "push_to_talk" in payload

    if not (update_gain or update_muted or update_push_to_talk):
        raise HTTPException(400, "No control fields provided for update")

    control = None
    push_to_talk = audio_state_store.snapshot().push_to_talk

    if update_gain or update_muted:
        if not req.stream_id:
            raise HTTPException(400, "stream_id is required when updating gain or mute")
        try:
            control, push_to_talk = audio_state_store.set_controls(
                stream_id=req.stream_id,
                gain_db=req.gain_db,
                muted=req.muted,
                push_to_talk=None,
                update_gain=update_gain,
                update_muted=update_muted,
                update_push_to_talk=False,
            )
        except AudioStateNotFoundError as exc:
            raise HTTPException(404, str(exc))

    if update_push_to_talk:
        push_to_talk = audio_state_store.set_push_to_talk(bool(req.push_to_talk))

    return {
        "control": control.dict() if control is not None else None,
        "push_to_talk": push_to_talk,
    }


@router.get("/meters")
def get_audio_meters():
    _ensure_audio_enabled()
    return {
        "meters": [meter.dict() for meter in audio_state_store.list_meters()],
        "engine_running": audio_engine.is_running,
    }
