import numpy as np
import onnxruntime as ort


def create_session(model_path: str, providers: list[str] | None = None) -> ort.InferenceSession:
    """Create an ONNX Runtime session with the correct DirectML-friendly flags."""
    options = ort.SessionOptions()
    # DirectML requirement: Disable memory pattern & use sequential execution
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

    return ort.InferenceSession(
        model_path,
        sess_options=options,
        providers=providers or ["DmlExecutionProvider"],
    )


def _dtype_for_input(input_type: str):
    t = (input_type or "").lower()
    if "int64" in t:
        return np.int64
    if "int32" in t:
        return np.int32
    if "int8" in t:
        return np.int8
    if "bool" in t:
        return np.bool_
    if "float16" in t:
        return np.float16
    if "double" in t or "float64" in t:
        return np.float64
    return np.float32


def _shape_for_input(shape):
    cooked = []
    for d in shape:
        if isinstance(d, int):
            cooked.append(1 if d < 0 else d)
        else:
            cooked.append(1)
    return cooked


def smoke_llm(session: ort.InferenceSession) -> None:
    inputs = {}
    for inp in session.get_inputs():
        if inp.name == "input_ids":
            inputs[inp.name] = np.array([[1]], dtype=np.int64)
        elif inp.name == "attention_mask":
            inputs[inp.name] = np.array([[1]], dtype=np.int64)
        else:
            shape = _shape_for_input(inp.shape)
            inputs[inp.name] = np.zeros(shape, dtype=_dtype_for_input(inp.type))
    session.run(None, inputs)


def smoke_whisper(session: ort.InferenceSession) -> None:
    inputs = {}
    for inp in session.get_inputs():
        if inp.name == "input_features":
            inputs[inp.name] = np.zeros((1, 80, 16), dtype=np.float32)
        else:
            shape = _shape_for_input(inp.shape)
            inputs[inp.name] = np.zeros(shape, dtype=_dtype_for_input(inp.type))
    session.run(None, inputs)


def smoke_tts(session: ort.InferenceSession) -> None:
    inputs = {}
    max_len = 64
    for inp in session.get_inputs():
        lname = inp.name.lower()
        if inp.name == "input_ids":
            inputs[inp.name] = np.array([list(range(1, max_len + 1))], dtype=np.int64)
        elif inp.name == "style":
            inputs[inp.name] = np.zeros((1, 256), dtype=np.float32)
        elif inp.name == "speed":
            inputs[inp.name] = np.array([1.0], dtype=np.float32)
        elif "length" in lname or lname.endswith("len") or "_len" in lname:
            inputs[inp.name] = np.array([max_len], dtype=np.int64)
        else:
            shape = _shape_for_input(inp.shape)
            if "style" not in lname:
                shape = [
                    min(d, max_len) if isinstance(d, int) and d > 0 else max_len
                    for d in shape
                ]
            inputs[inp.name] = np.zeros(shape, dtype=_dtype_for_input(inp.type))
    session.run(None, inputs)


def run_smoke_test(session: ort.InferenceSession, kind: str) -> None:
    """Run a single forward-pass smoke test for the given model kind."""
    kind = (kind or "").lower()
    if kind == "llm":
        smoke_llm(session)
    elif kind == "asr":
        smoke_whisper(session)
    elif kind == "tts":
        smoke_tts(session)
    else:
        raise ValueError("Unknown model kind")

