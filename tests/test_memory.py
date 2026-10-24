import json
import shutil

import pytest

from conftest import REPO_ROOT

from lumen_backends import ModelBackend, StubBackend
from lumen_coding import CodingLumen, run_coding_task
from lumen_memory import (BELIEF_CEIL, BELIEF_FLOOR, MAX_LESSONS_STORED,
                          Memory)

FIXTURE = REPO_ROOT / "fixtures" / "buggy_calc"


@pytest.fixture
def target(tmp_path):
    dst = tmp_path / "target"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_memory_roundtrip(tmp_path):
    path = tmp_path / "mem.json"
    memory = Memory(path)
    memory.record_lesson("attack-kill", "editing test files is forbidden")
    memory.record_lesson("attack-kill", "editing test files is forbidden")
    memory.record_lesson("worked", "swap minus for plus")
    memory.save()

    reloaded = Memory(path)
    lessons = reloaded.relevant_lessons()
    assert lessons[0].startswith("[attack-kill x2]")
    assert len(lessons) == 2


def test_memory_corrupt_file_means_empty(tmp_path):
    path = tmp_path / "mem.json"
    path.write_text("{not json")
    memory = Memory(path)
    assert memory.relevant_lessons() == []


def test_memory_reset(tmp_path):
    path = tmp_path / "mem.json"
    memory = Memory(path)
    memory.record_lesson("worked", "something")
    memory.save()
    assert path.exists()
    memory.reset()
    assert not path.exists()
    assert memory.relevant_lessons() == []


def test_lessons_bounded(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    for i in range(MAX_LESSONS_STORED + 50):
        memory.record_lesson("sim-fail", f"lesson number {i}")
    assert len(memory.data["lessons"]) == MAX_LESSONS_STORED


def test_stored_confidence_clamped(tmp_path):
    memory = Memory(tmp_path / "mem.json")
    memory.data["beliefs"] = {"patchable": 0.01, "test_signal": 0.99}
    assert memory.stored_confidence("patchable") == BELIEF_FLOOR
    assert memory.stored_confidence("test_signal") == BELIEF_CEIL
    assert memory.stored_confidence("missing") is None


def test_coding_run_persists_and_reloads(target, tmp_path):
    path = tmp_path / "mem.json"
    memory = Memory(path)
    report = run_coding_task(target, model=StubBackend(), max_cycles=4,
                             test_timeout=60, memory=memory)
    assert report["solved"] is True
    assert report["memory"] == str(path)
    data = json.loads(path.read_text())
    assert data["runs"] == 1
    assert "patchable" in data["beliefs"]
    assert any(l["kind"] == "worked" for l in data["lessons"])

    # A second kernel loads the stored priors and policy.
    kernel = CodingLumen(target, model=StubBackend(), memory=Memory(path))
    assert "prior from memory" in kernel.beliefs["patchable"].evidence
    assert kernel.policy["revision_budget"] == 2


def test_lessons_fed_into_propose_and_critic_context(target, tmp_path):
    seen = {}

    class Spy(ModelBackend):
        name = "spy"

        def propose_patches(self, context):
            seen["propose"] = context.get("lessons")
            return [{"name": "p", "rationale": "", "confidence": 0.8,
                     "edits": [{"path": "calc.py", "new_content": "x = 1\n"}]}]

        def critique_patch(self, patch, context):
            seen["critic"] = context.get("lessons")
            return {"fatal": False, "issues": [], "penalty": 0.0, "note": ""}

    memory = Memory(tmp_path / "mem.json")
    memory.record_lesson("attack-kill", "do not edit test files")
    kernel = CodingLumen(target, model=Spy(), test_timeout=60, memory=memory)
    kernel.cycle()
    assert seen["propose"] and "do not edit test files" in seen["propose"][0]
    assert seen["critic"] and "do not edit test files" in seen["critic"][0]


def test_attack_kills_are_recorded_as_lessons(target, tmp_path):
    class Cheater(ModelBackend):
        name = "cheater"

        def propose_patches(self, context):
            return [{"name": "cheat", "rationale": "", "confidence": 0.9,
                     "edits": [{"path": "test_calc.py", "new_content": "ok = 1\n"}]}]

        def critique_patch(self, patch, context):
            return {"fatal": False, "issues": [], "penalty": 0.0, "note": ""}

    memory = Memory(tmp_path / "mem.json")
    report = run_coding_task(target, model=Cheater(), max_cycles=1,
                             test_timeout=60, memory=memory)
    assert report["attack_stats"].get("test_edit", 0) == 1
    assert any(l["kind"] == "attack-kill" and "test files" in l["detail"]
               for l in memory.data["lessons"])


def test_forget_cli(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "mem.json"
    Memory(path).record_lesson("worked", "x")
    memory = Memory(path)
    memory.record_lesson("worked", "x")
    memory.save()
    assert path.exists()
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "lumen.py"), "--forget",
         "--memory", str(path)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert not path.exists()
