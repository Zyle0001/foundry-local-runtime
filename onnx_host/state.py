import gc


class SessionRecord:
    def __init__(self, name: str, onnx_path: str):
        self.name = name
        self.onnx_path = onnx_path
        self.session = None          # ort.InferenceSession
        self.vram_bytes = 0


class SessionGroup:
    def __init__(self, group_id: str, kind: str):
        self.id = group_id
        self.kind = kind
        self.state = "unloaded"

        self.sessions: dict[str, SessionRecord] = {}
        self.artifacts: dict[str, str] = {}        # role -> path

        self.vram_before = 0
        self.vram_after = 0
        self.vram_delta = 0

        self.error: str | None = None


class Endpoint:
    def __init__(self, path, method, handler, required_sessions, required_artifacts):
        self.path = path
        self.method = method
        self.handler = handler
        self.required_sessions = required_sessions
        self.required_artifacts = required_artifacts


class SessionGroupManager:
    def __init__(self, dxgi_probe, create_session_fn):
        self.groups: dict[str, SessionGroup] = {}
        self.dxgi = dxgi_probe
        self.create_session = create_session_fn

    def register_group(self, group: SessionGroup):
        if group.id in self.groups:
            raise ValueError(f"Group {group.id} already registered")
        self.groups[group.id] = group

    def load_group(self, group_id: str):
        group = self.groups[group_id]

        if group.state in ("loading", "loaded"):
            return

        group.state = "loading"
        group.error = None

        try:
            group.vram_before = self.dxgi.vram_used_bytes()

            for session in group.sessions.values():
                session.session = self.create_session(session.onnx_path)

            group.vram_after = self.dxgi.vram_used_bytes()
            group.vram_delta = group.vram_after - group.vram_before

            group.state = "loaded"

        except Exception as e:
            group.state = "error"
            group.error = str(e)
            self._teardown_group(group)
            raise

    def unload_group(self, group_id: str):
        group = self.groups[group_id]
        self._teardown_group(group)
        group.state = "unloaded"

    def _teardown_group(self, group: SessionGroup):
        for session in group.sessions.values():
            session.session = None
        gc.collect()

    def list_loaded(self):
        return {
            gid: {
                "state": g.state,
                "vram_bytes": g.vram_delta,
                "error": g.error,
            }
            for gid, g in self.groups.items()
        }


# This dictionary keeps the 'Hot' models in VRAM
hot_models: dict[str, object] = {}

loaded_models: set[str] = set()
active_model_options: dict[str, dict[str, str | None]] = {}

