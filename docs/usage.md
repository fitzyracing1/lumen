# Usage

## Kernel API (`lumen.py`)
`Lumen(mission)` provides `believe(key, claim, confidence)`, `add_goal(name, utility, success_test)`, `perceive(observation)`, `propose()`, `attack(h)`, `simulate(h)`, `act(h, realized)`, `maybe_revise_policy(history)`, and `cycle(observation)`. `run_demo()` drives the default mission.

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
