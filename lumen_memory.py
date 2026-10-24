#!/usr/bin/env python3
"""
Memory across runs for Lumen.

A small local JSON store that persists between runs:

  * beliefs  — final confidence of named beliefs (clamped on load so a bad
               streak can lower priors but never freeze the kernel forever)
  * policy   — the evolved policy (the revision budget still applies per run)
  * lessons  — what happened to past patches: which kinds were killed by the
               critic and why, which failed in simulation, which worked

Lessons are deduplicated and counted; the most frequent ones are fed into the
propose/attack prompts of model backends. The stub backend ignores them, so
tests and CI stay deterministic. `reset()` forgets everything.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

MEMORY_VERSION = 1
MAX_LESSONS_STORED = 100
MAX_LESSONS_FED = 8
MAX_LESSON_CHARS = 240

# Loaded belief priors are clamped into this band: memory may make the kernel
# more or less cautious, but never unable to act (or blindly confident).
BELIEF_FLOOR = 0.35
BELIEF_CEIL = 0.9


class Memory:
    """Persistent store. Missing or corrupt files mean an empty memory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = self._load()

    def _empty(self) -> dict:
        return {"version": MEMORY_VERSION, "beliefs": {}, "policy": None,
                "lessons": [], "runs": 0}

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty()
        if not isinstance(data, dict) or data.get("version") != MEMORY_VERSION:
            return self._empty()
        for key, kind in (("beliefs", dict), ("lessons", list)):
            if not isinstance(data.get(key), kind):
                data[key] = kind()
        data.setdefault("policy", None)
        data.setdefault("runs", 0)
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def reset(self) -> None:
        """Forget everything, on disk too."""
        self.data = self._empty()
        try:
            self.path.unlink()
        except OSError:
            pass

    # -- beliefs and policy ---------------------------------------------------

    def stored_confidence(self, key: str) -> float | None:
        value = self.data["beliefs"].get(key)
        if not isinstance(value, (int, float)):
            return None
        return min(BELIEF_CEIL, max(BELIEF_FLOOR, float(value)))

    def stored_policy(self) -> dict | None:
        policy = self.data["policy"]
        return dict(policy) if isinstance(policy, dict) else None

    def remember_run(self, beliefs: dict, policy: dict) -> None:
        """Persist final belief confidences and the evolved policy."""
        for key, belief in beliefs.items():
            self.data["beliefs"][key] = round(belief.confidence, 4)
        self.data["policy"] = dict(policy)
        self.data["runs"] = int(self.data.get("runs", 0)) + 1

    # -- lessons ----------------------------------------------------------------

    def record_lesson(self, kind: str, detail: str) -> None:
        detail = " ".join(str(detail).split())[:MAX_LESSON_CHARS]
        if not detail:
            return
        for lesson in self.data["lessons"]:
            if lesson.get("kind") == kind and lesson.get("detail") == detail:
                lesson["count"] = int(lesson.get("count", 1)) + 1
                return
        self.data["lessons"].append({"kind": kind, "detail": detail, "count": 1})
        if len(self.data["lessons"]) > MAX_LESSONS_STORED:
            # Drop the least established lesson, oldest first on ties.
            weakest = min(range(len(self.data["lessons"])),
                          key=lambda i: (self.data["lessons"][i].get("count", 1), -i))
            self.data["lessons"].pop(weakest)

    def relevant_lessons(self, limit: int = MAX_LESSONS_FED) -> list[str]:
        """Most established lessons first, formatted for a prompt."""
        ranked = sorted(self.data["lessons"],
                        key=lambda l: int(l.get("count", 1)), reverse=True)
        return [f"[{l['kind']} x{l.get('count', 1)}] {l['detail']}"
                for l in ranked[:limit]]
