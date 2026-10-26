# Lumen

A bounded superintelligence kernel. Better than a chat model in structure, not in marketing.

A language model answers the turn in front of it. Lumen keeps a mission, a goal stack, named beliefs with confidence, and a policy. Each cycle it perceives, proposes three different plans, tries to kill them, simulates the survivor, and only then acts. If results worsen, it may tighten its own policy, once, inside a budget.

## Results

Cold runs on Joshua's RTX 5070 against 12 fixable fixtures plus 1 impossible fixture.

| Model | Fixed (of 12) | Wrong fixes | Impossible fixture |
|---|---|---|---|
| qwen2.5-coder:1.5b (local) | 8 | 0 | withheld correctly |
| gpt-4.1-mini (OpenAI) | 8 | 0 | committed (wrong) |
| amalia 9B (local) | 5 | 1 | withheld correctly |
| qwen2.5-coder:0.5b (local) | 5 | not recorded | committed (wrong) |
| qwen2.5-coder:3b (local) | 4 | not recorded | not recorded |

A "wrong fix" passes the visible tests but fails the hidden tests. Memory mode is currently over-cautious and is being fixed.

## What is actually better

- Persistence. Goals survive the turn.
- Explicit uncertainty. Beliefs are numbers that move when evidence arrives.
- Adversarial planning. A plan that cannot survive attack does not get to act.
- Simulation before commitment. The world model runs the plan first.
- Withholding. Low confidence is an action: do not commit.
- Revision with a brake. The kernel can edit its policy, and the edit can be refused.
- A replayable trace. The decision is inspectable.

## What this is not

This is not a mind, not conscious, and not an unbounded self-improver. The revision budget is 2. There is no hidden training loop and no access to weights. "Superintelligence" here means the control shape that would still be required if the substrate got stronger: goals above tokens, critique above fluency, evidence above confidence.

## Run

```bash
python3 lumen.py
```

Outputs `run.json` with cycles, final beliefs, final policy, and the full trace.

## Model backends

Propose and attack go through a pluggable model backend (`lumen_backends.py`),
selected by the `LUMEN_MODEL` environment variable:

| `LUMEN_MODEL` | What it is | Configuration |
|---|---|---|
| `stub` (default) | Offline, deterministic. No network. Used by tests and CI. | none |
| `amalia` | Amália (Portugal's national LLM) served on another machine. | `AMALIA_BASE_URL` (default `http://127.0.0.1:8000/v1`), optional `AMALIA_API_KEY`, `AMALIA_MODEL` (default `amalia`) |
| `openai` | Any OpenAI-compatible chat completions endpoint (Ollama, llama.cpp, vLLM, OpenAI, ...). | `OPENAI_BASE_URL` (or `LUMEN_BASE_URL`), optional `OPENAI_API_KEY`, `OPENAI_MODEL` |

Model output must be valid JSON matching the expected plan/patch/critique
shapes. Anything else — prose, truncation, an unreachable server — validates to
nothing, and the kernel withholds instead of guessing.

## Coding-task mode

Point Lumen at a directory with failing tests. Each cycle: perceive = run
pytest and read the failures; propose = 3 candidate patches from the model;
attack = static checks (sandbox paths, syntax, no test edits) plus model
critique; simulate = apply the patch in a scratch copy and run the tests for
real; act = apply to the target only if tests improve and confidence clears the
policy threshold, otherwise withhold. Beliefs update from real test results and
the policy revision stays budgeted.

```bash
cp -r fixtures/buggy_calc /tmp/lumen-target
python3 lumen.py --task coding --target /tmp/lumen-target
```

The included fixture has a deliberately failing test; even the offline stub
fixes it (by proposing dumb operator mutations that attack and simulation then
filter). Sandbox guarantees: writes are confined to the target directory, test
files are read-only, and every test run has a timeout.

## Running against Amália on another machine

Amália runs on the owner's other computer. Serve it with an OpenAI-compatible
chat completions endpoint (see [github.com/fitzyracing1/amalia2.0](https://github.com/fitzyracing1/amalia2.0)),
bound to the LAN rather than localhost (e.g. `--host 0.0.0.0 --port 8000`), or
expose it through a tunnel (`ssh -L 8000:localhost:8000 user@that-machine`,
Tailscale, ngrok, ...). Then, one command:

```bash
LUMEN_MODEL=amalia AMALIA_BASE_URL=http://<that-machine>:8000/v1 \
  python3 lumen.py --task coding --target /tmp/lumen-target
```

Add `AMALIA_API_KEY` if the server requires one, and `AMALIA_MODEL` if it
serves several models. The same works for any local LLM via the generic
backend, e.g. Ollama:

```bash
ollama pull qwen2.5-coder:1.5b
LUMEN_MODEL=openai OPENAI_BASE_URL=http://localhost:11434/v1 \
  OPENAI_MODEL=qwen2.5-coder:1.5b \
  python3 lumen.py --task coding --target /tmp/lumen-target
```

A real trace from that exact Ollama setup is committed at
`runs/real-llm-run.json`.

## Tests

```bash
pip install pytest
python -m pytest -q
```

Tests run entirely on the stub backend (no network) and include an end-to-end
run where the stub fixes the fixture. CI (`.github/workflows/ci.yml`) runs the
same plus demo and coding-mode smoke tests.

## Documentation

- In-repo docs: [docs/](docs/index.md)
- Wiki: [https://github.com/fitzyracing1/lumen/wiki](https://github.com/fitzyracing1/lumen/wiki)

## Plans

This project is free, and its license stays as is. Support it through [GitHub Sponsors](https://github.com/sponsors/fitzyracing1):

- **Free**: use the code, community support.
- **Pro ($49/month)**: priority issues and support.
- **Team ($199/month)**: priority support for your team plus early access.
