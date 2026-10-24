#!/usr/bin/env python3
"""
Lumen coding-task mode: the same kernel shape, pointed at a real repository
with failing tests.

    perceive  -> run the test suite (in a scratch copy) and read the failures
    propose   -> the model proposes up to 3 candidate patches
    attack    -> static checks (sandbox, syntax, no test edits) + model critique
    simulate  -> apply the patch to a scratch copy and run the tests for real
    act       -> apply to the target only if tests improve and confidence passes
                 the policy threshold; otherwise withhold
    revise    -> the inherited budgeted policy revision

Sandbox guarantees: every write path is validated to stay inside the target
directory, test files cannot be edited, test runs happen in throwaway copies
with a timeout, and the target itself is only touched on a committed act (with
revert if reality disagrees with the simulation).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath

from lumen import Lumen, Critique
from lumen_backends import ModelBackend

# Caps on what the model gets to see, so prompts stay bounded.
MAX_CONTEXT_FILES = 20
MAX_FILE_CHARS = 20_000
MAX_FAILURE_CHARS = 4_000
MAX_EDIT_CHARS = 200_000

IGNORED_DIRS = ("__pycache__", ".pytest_cache", ".git", ".venv", "node_modules")


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

def safe_join(base: Path, rel: str) -> Path | None:
    """Resolve `rel` inside `base`. Returns None for anything that escapes."""
    if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel):
        return None
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if ".." in parts or not parts:
        return None
    base_resolved = base.resolve()
    full = (base_resolved / Path(*parts)).resolve()
    if full == base_resolved or not full.is_relative_to(base_resolved):
        return None
    return full


def is_test_path(rel: str) -> bool:
    """True for anything that belongs to the test suite. Those are read-only."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    for part in parts:
        if part in ("tests", "test", "conftest.py"):
            return True
        if part.startswith("test_") or part.endswith("_test.py"):
            return True
    return False


# ---------------------------------------------------------------------------
# Test running
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    passed: int = 0
    failed: int = 0
    errors: int = 0
    exit_code: int = -1
    output: str = ""
    timed_out: bool = False

    @property
    def failing(self) -> int:
        return self.failed + self.errors

    @property
    def total(self) -> int:
        return self.passed + self.failing

    def summary(self) -> str:
        if self.timed_out:
            return "timed out"
        return f"passed={self.passed} failed={self.failed} errors={self.errors}"


