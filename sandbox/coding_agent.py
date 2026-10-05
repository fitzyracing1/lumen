"""Coding agent Lumen can run. The result is a source file, not a tick log."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "responses" / "code"


def run(task: str = "score a plan and reject it if risk is too high") -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    module = OUT / "plan_gate.py"
    test = OUT / "test_plan_gate.py"
    module.write_text(textwrap.dedent('''\
        """Plan gate written by the Lumen coding agent."""


        def score(predicted_utility: float, risk: float, critic_weight: float = 0.65) -> float:
            if not 0 <= risk <= 1:
                raise ValueError("risk must be between 0 and 1")
            return predicted_utility * (1 - critic_weight * risk) - risk * 0.3


        def allow(predicted_utility: float, risk: float, max_risk: float = 0.45) -> bool:
            if risk > max_risk:
                return False
            return score(predicted_utility, risk) >= 0.35
    '''))
    test.write_text(textwrap.dedent('''\
        import unittest
        from plan_gate import allow, score


        class PlanGateTest(unittest.TestCase):
            def test_high_risk_is_refused(self):
                self.assertFalse(allow(0.9, 0.8))

            def test_clean_plan_passes(self):
                self.assertTrue(allow(0.84, 0.18))
                self.assertGreater(score(0.84, 0.18), 0.35)


        if __name__ == "__main__":
            unittest.main()
    '''))
    proc = subprocess.run(
        ["python3", "-m", "unittest", "test_plan_gate"],
        cwd=OUT,
        capture_output=True,
        text=True,
    )
    note = OUT / "RESULT.md"
    passed = proc.returncode == 0
    note.write_text(
        f"# Coding agent result\n\nTask: {task}\n\n"
        f"Wrote `{module.name}` and `{test.name}`.\n\n"
        f"Tests: {'passed' if passed else 'failed'}\n\n```\n{proc.stdout}{proc.stderr}\n```\n"
    )
    return {
        "task": task,
        "files": [str(module), str(test), str(note)],
        "passed": passed,
        "output": (proc.stdout + proc.stderr).strip(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
