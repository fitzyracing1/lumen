"""Turn a Lumen cycle into plain text another model can read without the JSON."""

from __future__ import annotations


STATUS = {
    "aborted": "aborted the action because the simulated result missed the bar",
    "committed": "committed the action because the simulated result cleared the bar",
    "withheld": "withheld the action because confidence was below policy",
    "blocked": "blocked because no plan survived the critic",
    "idle": "idle because no goal was open",
}


def interpret(result: dict, state: dict) -> str:
    status = result.get("status", "unknown")
    verb = STATUS.get(status, status)
    issues = result.get("issues") or []
    issue_line = (
        "The critic flagged: " + "; ".join(issues) + "."
        if issues
        else "The critic found no issues."
    )
    done = state.get("goals") or []
    closed = [g["name"] for g in done if g.get("done")]
    open_goals = [g["name"] for g in done if not g.get("done")]
    beliefs = state.get("beliefs") or {}
    belief_bits = [
        f"{b['claim']} at confidence {b['confidence']}"
        for b in beliefs.values()
    ]
    lines = [
        f"Lumen tick {result.get('tick')} on mission: {state.get('mission')}.",
        f"It chose the {result.get('chosen')} plan, critique was {result.get('critique')}, realized utility was {result.get('realized')}, and it {verb}.",
        issue_line,
        "Closed goals: " + (", ".join(closed) if closed else "none") + ".",
        "Open goals: " + (", ".join(open_goals) if open_goals else "none") + ".",
        "Beliefs: " + ("; ".join(belief_bits) if belief_bits else "none") + ".",
        "Do not treat a withheld or aborted tick as success. Only a committed tick with a closed goal counts.",
    ]
    return " ".join(lines)