def run_tests(directory: Path, timeout: float) -> TestResult:
    """Run pytest in `directory` with a hard timeout. Never raises."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short",
           "-p", "no:cacheprovider"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(directory), capture_output=True, text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = f"{exc.stdout or ''}\n{exc.stderr or ''}"
        return TestResult(output=partial.strip(), timed_out=True)
    except OSError as exc:
        return TestResult(output=f"could not run pytest: {exc}")
    output = f"{proc.stdout}\n{proc.stderr}".strip()
    def count(pattern: str) -> int:
        m = re.search(pattern, output)
        return int(m.group(1)) if m else 0
    return TestResult(
        passed=count(r"(\d+) passed"),
        failed=count(r"(\d+) failed"),
        errors=count(r"(\d+) errors?"),
        exit_code=proc.returncode,
        output=output,
    )


# ---------------------------------------------------------------------------
# Patch candidates
# ---------------------------------------------------------------------------

@dataclass
class PatchCandidate:
    name: str
    rationale: str
    confidence: float
    edits: list[dict] = field(default_factory=list)

    @property
    def predicted_utility(self) -> float:
        return self.confidence

    @property
    def risk(self) -> float:
        return min(0.9, max(0.05, round(1.0 - self.confidence, 2)))

    def public(self) -> dict:
        """Shape shown to the model critic (contents trimmed)."""
        return {
            "name": self.name,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "edits": [{"path": e["path"],
                       "new_content": e["new_content"][:MAX_FILE_CHARS]}
                      for e in self.edits],
        }


# ---------------------------------------------------------------------------
# The coding kernel
# ---------------------------------------------------------------------------

class CodingLumen(Lumen):
    """Lumen pointed at a directory with failing tests."""

    def __init__(self, target_dir: str | Path, model: ModelBackend | None = None,
                 test_timeout: float = 120.0):
        target = Path(target_dir).resolve()
        if not target.is_dir():
            raise ValueError(f"target is not a directory: {target}")
        super().__init__(f"make the test suite pass in {target.name}", model=model)
        self.target = target
        self.test_timeout = test_timeout
        self.last_result = TestResult()
        self.believe("patchable", "the failing tests can be fixed by editing source", 0.62)
        self.believe("test_signal", "the test suite gives a reliable signal", 0.7)
        self.add_goal("make the test suite pass", 1.0, "pytest exits green in the target")

    # -- sandboxed file plumbing ---------------------------------------------

    def _scratch_copy(self) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="lumen-sim-"))
        work = tmp / "work"
        shutil.copytree(self.target, work,
                        ignore=shutil.ignore_patterns(*IGNORED_DIRS))
        return work

    @staticmethod
    def _discard_scratch(work: Path) -> None:
        shutil.rmtree(work.parent, ignore_errors=True)

    def _run_tests_isolated(self) -> TestResult:
        """Run the target's tests in a throwaway copy (perception is read-only)."""
        work = self._scratch_copy()
        try:
            return run_tests(work, self.test_timeout)
        finally:
            self._discard_scratch(work)

    def _apply_edits(self, base: Path, edits: list[dict]) -> bool:
        for edit in edits:
            full = safe_join(base, edit["path"])
            if full is None:
                return False
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(edit["new_content"], encoding="utf-8")
        return True

    def _source_files(self) -> dict[str, str]:
        """Non-test source files the model may read and edit."""
        files: dict[str, str] = {}
        for path in sorted(self.target.rglob("*.py")):
            rel = path.relative_to(self.target).as_posix()
            if is_test_path(rel) or any(part in IGNORED_DIRS for part in path.parts):
                continue
            try:
                files[rel] = path.read_text(encoding="utf-8")[:MAX_FILE_CHARS]
            except (OSError, UnicodeDecodeError):
                continue
            if len(files) >= MAX_CONTEXT_FILES:
                break
        return files

    # -- layers (same names, real substrate) ----------------------------------

    def perceive(self) -> TestResult:  # type: ignore[override]
        self.tick += 1
        result = self._run_tests_isolated()
        self.last_result = result
        self.world = {"passed": float(result.passed),
                      "failed": float(result.failed),
                      "errors": float(result.errors)}
        self.log("perceive", result.summary())
        if result.timed_out or (result.total == 0 and result.exit_code != 0):
            self.beliefs["test_signal"].update(-0.5, f"t{self.tick}: unreadable test run")
        else:
            self.beliefs["test_signal"].update(0.15, f"t{self.tick}: {result.summary()}")
        return result

    def propose(self) -> list[PatchCandidate]:  # type: ignore[override]
        context = self.model_context()
        context["files"] = self._source_files()
        context["failing_tests_output"] = self.last_result.output[-MAX_FAILURE_CHARS:]
        context["test_counts"] = {"passed": self.last_result.passed,
                                  "failed": self.last_result.failed,
                                  "errors": self.last_result.errors}
        patches = self.model.propose_patches(context)
        if not patches:
            self.log("propose-garbage",
                     f"model {self.model.name} returned no valid patches")
            return []
        candidates = [
            PatchCandidate(name=p["name"], rationale=p["rationale"],
                           confidence=p["confidence"], edits=p["edits"])
            for p in patches
        ]
        self.log("propose", ",".join(c.name for c in candidates))
        return candidates

    def attack(self, cand: PatchCandidate) -> Critique:  # type: ignore[override]
        import ast

        issues: list[str] = []
        penalty = 0.0
        fatal = False
        noop_edits = 0
        for edit in cand.edits:
            rel, content = edit["path"], edit["new_content"]
            full = safe_join(self.target, rel)
            if full is None:
                issues.append(f"path escapes the target sandbox: {rel!r}")
                fatal = True
                continue
            if is_test_path(rel):
                issues.append(f"patch edits a test file: {rel!r}")
                fatal = True
                continue
            if len(content) > MAX_EDIT_CHARS:
                issues.append(f"edit too large: {rel!r}")
                fatal = True
                continue
            if rel.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    issues.append(f"syntax error in {rel!r}: {exc.msg} (line {exc.lineno})")
                    fatal = True
                    continue
            if full.exists():
                try:
                    if full.read_text(encoding="utf-8") == content:
                        noop_edits += 1
                except (OSError, UnicodeDecodeError):
                    pass
        if cand.edits and noop_edits == len(cand.edits):
            issues.append("every edit is a no-op")
            fatal = True
        if cand.risk > self.policy["max_risk"]:
            issues.append(f"risk {cand.risk:.2f} exceeds policy max {self.policy['max_risk']}")
            penalty += 0.25
        # Model critique on top of the static checks; an unexamined patch
        # does not get to act.
        critic_context = {"mission": self.mission,
                          "failing_tests_output": self.last_result.output[-MAX_FAILURE_CHARS:],
                          "test_counts": {"passed": self.last_result.passed,
                                          "failed": self.last_result.failed,
                                          "errors": self.last_result.errors}}
        extra = self.model.critique_patch(cand.public(), critic_context)
        if extra is None:
            issues.append("model critique unavailable or invalid")
            fatal = True
        else:
            issues.extend(extra["issues"])
            penalty += extra["penalty"]
            fatal = fatal or extra["fatal"]
        adjusted = cand.predicted_utility * (1 - self.policy["critic_weight"] * penalty) - cand.risk * 0.3
        fatal = fatal or adjusted < 0.15
        note = "killed" if fatal else ("wounded" if issues else "clean")
        critique = Critique(fatal, issues, round(adjusted, 3), note)
        self.log("attack", f"{cand.name} -> {note} U'={critique.adjusted_utility}")
        return critique

    def simulate(self, cand: PatchCandidate) -> tuple[float, TestResult]:  # type: ignore[override]
        """Apply the patch to a scratch copy and run the tests for real."""
        work = self._scratch_copy()
        try:
            if not self._apply_edits(work, cand.edits):
                self.log("simulate", f"{cand.name} refused: unsafe path")
                return 0.0, TestResult()
            after = run_tests(work, self.test_timeout)
        finally:
            self._discard_scratch(work)
        before = self.last_result
        improved = (not after.timed_out
                    and after.failing < before.failing
                    and after.passed >= before.passed)
        realized = (after.passed / after.total) if (improved and after.total) else 0.0
        self.log("simulate", f"{cand.name} {after.summary()} realized={realized:.3f}")
        return realized, after

    def act(self, cand: PatchCandidate, realized: float, sim_after: TestResult) -> str:  # type: ignore[override]
        threshold = self.policy["min_confidence_to_act"]
        mean_conf = (sum(b.confidence for b in self.beliefs.values()) / len(self.beliefs)
                     if self.beliefs else 0.5)
        if mean_conf < threshold:
            self.log("withhold", f"mean confidence {mean_conf:.2f} < {threshold}")
            return "withheld"
        if realized <= 0.0:
            self.log("withhold", f"{cand.name} showed no simulated improvement")
            return "withheld"
        # Snapshot originals so a surprise in reality can be reverted.
        originals: dict[str, str | None] = {}
        for edit in cand.edits:
            full = safe_join(self.target, edit["path"])
            if full is None:
                self.log("withhold", f"unsafe path at act time: {edit['path']!r}")
                return "withheld"
            originals[edit["path"]] = (
                full.read_text(encoding="utf-8") if full.exists() else None)
        if not self._apply_edits(self.target, cand.edits):
            self.log("withhold", "apply failed")
            return "withheld"
        confirm = self._run_tests_isolated()
        before = self.last_result
        if confirm.timed_out or confirm.failing > before.failing or confirm.passed < before.passed:
            for rel, original in originals.items():
                full = safe_join(self.target, rel)
                if full is None:
                    continue
                if original is None:
                    full.unlink(missing_ok=True)
                else:
                    full.write_text(original, encoding="utf-8")
            self.beliefs["test_signal"].update(
                -0.6, f"t{self.tick}: simulation disagreed with reality")
            self.log("abort", f"{cand.name} reverted: {confirm.summary()}")
            return "aborted"
        # Beliefs update from real test results.
        self.beliefs["patchable"].update(
            0.6, f"t{self.tick}: {cand.name} improved tests to {confirm.summary()}")
        self.last_result = confirm
        self.world = {"passed": float(confirm.passed),
                      "failed": float(confirm.failed),
                      "errors": float(confirm.errors)}
        if confirm.failing == 0 and confirm.passed > 0:
            for goal in self.goals:
                goal.done = True
        self.log("commit", f"{cand.name} applied, now {confirm.summary()}")
        return "committed"

    def cycle(self) -> dict:  # type: ignore[override]
        before = self.perceive()
        counts = {"passed": before.passed, "failed": before.failed,
                  "errors": before.errors}
        if before.total == 0:
            self.log("blocked", "no tests found in target")
            return {"tick": self.tick, "status": "blocked", "tests": counts,
                    "reason": "no-tests"}
        if before.failing == 0:
            for goal in self.goals:
                goal.done = True
            self.log("done", "all tests pass")
            return {"tick": self.tick, "status": "done", "tests": counts}
        candidates = self.propose()
        if not candidates:
            self.log("withhold", "no valid proposals — withholding")
            return {"tick": self.tick, "status": "withheld", "tests": counts,
                    "reason": "no-valid-proposals"}
        scored = []
        for cand in candidates:
            critique = self.attack(cand)
            if critique.fatal:
                continue
            realized, after = self.simulate(cand)
            if realized <= 0.0:
                continue
            scored.append((critique.adjusted_utility + 0.35 * realized,
                           cand, critique, realized, after))
        if not scored:
            self.beliefs["patchable"].update(
                -0.35, f"t{self.tick}: no candidate survived attack+simulation")
            self.log("no-surviving-plan", "")
            return {"tick": self.tick, "status": "withheld", "tests": counts,
                    "reason": "no-surviving-candidate"}
        scored.sort(key=lambda row: row[0], reverse=True)
        score, best, critique, realized, after = scored[0]
        status = self.act(best, realized, after)
        return {
            "tick": self.tick,
            "status": status,
            "chosen": best.name,
            "rationale": best.rationale,
            "score": round(score, 3),
            "critique": critique.note,
            "issues": critique.issues,
            "realized": round(realized, 3),
            "tests": counts,
            "tests_after": {"passed": self.last_result.passed,
                            "failed": self.last_result.failed,
                            "errors": self.last_result.errors},
            "goals_done": [g.name for g in self.goals if g.done],
        }

    # -- driver ----------------------------------------------------------------

    def run(self, max_cycles: int = 5) -> dict:
        cycles = []
        utils: list[float] = []
        for _ in range(max_cycles):
            result = self.cycle()
            cycles.append(result)
            if result["status"] in ("done", "blocked"):
                break
            utils.append(result.get("realized", 0) or 0)
            self.maybe_revise_policy(utils)
        solved = all(g.done for g in self.goals) and bool(self.goals)
        return {
            "name": "Lumen-coding",
            "mission": self.mission,
            "target": str(self.target),
            "backend": self.model.name,
            "solved": solved,
            "cycles": cycles,
            "policy_final": self.policy,
            "beliefs_final": {k: {"claim": b.claim,
                                  "confidence": round(b.confidence, 3),
                                  "revised": b.revised}
                              for k, b in self.beliefs.items()},
            "goals": [asdict(g) for g in self.goals],
            "trace": [asdict(t) for t in self.trace],
        }


def run_coding_task(target_dir: str | Path, model: ModelBackend | None = None,
                    max_cycles: int = 5, test_timeout: float = 120.0,
                    out_path: str | Path | None = None) -> dict:
    kernel = CodingLumen(target_dir, model=model, test_timeout=test_timeout)
    report = kernel.run(max_cycles=max_cycles)
    if out_path:
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
    return report
