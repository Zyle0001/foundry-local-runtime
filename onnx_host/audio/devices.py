from .schemas import AudioDevice, AudioDevicesResponse


def enumerate_audio_devices() -> AudioDevicesResponse:
    """
    Best-effort device listing for Phase 1 control plane.
    If `sounddevice` is not installed, return an empty inventory.
    """
    try:
        import sounddevice as sd  # type: ignore

        all_devices = sd.query_devices()
        default_input_id, default_output_id = sd.default.device

        input_devices: list[AudioDevice] = []
        output_devices: list[AudioDevice] = []

        for index, dev in enumerate(all_devices):
            max_in = int(dev.get("max_input_channels", 0))
            max_out = int(dev.get("max_output_channels", 0))
            sample_rate = dev.get("default_samplerate")
            name = str(dev.get("name", f"device-{index}"))
            device_id = str(index)

            if max_in > 0:
                input_devices.append(
                    AudioDevice(
                        id=device_id,
                        name=name,
                        channels=max_in,
                        sample_rate=sample_rate,
                    )
                )
            if max_out > 0:
                output_devices.append(
                    AudioDevice(
                        id=device_id,
                        name=name,
                        channels=max_out,
                        sample_rate=sample_rate,
                    )
                )

        return AudioDevicesResponse(
            backend="sounddevice",
            input_devices=input_devices,
            output_devices=output_devices,
            default_input_device_id=str(default_input_id) if default_input_id is not None else None,
            default_output_device_id=str(default_output_id) if default_output_id is not None else None,
        )
    except ModuleNotFoundError as exc:
        if exc.name == "sounddevice":
            return AudioDevicesResponse(
                backend="none",
                input_devices=[],
                output_devices=[],
                default_input_device_id=None,
                default_output_device_id=None,
                error="Audio device backend is not installed.",
                error_code="missing_dependency",
                hint="Install 'sounddevice' (pip install sounddevice) and restart the backend.",
            )
        return AudioDevicesResponse(
            backend="none",
            input_devices=[],
            output_devices=[],
            default_input_device_id=None,
            default_output_device_id=None,
            error=str(exc),
            error_code="backend_error",
            hint="Check runtime logs for details.",
        )
    except Exception as exc:
        return AudioDevicesResponse(
            backend="none",
            input_devices=[],
            output_devices=[],
            default_input_device_id=None,
            default_output_device_id=None,
            error=str(exc),
            error_code="backend_error",
            hint="Check runtime logs for details.",
        )
