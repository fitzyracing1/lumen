# Lumen sandbox

Local offline sandbox for the Lumen kernel. Port 3000. No network required at runtime.

## Run

```bash
python3 mock_server.py --port 3000
```

Docker:

```bash
docker compose up --build
```

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | /health | Service and endpoint list |
| GET | /state | Mission, beliefs, goals, policy |
| GET | /trace | Replayable decision trace |
| GET | /interpret | Latest cycle as plain text |
| POST | /cycle | One perceive-propose-attack-simulate-act step |
| POST | /reset | Boot the default Lumen mission |

Cycle body: `{"observation": {"signal": 0.55, "resources": 0.7, "noise": 0.32}}`

## Client

```python
from sdk.client import LumenClient
print(LumenClient().full_flow_demo())
```
