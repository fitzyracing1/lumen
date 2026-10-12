# Getting started

Python 3 only, no third-party dependencies in `lumen.py`.

```bash
python3 lumen.py      # runs the demo and writes run.json (cycles, final beliefs, final policy, trace)
```

## Offline sandbox (HTTP on port 3000)

```bash
cd sandbox
python3 mock_server.py --port 3000
# or
docker compose up --build
```
