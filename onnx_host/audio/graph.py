from uuid import uuid4

from .schemas import (
    PROCESSOR_NODE_KINDS,
    SINK_NODE_KINDS,
    SOURCE_NODE_KINDS,
    AudioRouteRecord,
    AudioRouteUpsertRequest,
)


class AudioRouteValidationError(ValueError):
    pass


def _validate_route(route: AudioRouteUpsertRequest) -> None:
    if route.source.kind not in SOURCE_NODE_KINDS:
        allowed = ", ".join(sorted(SOURCE_NODE_KINDS))
        raise AudioRouteValidationError(f"Invalid source kind '{route.source.kind}'. Allowed: {allowed}")

    for proc in route.processors:
        if proc.kind not in PROCESSOR_NODE_KINDS:
            allowed = ", ".join(sorted(PROCESSOR_NODE_KINDS))
            raise AudioRouteValidationError(f"Invalid processor kind '{proc.kind}'. Allowed: {allowed}")

    if route.sink.kind not in SINK_NODE_KINDS:
        allowed = ", ".join(sorted(SINK_NODE_KINDS))
        raise AudioRouteValidationError(f"Invalid sink kind '{route.sink.kind}'. Allowed: {allowed}")


def materialize_route(route: AudioRouteUpsertRequest) -> AudioRouteRecord:
    _validate_route(route)
    return AudioRouteRecord(
        route_id=route.route_id or uuid4().hex,
        name=route.name,
        source=route.source,
        processors=route.processors,
        sink=route.sink,
        enabled=route.enabled,
    )


def infer_route_direction(route: AudioRouteRecord) -> str:
    has_capture_source = route.source.kind in {"mic", "loopback"}
    has_playback_sink = route.sink.kind in {"speakers", "virtual_output", "file"}
    if has_capture_source and has_playback_sink:
        return "hybrid"
    if has_capture_source:
        return "capture"
    if has_playback_sink:
        return "playback"
    return "hybrid"
