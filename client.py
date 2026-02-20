import json
from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError, URLError


class HostClientError(Exception):
    pass


@dataclass
class OnnxHostClient:
    base_url: str = "http://127.0.0.1:8000"

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _get(self, path: str):
        req = request.Request(self._url(path), method="GET")
        return self._send(req)

    def _post(self, path: str, payload: dict | None = None):
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self._url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        return self._send(req)

    def _send(self, req: request.Request):
        try:
            with request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else None
        except HTTPError as e:
            detail = e.read().decode("utf-8") if e.fp else str(e)
            raise HostClientError(detail) from e
        except URLError as e:
            raise HostClientError(str(e)) from e

    def models(self):
        return self._get("/models")

    def load(self, model_id: str, variant: str | None = None):
        payload = {"id": model_id}
        if variant:
            payload["variant"] = variant
        return self._post("/models/load", payload)

    def unload(self, model_id: str):
        return self._post("/models/unload", {"id": model_id})

    def inputs(self, model_id: str):
        return self._get(f"/models/{model_id}/inputs")

    def options(self, model_id: str):
        return self._get(f"/models/{model_id}/options")

    def active(self, model_id: str, voice: str | None = None, config: str | None = None):
        payload: dict[str, str | None] = {}
        if voice is not None:
            payload["voice"] = voice
        if config is not None:
            payload["config"] = config
        return self._post(f"/models/{model_id}/active", payload)

    def smoke(self, model_id: str):
        return self._post(f"/models/{model_id}/smoke")

    def predict(self, model_id: str, inputs: dict):
        return self._post(f"/predict/{model_id}", inputs)

    def status(self):
        return self._get("/status")
