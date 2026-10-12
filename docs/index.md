# Lumen

Lumen is a small Python kernel that the README calls "a bounded superintelligence kernel". It keeps a mission, a goal stack, named beliefs with confidence values, and a policy. Each cycle it perceives, proposes plans, attacks them, simulates the survivor, and then acts, withholds, or aborts. If results get worse it may tighten its own policy, within a revision budget of 2.

The README is explicit that Lumen is not a mind, not conscious, and not an unbounded self-improver. It has no training loop and no access to weights.

Pages: [Getting started](getting-started.md) · [Usage](usage.md) · [Architecture](architecture.md) · [Contributing](contributing.md)

The repo has no CI workflow and no LICENSE file.

Copyright (c) 2026 Joshua Almeida
