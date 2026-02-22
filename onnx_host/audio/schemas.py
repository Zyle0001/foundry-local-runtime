from typing import Any

from pydantic import BaseModel, Field


SOURCE_NODE_KINDS = {"mic", "loopback", "file_input", "test_tone", "tts"}
PROCESSOR_NODE_KINDS = {"asr_ingress", "tts_egress_formatter", "resampler", "passthrough"}
SINK_NODE_KINDS = {"speakers", "file", "virtual_output", "asr"}

DUPLEX_POLICY_MODES = {
    "capture_gated_by_playback",
    "playback_gated_by_capture",
    "allow_overlap",
    "barge_in_enabled",
}


class AudioNode(BaseModel):
    kind: str
    name: str | None = None
    device_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class AudioRouteUpsertRequest(BaseModel):
    route_id: str | None = None
    name: str | None = None
    source: AudioNode
    processors: list[AudioNode] = Field(default_factory=list)
    sink: AudioNode
    enabled: bool = True


class AudioRouteRecord(BaseModel):
    route_id: str
    name: str | None = None
    source: AudioNode
    processors: list[AudioNode] = Field(default_factory=list)
    sink: AudioNode
    enabled: bool = True


STREAM_STATES = {"stopped", "running", "paused"}


class AudioDefaultsUpdateRequest(BaseModel):
    default_input_device_id: str | None = None
    default_output_device_id: str | None = None


class AudioPolicyUpdateRequest(BaseModel):
    mode: str


class AudioModuleToggleRequest(BaseModel):
    enabled: bool


class AudioStreamRecord(BaseModel):
    stream_id: str
    route_id: str
    direction: str
    state: str = "stopped"
    last_transition_utc: str | None = None


class AudioStreamControlRecord(BaseModel):
    stream_id: str
    gain_db: float = 0.0
    muted: bool = False


class AudioControlsUpdateRequest(BaseModel):
    stream_id: str | None = None
    gain_db: float | None = None
    muted: bool | None = None
    push_to_talk: bool | None = None


class AudioMeterSnapshot(BaseModel):
    stream_id: str
    peak: float = 0.0
    rms: float = 0.0
    clipped: bool = False
    updated_at_utc: str | None = None


class AudioDevice(BaseModel):
    id: str
    name: str
    channels: int | None = None
    sample_rate: float | None = None


class AudioDevicesResponse(BaseModel):
    backend: str
    input_devices: list[AudioDevice] = Field(default_factory=list)
    output_devices: list[AudioDevice] = Field(default_factory=list)
    default_input_device_id: str | None = None
    default_output_device_id: str | None = None
    error: str | None = None
    error_code: str | None = None
    hint: str | None = None
