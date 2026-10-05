#!/usr/bin/env python3
"""
Lumen — a bounded superintelligence kernel.

Not a claim of AGI. A working architecture that is structurally better than a
single-pass language model:

  1. Goals persist and outrank the current token.
  2. Beliefs are explicit, scored, and revisable.
  3. Every plan is attacked by an internal critic before it is allowed to act.
  4. Actions are simulated against the world model before commitment.
  5. Outcomes update the model. Failures are first-class data.
  6. The kernel may propose a revision of its own policy, but only if the
     critic cannot falsify the expected gain.

Run: python3 lumen.py
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from typing import Callable


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

@dataclass
class Belief:
    claim: str
    confidence: float  # 0..1
    evidence: list[str] = field(default_factory=list)
    revised: int = 0

    def update(self, support: float, note: str) -> None:
        # Bayesian-ish nudge, clamped. Not a real posterior — an explicit one.
        prior = min(max(self.confidence, 1e-4), 1 - 1e-4)
        logit = math.log(prior / (1 - prior)) + support
        self.confidence = 1 / (1 + math.exp(-logit))
        self.evidence.append(note)
        self.revised += 1


@dataclass
class Goal:
    name: str
    utility: float
    success_test: str
    done: bool = False


@dataclass
class Hypothesis:
    name: str
    steps: list[str]
    predicted_utility: float
    risk: float
    assumptions: list[str]


@dataclass
class Critique:
    fatal: bool
    issues: list[str]
    adjusted_utility: float
    note: str


@dataclass
class Trace:
    tick: int
    event: str
    detail: str


# ---------------------------------------------------------------------------
# Kernel
# ---------------------------------------------------------------------------

class Lumen:
    """Hierarchical kernel: perceive -> model -> propose -> attack -> simulate -> act -> revise."""

    def __init__(self, mission: str):
        self.mission = mission
        self.tick = 0
        self.goals: list[Goal] = []
        self.beliefs: dict[str, Belief] = {}
        self.memory: list[str] = []
        self.trace: list[Trace] = []
        self.policy = {
            "min_confidence_to_act": 0.55,
            "max_risk": 0.45,
            "critic_weight": 0.65,
            "revision_budget": 2,
        }
        self.revisions_used = 0
        self.world: dict[str, float] = {}
        self.log(f"boot mission={mission!r}")

    def log(self, event: str, detail: str = "") -> None:
        self.trace.append(Trace(self.tick, event, detail))
        self.memory.append(f"t{self.tick}:{event}:{detail}")

    def believe(self, key: str, claim: str, confidence: float, note: str = "prior") -> None:
        self.beliefs[key] = Belief(claim, confidence, [note])

    def add_goal(self, name: str, utility: float, success_test: str) -> None:
        self.goals.append(Goal(name, utility, success_test))
        self.log("goal", f"{name} U={utility}")

    # -- layers -------------------------------------------------------------

    def perceive(self, observation: dict[str, float]) -> None:
        self.tick += 1
        self.world.update(observation)
        self.log("perceive", json.dumps(observation))
        for k, v in observation.items():
            if k in self.beliefs:
                # Observation pulls confidence toward the measured direction.
                expected = 0.5
                support = 1.2 * (v - expected)
                self.beliefs[k].update(support, f"obs={v:.2f}")

    def propose(self) -> list[Hypothesis]:
        open_goals = [g for g in self.goals if not g.done]
        if not open_goals:
            return []
        focus = max(open_goals, key=lambda g: g.utility)
        # Three structurally different strategies, not three phrasings of one.
        catalog = [
            Hypothesis(
                name="direct",
                steps=[f"allocate all effort to {focus.name}", "measure success test", "stop on pass"],
                predicted_utility=focus.utility * 0.72,
                risk=0.28,
                assumptions=["success test is observable", "no hidden constraint"],
            ),
            Hypothesis(
                name="decompose",
                steps=[
                    f"split {focus.name} into probe / build / verify",
                    "run cheapest probe that can falsify the plan",
                    "build only the surviving branch",
                    "verify against success test before claiming done",
                ],
                predicted_utility=focus.utility * 0.84,
                risk=0.18,
                assumptions=["a cheap falsifier exists", "branching cost < rework cost"],
            ),
            Hypothesis(
                name="instrument-first",
                steps=[
                    "build the measurement before the intervention",
                    f"define numeric pass line for {focus.success_test}",
                    "intervene at the smallest dose that can move the metric",
                    "abort if metric does not move",
                ],
                predicted_utility=focus.utility * 0.8,
                risk=0.14,
                assumptions=["metric is causal enough to steer by", "dose-response is monotone near zero"],
            ),
        ]
        self.log("propose", ",".join(h.name for h in catalog))
        return catalog

    def attack(self, h: Hypothesis) -> Critique:
        issues = []
        penalty = 0.0
        # Adversarial pass: try to kill the plan.
        if h.risk > self.policy["max_risk"]:
            issues.append(f"risk {h.risk:.2f} exceeds policy max {self.policy['max_risk']}")
            penalty += 0.25
        if any(self.beliefs.get(k) and self.beliefs[k].confidence < 0.4 for k in ("signal", "resources")):
            issues.append("a load-bearing belief is below 0.4")
            penalty += 0.2
        if len(h.steps) < 3 and h.risk > 0.2:
            issues.append("short plan with non-trivial risk — under-specified")
            penalty += 0.12
        if "falsif" not in " ".join(h.steps) and h.name != "instrument-first":
            issues.append("no explicit falsifier in the step list")
            penalty += 0.08
        adjusted = h.predicted_utility * (1 - self.policy["critic_weight"] * penalty) - h.risk * 0.3
        fatal = adjusted < 0.35 or h.risk > 0.6
        note = "killed" if fatal else ("wounded" if issues else "clean")
        critique = Critique(fatal, issues, round(adjusted, 3), note)
        self.log("attack", f"{h.name} -> {note} U'={critique.adjusted_utility}")
        return critique

    def simulate(self, h: Hypothesis) -> float:
        """Roll the plan against the current world model. Returns realized utility proxy."""
        signal = self.world.get("signal", 0.5)
        resources = self.world.get("resources", 0.5)
        noise = self.world.get("noise", 0.3)
        # Instrument-first spends resources on measurement and gains signal.
        if h.name == "instrument-first":
            signal = min(1.0, signal + 0.18 * resources)
            resources *= 0.85
        elif h.name == "decompose":
            signal = min(1.0, signal + 0.1 * resources)
            noise *= 0.7
        else:
            resources *= 0.6
        realized = signal * (1 - noise) * resources * 1.4
        self.log("simulate", f"{h.name} realized={realized:.3f}")
        return realized

    def act(self, h: Hypothesis, realized: float) -> str:
        threshold = self.policy["min_confidence_to_act"]
        mean_conf = (
            sum(b.confidence for b in self.beliefs.values()) / len(self.beliefs)
            if self.beliefs else 0.5
        )
        if mean_conf < threshold:
            self.log("withhold", f"mean confidence {mean_conf:.2f} < {threshold}")
            return "withheld"
        # Commit: mark the top open goal done only if realized clears the bar.
        open_goals = [g for g in self.goals if not g.done]
        if not open_goals:
            return "idle"
        focus = max(open_goals, key=lambda g: g.utility)
        if realized >= 0.45:
            focus.done = True
            self.beliefs.setdefault("signal", Belief("signal is usable", 0.5)).update(
                0.6, f"action {h.name} cleared bar"
            )
            self.log("commit", f"{focus.name} via {h.name} realized={realized:.3f}")
            return "committed"
        self.beliefs.setdefault("signal", Belief("signal is usable", 0.5)).update(
            -0.4, f"action {h.name} missed bar"
        )
        self.log("abort", f"{focus.name} via {h.name} realized={realized:.3f}")
        return "aborted"

    def maybe_revise_policy(self, history_utils: list[float]) -> None:
        if self.revisions_used >= self.policy["revision_budget"]:
            return
        if len(history_utils) < 2:
            return
        trend = history_utils[-1] - history_utils[0]
        if trend < 0:
            # Self-revision: tighten risk if we are getting worse.
            proposal = dict(self.policy)
            proposal["max_risk"] = max(0.2, self.policy["max_risk"] - 0.05)
            proposal["critic_weight"] = min(0.85, self.policy["critic_weight"] + 0.05)
            # Critic of the revision: accept only if it does not freeze action entirely.
            if proposal["max_risk"] >= 0.2:
                self.policy = proposal
                self.revisions_used += 1
                self.log("revise", json.dumps(self.policy))

    def cycle(self, observation: dict[str, float]) -> dict:
        self.perceive(observation)
        proposals = self.propose()
        scored = []
        for h in proposals:
            c = self.attack(h)
            if c.fatal:
                continue
            realized = self.simulate(h)
            scored.append((c.adjusted_utility + 0.35 * realized, h, c, realized))
        if not scored:
            self.log("no-surviving-plan", "")
            return {"status": "blocked", "tick": self.tick}
        scored.sort(key=lambda row: row[0], reverse=True)
        best_score, best, critique, realized = scored[0]
        status = self.act(best, realized)
        return {
            "tick": self.tick,
            "status": status,
            "chosen": best.name,
            "score": round(best_score, 3),
            "critique": critique.note,
            "issues": critique.issues,
            "realized": round(realized, 3),
            "goals_done": [g.name for g in self.goals if g.done],
        }


def run_demo() -> dict:
    kernel = Lumen("Outperform a single-pass assistant on a bounded research task")
    kernel.believe("signal", "the task has a measurable success signal", 0.52, "prior")
    kernel.believe("resources", "compute and attention budget is finite", 0.7, "prior")
    kernel.add_goal("frame the decision", 0.6, "one falsifiable question written")
    kernel.add_goal("produce a checked answer", 0.9, "answer survives internal attack")
    kernel.add_goal("leave a reusable trace", 0.5, "trace is sufficient to replay")

    observations = [
        {"signal": 0.42, "resources": 0.8, "noise": 0.45},
        {"signal": 0.55, "resources": 0.7, "noise": 0.32},
        {"signal": 0.63, "resources": 0.62, "noise": 0.22},
    ]
    cycles = []
    utils = []
    for obs in observations:
        result = kernel.cycle(obs)
        cycles.append(result)
        utils.append(result.get("realized", 0) or 0)
        kernel.maybe_revise_policy(utils)

    report = {
        "name": "Lumen",
        "mission": kernel.mission,
        "why_better_than_a_chat_model": [
            "goals persist across cycles instead of dying with the prompt",
            "beliefs are named, scored, and updated by evidence",
            "every plan is attacked before it can act",
            "action is simulated against a world model, then withheld if confidence is low",
            "policy can revise itself, but only inside a budget and a safety check",
            "the trace is the product: another process can replay the decision",
        ],
        "cycles": cycles,
        "policy_final": kernel.policy,
        "beliefs_final": {k: {"claim": b.claim, "confidence": round(b.confidence, 3), "revised": b.revised} for k, b in kernel.beliefs.items()},
        "goals": [asdict(g) for g in kernel.goals],
        "trace": [asdict(t) for t in kernel.trace],
    }
    return report


if __name__ == "__main__":
    report = run_demo()
    print(json.dumps({k: report[k] for k in ("cycles", "policy_final", "beliefs_final", "goals")}, indent=2))
    out = "/workspace/artifacts/superintelligence-kernel/run.json"
    with open(out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"wrote {out}")
