# Usage

## Kernel API (`lumen.py`)
`Lumen(mission, model=None)` provides `believe(key, claim, confidence)`, `add_goal(name, utility, success_test)`, `perceive(observation)`, `propose()`, `attack(h)`, `simulate(h)`, `act(h, realized)`, `maybe_revise_policy(history)`, and `cycle(observation)`. `run_demo()` drives the default mission. `propose` and `attack` call the model backend; invalid model output makes the kernel withhold.

## CLI

```bash
python3 lumen.py                                   # demo mission, writes run.json
python3 lumen.py --task coding --target DIR        # fix failing tests in DIR
python3 lumen.py --task coding --target DIR --max-cycles 5 --test-timeout 120 --out run.json
python3 lumen.py --task coding --target DIR --memory mem.json   # persist memory
python3 lumen.py --forget --memory mem.json        # wipe the memory store
```

## Benchmark CLI

```bash
python3 -m lumen_bench --model stub                          # all fixtures, offline
python3 -m lumen_bench --model openai:qwen2.5-coder:1.5b     # local Ollama
python3 -m lumen_bench --model amalia --check-only           # reachability only
python3 -m lumen_bench --model stub --fixtures wrong_operator,impossible
python3 -m lumen_bench --model stub --memory mem.json --reset-memory
```

Writes `<prefix>.json` and `<prefix>.md` (default under `bench/results/`).

The backend is selected by `LUMEN_MODEL` (`stub` default, `amalia`, `openai`); see the README for the environment variables of each.

## Coding mode (`lumen_coding.py`)
`CodingLumen(target_dir, model, test_timeout)` keeps the kernel layers but on a real substrate: perceive runs pytest in a scratch copy, propose asks the model for up to 3 patches (full-file edits), attack combines static checks (sandboxed paths, `ast.parse`, no test-file edits, no no-ops) with a model critique, simulate applies the patch in a scratch copy and runs the tests, act applies to the target only when tests improve and mean belief confidence clears `min_confidence_to_act` — with a revert if reality disagrees with the simulation. `run_coding_task(...)` drives it and writes a replayable `run.json`.

## Sandbox endpoints (`sandbox/mock_server.py`)

| Method | Path | What it does |
|---|---|---|
| GET | /health | service and endpoint list |
| GET | /state | mission, beliefs, goals, policy |
| GET | /trace | replayable decision trace |
| GET | /interpret | latest cycle as plain text |
| POST | /cycle | one perceive → propose → attack → simulate → act step |
| POST | /reset | boot the default mission |

Example cycle body: `{"observation": {"signal": 0.55, "resources": 0.7, "noise": 0.32}}`

Python client:
```python
from sdk.client import LumenClient
print(LumenClient().full_flow_demo())
```

Cycle outcomes (`sandbox/interpret.py`): `aborted`, `committed`, `withheld`, `blocked`, `idle`.
