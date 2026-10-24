import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

from lumen_backends import ModelBackend, StubBackend
from lumen_coding import (
    CodingLumen,
    is_test_path,
    run_coding_task,
    run_tests,
    safe_join,
)

FIXTURE = REPO_ROOT / "fixtures" / "buggy_calc"


@pytest.fixture
def target(tmp_path):
    dst = tmp_path / "target"
    shutil.copytree(FIXTURE, dst)
    return dst


# -- sandbox helpers -------------------------------------------------------------

def test_safe_join_accepts_inside(tmp_path):
    assert safe_join(tmp_path, "calc.py") == tmp_path.resolve() / "calc.py"
    assert safe_join(tmp_path, "pkg/mod.py") == tmp_path.resolve() / "pkg" / "mod.py"


@pytest.mark.parametrize("rel", [
    "../evil.py", "a/../../evil.py", "/etc/passwd", "", ".",
    "C:\\windows\\system32", "..",
])
def test_safe_join_rejects_escapes(tmp_path, rel):
    assert safe_join(tmp_path, rel) is None


@pytest.mark.parametrize("rel,expected", [
    ("test_calc.py", True),
    ("tests/test_x.py", True),
    ("conftest.py", True),
    ("pkg/conftest.py", True),
    ("calc_test.py", True),
    ("calc.py", False),
    ("pkg/module.py", False),
])
def test_is_test_path(rel, expected):
    assert is_test_path(rel) is expected


# -- test runner -----------------------------------------------------------------

def test_run_tests_parses_counts(target):
    result = run_tests(target, timeout=60)
    assert result.passed == 1
    assert result.failed == 1
    assert result.failing == 1
    assert "test_add" in result.output


# -- end to end with the stub ------------------------------------------------------

def test_stub_fixes_the_fixture(target, tmp_path):
    out = tmp_path / "run.json"
    report = run_coding_task(target, model=StubBackend(), max_cycles=4,
                             test_timeout=60, out_path=out)
    assert report["solved"] is True
    statuses = [c["status"] for c in report["cycles"]]
    assert "committed" in statuses
    assert statuses[-1] == "done"
    # The bug is actually fixed on disk, and only inside the target.
    assert "return a + b" in (target / "calc.py").read_text()
    assert run_tests(target, timeout=60).failing == 0
    assert "return a - b" in (FIXTURE / "calc.py").read_text()
    # The trace replays: perceive, propose, attack, simulate, commit all appear.
    events = {t["event"] for t in json.loads(out.read_text())["trace"]}
    assert {"perceive", "propose", "attack", "simulate", "commit"} <= events


def test_solved_target_reports_done_immediately(target):
    (target / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    report = run_coding_task(target, model=StubBackend(), max_cycles=2, test_timeout=60)
    assert report["solved"] is True
    assert report["cycles"][0]["status"] == "done"


# -- withholding on bad model output ------------------------------------------------

class CannedBackend(ModelBackend):
    """Returns a fixed patch list; benign critic."""

    name = "canned"

    def __init__(self, patches):
        self.patches = patches

    def propose_patches(self, context):
        return self.patches

    def critique_patch(self, patch, context):
        return {"fatal": False, "issues": [], "penalty": 0.0, "note": "ok"}


def _candidate(path, content, name="c"):
    return {"name": name, "rationale": "", "confidence": 0.8,
            "edits": [{"path": path, "new_content": content}]}


def test_garbage_proposals_withhold(target):
    class Garbage(ModelBackend):
        name = "garbage"

        def propose_patches(self, context):
            return None

    report = run_coding_task(target, model=Garbage(), max_cycles=1, test_timeout=60)
    assert report["solved"] is False
    assert report["cycles"][0]["status"] == "withheld"
    assert "return a - b" in (target / "calc.py").read_text()


def test_attack_kills_sandbox_escape_and_test_edits(target):
    backend = CannedBackend([
        _candidate("../outside.py", "x = 1\n", name="escape"),
        _candidate("test_calc.py", "def test_add():\n    assert True\n", name="cheat"),
        _candidate("calc.py", "def add(a, b:\n", name="broken-syntax"),
    ])
    report = run_coding_task(target, model=backend, max_cycles=1, test_timeout=60)
    assert report["cycles"][0]["status"] == "withheld"
    assert not (target.parent / "outside.py").exists()
    assert "assert add(2, 3) == 5" in (target / "test_calc.py").read_text()


def test_non_improving_patch_is_withheld(target):
    # Valid syntax, inside the sandbox, but makes nothing better.
    backend = CannedBackend([
        _candidate("calc.py", "def add(a, b):\n    return 0\n\n\ndef sub(a, b):\n    return a - b\n"),
    ])
    report = run_coding_task(target, model=backend, max_cycles=1, test_timeout=60)
    assert report["cycles"][0]["status"] == "withheld"
    assert "return a - b" in (target / "calc.py").read_text()


def test_low_confidence_withholds(target):
    kernel = CodingLumen(target, model=StubBackend(), test_timeout=60)
    kernel.beliefs["patchable"].confidence = 0.1
    kernel.beliefs["test_signal"].confidence = 0.1
    result = kernel.cycle()
    assert result["status"] == "withheld"
    assert "return a - b" in (target / "calc.py").read_text()


def test_revision_budget_respected_when_stuck(target):
    class Garbage(ModelBackend):
        name = "garbage"

        def propose_patches(self, context):
            return None

    report = run_coding_task(target, model=Garbage(), max_cycles=6, test_timeout=60)
    revisions = [t for t in report["trace"] if t["event"] == "revise"]
    assert len(revisions) <= report["policy_final"]["revision_budget"]


# -- CLI ------------------------------------------------------------------------------

def test_cli_coding_end_to_end(target, tmp_path):
    out = tmp_path / "run.json"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "lumen.py"), "--task", "coding",
         "--target", str(target), "--out", str(out)],
        capture_output=True, text=True, cwd=str(tmp_path),
        env={**os.environ, "LUMEN_MODEL": "stub"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads(out.read_text())
    assert report["solved"] is True
