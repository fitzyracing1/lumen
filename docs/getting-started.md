# Getting started

Python 3 only, no third-party dependencies in `lumen.py`.

```bash
python3 lumen.py      # runs the demo and writes run.json (cycles, final beliefs, final policy, trace)
```

## Coding-task mode

```bash
cp -r fixtures/buggy_calc /tmp/lumen-target
python3 lumen.py --task coding --target /tmp/lumen-target
```

Works offline on the deterministic stub backend by default. Set `LUMEN_MODEL=amalia` (with `AMALIA_BASE_URL`) or `LUMEN_MODEL=openai` (with `OPENAI_BASE_URL`, `OPENAI_MODEL`) to use a real LLM — see the README.

## Tests

```bash
pip install pytest
python -m pytest -q
```

## Offline sandbox (HTTP on port 3000)

```bash
cd sandbox
python3 mock_server.py --port 3000
# or
docker compose up --build
```
