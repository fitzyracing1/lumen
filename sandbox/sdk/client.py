"""Lumen sandbox client. Stdlib only."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen


class LumenClient:
    def __init__(self, base_url: str = "http://127.0.0.1:3000"):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> dict:
        with urlopen(self.base_url + path) as res:
            return json.loads(res.read().decode())

    def _post(self, path: str, body: dict) -> dict:
        req = Request(
            self.base_url + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req) as res:
            return json.loads(res.read().decode())

    def health(self) -> dict:
        return self._get("/health")

    def state(self) -> dict:
        return self._get("/state")

    def trace(self) -> dict:
        return self._get("/trace")

    def cycle(self, observation: dict | None = None) -> dict:
        return self._post("/cycle", {"observation": observation or {}})

    def reset(self, mission: str | None = None) -> dict:
        return self._post("/reset", {"mission": mission} if mission else {})

    def interpret(self) -> str:
        return self._get("/interpret")["text"]

    def full_flow_demo(self) -> list[str]:
        self.reset()
        observations = [
            {"signal": 0.42, "resources": 0.8, "noise": 0.45},
            {"signal": 0.55, "resources": 0.7, "noise": 0.32},
            {"signal": 0.63, "resources": 0.62, "noise": 0.22},
        ]
        return [self.cycle(obs)["text"] for obs in observations]
