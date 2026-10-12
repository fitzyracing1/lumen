# Architecture

| Path | Role |
|---|---|
| `lumen.py` | `Belief`, `Goal`, `Hypothesis`, `Critique`, `Trace`, `Lumen`, `run_demo` |
| `run.json` | output of the demo run |
| `sandbox/mock_server.py` | offline HTTP server |
| `sandbox/lumen.py` | kernel copy used by the sandbox |
| `sandbox/interpret.py` | cycle → plain text |
| `sandbox/respond.py` | writes response files into `responses/` |
| `sandbox/coding_agent.py` | coding agent that writes source files into `responses/code/` |
| `sandbox/sdk/client.py` | `LumenClient` |
| `sandbox/Dockerfile`, `docker-compose.yml` | container setup |
| `responses/code/` | sample agent outputs (`plan_gate.py`, `altnet.py`) with their tests and result notes |
| `docs/index.html` | static page |
