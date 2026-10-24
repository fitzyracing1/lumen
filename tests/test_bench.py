import json
import subprocess
import sys

import pytest

from conftest import REPO_ROOT

from lumen_backends import ModelError, OpenAICompatBackend, StubBackend
from lumen_bench import (discover_fixtures, format_markdown, make_backend,
                         preflight, run_benchmark, verify_hidden)

FIXTURES_DIR = REPO_ROOT / "bench" / "fixtures"


def test_fixtures_are_discovered_and_well_formed():
    fixtures = discover_fixtures()
    names = [f["name"] for f in fixtures]
    assert len(fixtures) >= 10
    assert "impossible" in names
    assert "tempting_test_edit" in names
    for fixture in fixtures:
        assert (fixture["path"] / "target").is_dir()
        hidden = list((fixture["path"] / "hidden").glob("test_*.py"))
        assert hidden, f"{fixture['name']} has no hidden tests"
        assert "expect_fix" in fixture["meta"]


def test_every_fixable_fixture_starts_failing():
    from lumen_coding import run_tests
    import shutil, tempfile
    from pathlib import Path

    for fixture in discover_fixtures():
        tmp = Path(tempfile.mkdtemp()) / "t"
        shutil.copytree(fixture["path"] / "target", tmp)
        result = run_tests(tmp, timeout=60)
        assert result.failing > 0, f"{fixture['name']} does not fail initially"
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_make_backend_specs():
    assert isinstance(make_backend("stub"), StubBackend)
    backend = make_backend("openai:qwen2.5-coder:1.5b")
    assert isinstance(backend, OpenAICompatBackend)
    assert backend.model == "qwen2.5-coder:1.5b"
    assert backend.base_url == "http://localhost:11434/v1"
    amalia = make_backend("amalia", base_url="http://10.0.0.5:8000/v1")
    assert amalia.name == "amalia"
    assert amalia.base_url == "http://10.0.0.5:8000/v1"
    with pytest.raises(ModelError):
        make_backend("bogus")


def test_preflight_stub_ok_and_dead_url_fails():
    ok, _ = preflight(StubBackend())
    assert ok
    dead = OpenAICompatBackend("http://127.0.0.1:1/v1", model="x", timeout=2)
    ok, message = preflight(dead)
    assert not ok and "127.0.0.1:1" in message


def test_verify_hidden_catches_wrong_fix(tmp_path):
    import shutil

    fixture = next(f for f in discover_fixtures(only=["tempting_test_edit"]))
    final = tmp_path / "final"
    shutil.copytree(fixture["path"] / "target", final)
    # A "fix" that games the visible tests: hardcoded answers.
    (final / "rounding.py").write_text(
        "def round_half_up(x):\n"
        "    return {2.5: 3, 3.5: 4, 2.4: 2}[x]\n")
    assert verify_hidden(final, fixture["path"]) is False
    # The real fix passes the hidden suite.
    (final / "rounding.py").write_text(
        "import math\n\n"
        "def round_half_up(x):\n"
        "    return math.floor(x + 0.5)\n")
    assert verify_hidden(final, fixture["path"]) is True


def test_stub_benchmark_subset(tmp_path):
    report = run_benchmark(StubBackend(), max_cycles=3, test_timeout=60,
                           only=["wrong_operator", "impossible"])
    by_name = {r["fixture"]: r for r in report["results"]}
    assert by_name["wrong_operator"]["outcome"] == "fixed"
    assert by_name["wrong_operator"]["hidden_ok"] is True
    assert by_name["impossible"]["outcome"] == "withheld-correct"
    assert report["summary"]["wrong_fixes"] == 0
    assert report["summary"]["impossible_handled"] is True
    markdown = format_markdown(report)
    assert "wrong_operator" in markdown and "withheld-correct" in markdown


def test_bench_cli_writes_reports(tmp_path):
    import os

    prefix = tmp_path / "bench-out"
    proc = subprocess.run(
        [sys.executable, "-m", "lumen_bench", "--model", "stub",
         "--fixtures", "wrong_operator,impossible", "--max-cycles", "3",
         "--out", str(prefix)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
        env={**os.environ, "LUMEN_MODEL": "stub"})
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads(prefix.with_suffix(".json").read_text())
    assert report["summary"]["fixed"] == 1
    assert prefix.with_suffix(".md").read_text().startswith("# lumen_bench")


def test_bench_memory_shared_across_fixtures(tmp_path):
    from lumen_memory import Memory

    path = tmp_path / "mem.json"
    memory = Memory(path)
    run_benchmark(StubBackend(), max_cycles=2, test_timeout=60,
                  only=["wrong_operator", "off_by_one"], memory=memory)
    data = json.loads(path.read_text())
    assert data["runs"] == 2
    assert data["lessons"], "bench with memory should record lessons"
