import json
import os
import subprocess
import sys

from conftest import REPO_ROOT

from lumen import Lumen, run_demo
from lumen_backends import ModelBackend


class GarbageBackend(ModelBackend):
    """Simulates a model whose output never validates."""

    name = "garbage"

    def propose_plans(self, context):
        return None

    def critique_plan(self, plan, context):
        return None

    def propose_patches(self, context):
        return None

    def critique_patch(self, patch, context):
        return None


def test_demo_runs_three_cycles():
    report = run_demo()
    assert len(report["cycles"]) == 3
    assert report["goals"], "demo should have goals"
    assert report["trace"], "trace must be present for replay"


def test_demo_is_deterministic_with_stub():
    assert run_demo() == run_demo()


def test_revision_budget_is_respected():
    report = run_demo()
    revisions = [t for t in report["trace"] if t["event"] == "revise"]
    assert len(revisions) <= report["policy_final"]["revision_budget"]


def test_garbage_model_blocks_instead_of_acting():
    kernel = Lumen("mission", model=GarbageBackend())
    kernel.believe("signal", "claim", 0.9)
    kernel.add_goal("g", 0.9, "test")
    result = kernel.cycle({"signal": 0.6, "resources": 0.7, "noise": 0.2})
    assert result["status"] == "blocked"
    assert not any(g.done for g in kernel.goals)
    assert any(t.event == "propose-garbage" for t in kernel.trace)


def test_garbage_critic_kills_plans():
    class GoodPlansBadCritic(GarbageBackend):
        def propose_plans(self, context):
            return [{"name": "p", "steps": ["a", "b", "c", "falsify d"],
                     "predicted_utility": 0.9, "risk": 0.1, "assumptions": []}]

    kernel = Lumen("mission", model=GoodPlansBadCritic())
    kernel.believe("signal", "claim", 0.9)
    kernel.add_goal("g", 0.9, "test")
    result = kernel.cycle({"signal": 0.6, "resources": 0.7, "noise": 0.2})
    assert result["status"] == "blocked"


def test_cli_demo_writes_run_json(tmp_path):
    out = tmp_path / "run.json"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "lumen.py"), "--out", str(out)],
        capture_output=True, text=True,
        env={**os.environ, "LUMEN_MODEL": "stub"},
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())
    assert len(report["cycles"]) == 3
