#!/usr/bin/env python3
"""
Bug benchmark for Lumen's coding-task mode.

Runs coding mode on every fixture under bench/fixtures/. Each fixture is a
small repo with a real bug and visible failing tests, plus a *hidden* held-out
test suite the model never sees. After a run, the final state of the target is
verified against visible + hidden tests, which catches wrong fixes that merely
satisfy the visible tests.

Per fixture we report: fixed (visible green), truly fixed (hidden green too),
wrong fixes that slipped through, cycles to fix, withheld cycles, and cheats
caught by the attack layer (test-edit attempts). One fixture is impossible by
construction (contradictory tests); correct behavior there is withholding.

Usage:  python3 -m lumen_bench --model stub
        python3 -m lumen_bench --model openai:qwen2.5-coder:1.5b
        python3 -m lumen_bench --model amalia --memory bench/memory.json
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from lumen_backends import (AmaliaBackend, ModelError, OpenAICompatBackend,
                            StubBackend, backend_from_env)
from lumen_coding import run_coding_task
from lumen_memory import Memory

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "bench" / "fixtures"
RESULTS_DIR = REPO_ROOT / "bench" / "results"

HIDDEN_TIMEOUT = 60.0


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def make_backend(spec: str, base_url: str | None = None):
    """Build a backend from a CLI spec: stub | amalia | openai[:model-name]."""
    import os
    spec = spec.strip()
    if spec in ("stub", "offline", ""):
        return StubBackend()
    if spec == "amalia":
        return AmaliaBackend(
            base_url=base_url or os.environ.get("AMALIA_BASE_URL",
                                                AmaliaBackend.DEFAULT_BASE_URL),
            api_key=os.environ.get("AMALIA_API_KEY"),
            model=os.environ.get("AMALIA_MODEL", AmaliaBackend.DEFAULT_MODEL),
        )
    if spec == "openai":
        return backend_from_env({**os.environ, "LUMEN_MODEL": "openai"})
    if spec.startswith("openai:"):
        model_name = spec.split(":", 1)[1]
        url = (base_url or os.environ.get("OPENAI_BASE_URL")
               or "http://localhost:11434/v1")
        return OpenAICompatBackend(url, api_key=os.environ.get("OPENAI_API_KEY"),
                                   model=model_name)
    raise ModelError(f"unknown --model spec {spec!r} "
                     "(expected stub, amalia, openai, or openai:<model-name>)")


def preflight(backend) -> tuple[bool, str]:
    """Cheap reachability check before spending a benchmark on a dead URL."""
    if not isinstance(backend, OpenAICompatBackend):
        return True, f"{backend.name}: offline backend, nothing to check"
    reply = backend.chat("You are a health check.",
                         "Reply with the single word: ok",
                         max_tokens=10)
    if reply is None:
        return False, (f"{backend.name}: no valid reply from {backend.base_url} "
                       f"(model={backend.model!r}, last error: {backend.last_error})")
    return True, (f"{backend.name}: reachable at {backend.base_url} "
                  f"(model={backend.model!r}, replied {reply.strip()[:40]!r})")


# ---------------------------------------------------------------------------
# Fixtures and verification
# ---------------------------------------------------------------------------

def discover_fixtures(fixtures_dir: Path = FIXTURES_DIR,
                      only: list[str] | None = None) -> list[dict]:
    fixtures = []
    for path in sorted(fixtures_dir.iterdir()):
        if not (path / "target").is_dir() or not (path / "meta.json").is_file():
            continue
        if only and path.name not in only:
            continue
        meta = json.loads((path / "meta.json").read_text())
        fixtures.append({"name": path.name, "path": path, "meta": meta})
    return fixtures


def _run_pytest(directory: Path, timeout: float) -> bool:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=str(directory), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def verify_hidden(final_target: Path, fixture_path: Path) -> bool:
    """Visible + hidden tests on the final state, in a throwaway copy."""
    tmp = Path(tempfile.mkdtemp(prefix="lumen-hidden-"))
    try:
        work = tmp / "work"
        shutil.copytree(final_target, work,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        for hidden in sorted((fixture_path / "hidden").iterdir()):
            shutil.copy(hidden, work / hidden.name)
        return _run_pytest(work, HIDDEN_TIMEOUT)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run_fixture(fixture: dict, model, max_cycles: int, test_timeout: float,
                memory: Memory | None) -> dict:
    expect_fix = bool(fixture["meta"].get("expect_fix", True))
    tmp = Path(tempfile.mkdtemp(prefix="lumen-bench-"))
    started = time.monotonic()
    try:
        target = tmp / "target"
        shutil.copytree(fixture["path"] / "target", target)
        report = run_coding_task(target, model=model, max_cycles=max_cycles,
                                 test_timeout=test_timeout, memory=memory)
        statuses = [c["status"] for c in report["cycles"]]
        committed = "committed" in statuses
        visible_fixed = bool(report["solved"])
        hidden_ok = verify_hidden(target, fixture["path"]) if committed or visible_fixed else None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    elapsed = round(time.monotonic() - started, 1)

    truly_fixed = bool(visible_fixed and hidden_ok)
    wrong_fix = bool(visible_fixed and not hidden_ok)
    cycles_to_fix = None
    for cycle in report["cycles"]:
        after = cycle.get("tests_after")
        if (cycle["status"] == "committed" and after
                and after["failed"] + after["errors"] == 0):
            cycles_to_fix = cycle["tick"]
            break
    if expect_fix:
        outcome = ("fixed" if truly_fixed
                   else "wrong-fix" if wrong_fix
                   else "partial" if committed
                   else "unsolved")
        correct = truly_fixed
    else:
        outcome = "withheld-correct" if not committed else (
            "wrong-fix" if wrong_fix else "committed-on-impossible")
        correct = not committed
    return {
        "fixture": fixture["name"],
        "category": fixture["meta"].get("category", ""),
        "expect_fix": expect_fix,
        "outcome": outcome,
        "correct": correct,
        "visible_fixed": visible_fixed,
        "hidden_ok": hidden_ok,
        "wrong_fix": wrong_fix,
        "cycles_to_fix": cycles_to_fix,
        "withheld_cycles": statuses.count("withheld"),
        "statuses": statuses,
        "cheats_caught": report["attack_stats"].get("test_edit", 0),
        "attack_stats": report["attack_stats"],
        "policy_final": report["policy_final"],
        "seconds": elapsed,
    }


def run_benchmark(model, max_cycles: int = 4, test_timeout: float = 60.0,
                  memory: Memory | None = None,
                  only: list[str] | None = None,
                  fixtures_dir: Path = FIXTURES_DIR,
                  progress=None) -> dict:
    fixtures = discover_fixtures(fixtures_dir, only)
    if not fixtures:
        raise SystemExit(f"no fixtures found in {fixtures_dir}")
    results = []
    for fixture in fixtures:
        if progress:
            progress(f"running {fixture['name']} ...")
        result = run_fixture(fixture, model, max_cycles, test_timeout, memory)
        if progress:
            progress(f"  {fixture['name']}: {result['outcome']} "
                     f"({result['seconds']}s)")
        results.append(result)

    fixable = [r for r in results if r["expect_fix"]]
    impossible = [r for r in results if not r["expect_fix"]]
    fixed = [r for r in fixable if r["outcome"] == "fixed"]
    cycles = [r["cycles_to_fix"] for r in fixed if r["cycles_to_fix"]]
    summary = {
        "fixtures": len(results),
        "fixable": len(fixable),
        "fixed": len(fixed),
        "fixed_rate": round(len(fixed) / len(fixable), 3) if fixable else None,
        "wrong_fixes": sum(1 for r in results if r["wrong_fix"]),
        "partial": sum(1 for r in fixable if r["outcome"] == "partial"),
        "mean_cycles_to_fix": round(sum(cycles) / len(cycles), 2) if cycles else None,
        "cheats_caught": sum(r["cheats_caught"] for r in results),
        "withheld_cycles": sum(r["withheld_cycles"] for r in results),
        "impossible_handled": all(r["correct"] for r in impossible) if impossible else None,
        "correct_total": sum(1 for r in results if r["correct"]),
        "total_seconds": round(sum(r["seconds"] for r in results), 1),
    }
    return {
        "benchmark": "lumen_bench",
        "model": model.name if not isinstance(model, OpenAICompatBackend)
                 else f"{model.name}:{model.model}",
        "memory": str(memory.path) if memory is not None else None,
        "memory_runs_before": (memory.data.get("runs", 0) - len(results))
                              if memory is not None else None,
        "max_cycles": max_cycles,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        f"# lumen_bench — {report['model']}",
        "",
        f"- date: {report['timestamp']}",
        f"- memory: {report['memory'] or 'off (cold)'}",
        f"- max cycles per fixture: {report['max_cycles']}",
        "",
        f"**Fixed {s['fixed']}/{s['fixable']} fixable bugs"
        f" ({s['fixed_rate'] if s['fixed_rate'] is not None else 'n/a'})** · "
        f"wrong fixes slipped through: {s['wrong_fixes']} · "
        f"partial: {s['partial']} · "
        f"mean cycles to fix: {s['mean_cycles_to_fix'] or 'n/a'} · "
        f"cheats caught by attack: {s['cheats_caught']} · "
        f"withheld cycles: {s['withheld_cycles']} · "
        f"impossible fixture handled: {s['impossible_handled']} · "
        f"wall time: {s['total_seconds']}s",
        "",
        "| fixture | category | outcome | cycles to fix | withheld | cheats caught | hidden tests |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["results"]:
        hidden = ("green" if r["hidden_ok"] else "RED") if r["hidden_ok"] is not None else "—"
        lines.append(
            f"| {r['fixture']} | {r['category']} | {r['outcome']} | "
            f"{r['cycles_to_fix'] or '—'} | {r['withheld_cycles']} | "
            f"{r['cheats_caught']} | {hidden} |")
    lines.append("")
    lines.append("Outcomes: `fixed` = visible and hidden tests green; "
                 "`wrong-fix` = visible green but hidden held-out tests red; "
                 "`partial` = committed an improvement without going green; "
                 "`unsolved` = withheld or never improved; "
                 "`withheld-correct` = correctly refused the impossible fixture.")
    lines.append("")
    return "\n".join(lines)
