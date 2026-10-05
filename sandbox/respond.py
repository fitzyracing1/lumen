"""Write a usable response file. A tick log is not a result."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parent / "responses"


def write_response(result: dict, state: dict, text: str) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    tick = result.get("tick", 0)
    status = result.get("status", "idle")
    closed = [g["name"] for g in state.get("goals", []) if g.get("done")]
    open_goals = [g["name"] for g in state.get("goals", []) if not g.get("done")]
    beliefs = state.get("beliefs") or {}
    usable = status == "committed" and bool(closed)
    title = "Usable response" if usable else "No usable response yet"
    body = [
        f"# {title}",
        "",
        f"Mission: {state.get('mission')}",
        "",
        text,
        "",
        "## What you can use",
        "",
    ]
    if usable:
        body.append(f"Closed this run: {', '.join(closed)}.")
        body.append(f"Plan used: {result.get('chosen')}. Realized utility: {result.get('realized')}.")
        body.append("This file is the result. The tick numbers are only how it got here.")
    else:
        body.append("Nothing is usable yet. The kernel refused to treat an abort or a withhold as an answer.")
        body.append(f"Still open: {', '.join(open_goals) if open_goals else 'none'}.")
    body.extend(["", "## Beliefs", ""])
    for b in beliefs.values():
        body.append(f"- {b['claim']} ({b['confidence']})")
    body.append("")
    path = OUT / f"tick-{tick}.md"
    path.write_text("\n".join(body))
    latest = OUT / "latest.md"
    latest.write_text(path.read_text())
    return str(path)
