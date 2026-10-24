# Architecture

| Path | Role |
|---|---|
| `lumen.py` | `Belief`, `Goal`, `Hypothesis`, `Critique`, `Trace`, `Lumen`, `run_demo`, CLI |
| `lumen_backends.py` | model backends: `StubBackend` (offline default), `OpenAICompatBackend`, `AmaliaBackend`, `backend_from_env`, JSON extraction/validation |
| `lumen_coding.py` | `CodingLumen`, `run_coding_task`, sandboxed test runner |
| `lumen_memory.py` | `Memory`: persistent beliefs, policy, and lessons between runs |
| `lumen_bench/` | bug benchmark runner (`python3 -m lumen_bench`) |
| `bench/fixtures/` | 13 bug fixtures, each with hidden held-out tests |
| `bench/results/` | committed benchmark reports (JSON + markdown) |
| `scripts/amalia_bench.sh` | one-command reachability check + benchmark against Amália |
| `fixtures/buggy_calc/` | tiny target repo with a deliberately failing test |
| `tests/` | unit + end-to-end tests on the stub backend |
| `.github/workflows/ci.yml` | CI: pytest plus demo and coding-mode smoke tests |
| `run.json` | output of the demo run |
| `runs/real-llm-run.json` | coding-mode trace from a real local LLM (Ollama, qwen2.5-coder:1.5b) |
| `sandbox/mock_server.py` | offline HTTP server |
| `sandbox/lumen.py` | kernel copy used by the sandbox |
| `sandbox/interpret.py` | cycle → plain text |
| `sandbox/respond.py` | writes response files into `responses/` |
| `sandbox/coding_agent.py` | coding agent that writes source files into `responses/code/` |
| `sandbox/sdk/client.py` | `LumenClient` |
| `sandbox/Dockerfile`, `docker-compose.yml` | container setup |
| `responses/code/` | sample agent outputs (`plan_gate.py`, `altnet.py`) with their tests and result notes |
| `docs/index.html` | static page |
