#!/usr/bin/env python3
"""Lumen sandbox. Pure stdlib. The real kernel, not a fake.

  python3 mock_server.py --port 3000
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from lumen import Lumen  # noqa: E402
from interpret import interpret  # noqa: E402
from respond import write_response  # noqa: E402
from coding_agent import run as run_coding_agent  # noqa: E402

SEED = json.loads((ROOT / "data" / "seed.json").read_text())
PORT = 3000

kernel = Lumen(SEED.get("mission", "Lumen sandbox"))
last_result: dict | None = None
for key, belief in SEED.get("beliefs_final", {}).items():
    kernel.believe(key, belief["claim"], belief["confidence"], "seed")
for goal in SEED.get("goals", []):
    kernel.add_goal(goal["name"], goal["utility"], goal["success_test"])
    if goal.get("done"):
        kernel.goals[-1].done = True


def snapshot() -> dict:
    return {
        "name": "Lumen",
        "mission": kernel.mission,
        "tick": kernel.tick,
        "policy": kernel.policy,
        "revisions_used": kernel.revisions_used,
        "beliefs": {
            k: {"claim": b.claim, "confidence": round(b.confidence, 3), "revised": b.revised}
            for k, b in kernel.beliefs.items()
        },
        "goals": [
            {"name": g.name, "utility": g.utility, "success_test": g.success_test, "done": g.done}
            for g in kernel.goals
        ],
        "world": kernel.world,
        "trace_len": len(kernel.trace),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            self._send(200, {
                "ok": True,
                "service": "lumen-sandbox",
                "port": PORT,
                "endpoints": ["GET /health", "GET /state", "GET /trace", "GET /seed", "GET /interpret", "POST /cycle", "POST /reset"],
            })
            return
        if path == "/state":
            self._send(200, snapshot())
            return
        if path == "/trace":
            self._send(200, {"trace": [{"tick": t.tick, "event": t.event, "detail": t.detail} for t in kernel.trace]})
            return
        if path == "/interpret":
            text = interpret(last_result or {"tick": kernel.tick, "status": "idle", "chosen": "none", "critique": "none", "realized": 0, "issues": []}, snapshot())
            self._send(200, {"text": text})
            return
        if path == "/seed":
            self._send(200, SEED)
            return
        self._send(404, {"error": "not found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid json"})
            return
        if path == "/cycle":
            obs = payload.get("observation") or {"signal": 0.5, "resources": 0.6, "noise": 0.3}
            result = kernel.cycle({k: float(v) for k, v in obs.items()})
            kernel.maybe_revise_policy([result.get("realized") or 0])
            state = snapshot()
            text = interpret(result, state)
            path = write_response(result, state, text)
            global last_result
            last_result = result
            self._send(200, {"text": text, "file": path, "result": result, "state": state})
            return
        if path == "/code":
            task = payload.get("task") or "score a plan and reject it if risk is too high"
            coded = run_coding_agent(task)
            obs = {"signal": 0.7 if coded["passed"] else 0.3, "resources": 0.7, "noise": 0.2}
            result = kernel.cycle(obs)
            state = snapshot()
            text = interpret(result, state)
            written = write_response(result, state, text + " Coding agent files: " + ", ".join(coded["files"]) + ".")
            global last_result
            last_result = result
            self._send(200, {"text": text, "file": written, "code": coded, "result": result})
            return
        if path == "/reset":
            boot(payload.get("mission"))
            self._send(200, snapshot())
            return
        self._send(404, {"error": "not found", "path": path})

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def boot(mission: str | None = None) -> None:
    global kernel, last_result
    last_result = None
    kernel = Lumen(mission or SEED.get("mission", "Lumen sandbox"))
    kernel.believe("signal", "the task has a measurable success signal", 0.52, "prior")
    kernel.believe("resources", "compute and attention budget is finite", 0.7, "prior")
    kernel.add_goal("frame the decision", 0.6, "one falsifiable question written")
    kernel.add_goal("produce a checked answer", 0.9, "answer survives internal attack")
    kernel.add_goal("leave a reusable trace", 0.5, "trace is sufficient to replay")


def main() -> None:
    global PORT
    if "--port" in sys.argv:
        PORT = int(sys.argv[sys.argv.index("--port") + 1])
    boot()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"lumen sandbox on http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
