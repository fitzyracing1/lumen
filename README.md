# Lumen

A bounded superintelligence kernel. Better than a chat model in structure, not in marketing.

A language model answers the turn in front of it. Lumen keeps a mission, a goal stack, named beliefs with confidence, and a policy. Each cycle it perceives, proposes three different plans, tries to kill them, simulates the survivor, and only then acts. If results worsen, it may tighten its own policy, once, inside a budget.

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
