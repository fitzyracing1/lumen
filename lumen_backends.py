#!/usr/bin/env python3
"""
Model backends for Lumen.

The kernel never talks to a model directly. It calls four high-level methods:

    propose_plans(context)    -> list[plan dict]  | None
    critique_plan(plan, ctx)  -> critique dict    | None
    propose_patches(context)  -> list[patch dict] | None
    critique_patch(patch, ctx)-> critique dict    | None

`None` always means "the model produced garbage or is unreachable". The kernel
treats that as a reason to withhold, never as a reason to guess.

Backends:

  * StubBackend          — offline, deterministic. Default. Used by tests/CI.
  * OpenAICompatBackend  — any OpenAI-compatible /chat/completions endpoint.
  * AmaliaBackend        — Amália (Portugal's national LLM) served locally on
                           another machine. A thin subclass of the OpenAI-compat
                           adapter so the endpoint shape is easy to change if
                           Amália's server diverges. See the owner's SDK repo
                           github.com/fitzyracing1/amalia2.0 (not a dependency).

Selection is by environment:

    LUMEN_MODEL=stub   (default)   no network
    LUMEN_MODEL=amalia             AMALIA_BASE_URL, AMALIA_API_KEY?, AMALIA_MODEL?
    LUMEN_MODEL=openai             LUMEN_BASE_URL/OPENAI_BASE_URL, *_API_KEY, *_MODEL
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request


class ModelError(Exception):
    """Raised for configuration errors (never for bad model output)."""


# ---------------------------------------------------------------------------
# Robust parsing of model output
# ---------------------------------------------------------------------------

def extract_json(text):
    """Pull the first JSON value out of model output. Returns None on garbage."""
    if not isinstance(text, str) or not text.strip():
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # Model wrapped the JSON in prose: find the outermost bracketed region.
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start = text.find(open_c)
        if start == -1:
            continue
        end = text.rfind(close_c)
        while end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                end = text.rfind(close_c, start, end)
    return None


def _clamp(value, lo=0.0, hi=1.0, default=0.5):
    try:
        return min(hi, max(lo, float(value)))
    except (TypeError, ValueError):
        return default


def validate_plans(obj):
    """Validate a model's plan list. Returns up to 3 clean plans, or None."""
    if not isinstance(obj, list):
        return None
    plans = []
    for item in obj[:3]:
        if not isinstance(item, dict):
            return None
        name, steps = item.get("name"), item.get("steps")
        if not isinstance(name, str) or not name.strip():
            return None
        if (not isinstance(steps, list) or not steps
                or not all(isinstance(s, str) for s in steps)):
            return None
        plans.append({
            "name": name.strip()[:80],
            "steps": [s[:400] for s in steps[:8]],
            "predicted_utility": _clamp(item.get("predicted_utility"), default=0.5),
            "risk": _clamp(item.get("risk"), default=0.3),
            "assumptions": [a[:200] for a in item.get("assumptions", [])
                            if isinstance(a, str)][:6],
        })
    return plans or None


def validate_critique(obj):
    """Validate a model critique. Returns a clean critique dict, or None."""
    if not isinstance(obj, dict):
        return None
    issues = obj.get("issues", [])
    if not isinstance(issues, list):
        return None
    return {
        "fatal": bool(obj.get("fatal", False)),
        "issues": [str(i)[:300] for i in issues[:8]],
        "penalty": _clamp(obj.get("penalty"), 0.0, 1.0, default=0.0),
        "note": str(obj.get("note", ""))[:200],
    }


def validate_patches(obj):
    """Validate a model's patch list. Returns up to 3 clean patches, or None.

    A patch is {"name", "rationale", "confidence", "edits": [{"path",
    "new_content"}]} where new_content is the full new file content.
    """
    if not isinstance(obj, list):
        return None
    patches = []
    for item in obj[:3]:
        if not isinstance(item, dict):
            continue
        edits = item.get("edits")
        if not isinstance(edits, list) or not edits:
            continue
        clean_edits = []
        for edit in edits[:8]:
            if not isinstance(edit, dict):
                clean_edits = None
                break
            path, content = edit.get("path"), edit.get("new_content")
            if (not isinstance(path, str) or not path.strip()
                    or not isinstance(content, str)):
                clean_edits = None
                break
            clean_edits.append({"path": path.strip(), "new_content": content})
        if not clean_edits:
            continue
        patches.append({
            "name": str(item.get("name", f"patch-{len(patches) + 1}"))[:80],
            "rationale": str(item.get("rationale", ""))[:500],
            "confidence": _clamp(item.get("confidence"), default=0.5),
            "edits": clean_edits,
        })
    return patches or None


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class ModelBackend:
    name = "base"

    def propose_plans(self, context):
        raise NotImplementedError

    def critique_plan(self, plan, context):
        raise NotImplementedError

    def propose_patches(self, context):
        raise NotImplementedError

    def critique_patch(self, patch, context):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Offline deterministic stub
# ---------------------------------------------------------------------------

# Operator swaps the stub uses to generate candidate patches. Dumb on purpose:
# the point is that the kernel's attack/simulate layers filter the bad ones.
_STUB_MUTATIONS = [("-", "+"), ("+", "-"), ("*", "+"), ("<", "<="), (">", ">=")]


def _replace_nth(text, old, new, n):
    """Replace the n-th (0-based) occurrence of `old`. No-op if absent."""
    start = 0
    for _ in range(n):
        i = text.find(old, start)
        if i == -1:
            return text
        start = i + len(old)
    i = text.find(old, start)
    if i == -1:
        return text
    return text[:i] + new + text[i + len(old):]


class StubBackend(ModelBackend):
    """Deterministic offline backend. No network, no randomness.

    For abstract planning it reproduces Lumen's original three-strategy
    catalog. For coding it proposes small operator mutations of the source
    files; simulation against the real test suite decides which (if any)
    survive.
    """

    name = "stub"

    def propose_plans(self, context):
        focus = context.get("focus") or {}
        name = focus.get("name", "the goal")
        utility = _clamp(focus.get("utility"), default=0.5)
        success_test = focus.get("success_test", "the success test")
        return [
            {
                "name": "direct",
                "steps": [f"allocate all effort to {name}", "measure success test",
                          "stop on pass"],
                "predicted_utility": utility * 0.72,
                "risk": 0.28,
                "assumptions": ["success test is observable", "no hidden constraint"],
            },
            {
                "name": "decompose",
                "steps": [
                    f"split {name} into probe / build / verify",
                    "run cheapest probe that can falsify the plan",
                    "build only the surviving branch",
                    "verify against success test before claiming done",
                ],
                "predicted_utility": utility * 0.84,
                "risk": 0.18,
                "assumptions": ["a cheap falsifier exists",
                                "branching cost < rework cost"],
            },
            {
                "name": "instrument-first",
                "steps": [
                    "build the measurement before the intervention",
                    f"define numeric pass line for {success_test}",
                    "intervene at the smallest dose that can move the metric",
                    "abort if metric does not move",
                ],
                "predicted_utility": utility * 0.8,
                "risk": 0.14,
                "assumptions": ["metric is causal enough to steer by",
                                "dose-response is monotone near zero"],
            },
        ]

    def critique_plan(self, plan, context):
        return {"fatal": False, "issues": [], "penalty": 0.0, "note": "stub"}

    def propose_patches(self, context):
        files = context.get("files") or {}
        candidates = []
        for path in sorted(files):
            content = files[path]
            if not isinstance(content, str):
                continue
            for old, new in _STUB_MUTATIONS:
                count = content.count(old)
                for occ in range(min(count, 3)):
                    mutated = _replace_nth(content, old, new, occ)
                    if mutated == content:
                        continue
                    candidates.append({
                        "name": f"{path}:{old}->{new}@{occ}",
                        "rationale": f"swap occurrence {occ} of {old!r} for {new!r} in {path}",
                        "confidence": 0.6,
                        "edits": [{"path": path, "new_content": mutated}],
                    })
                    if len(candidates) >= 3:
                        return candidates
                if count > 1:
                    mutated = content.replace(old, new)
                    candidates.append({
                        "name": f"{path}:{old}->{new}@all",
                        "rationale": f"swap every {old!r} for {new!r} in {path}",
                        "confidence": 0.6,
                        "edits": [{"path": path, "new_content": mutated}],
                    })
                    if len(candidates) >= 3:
                        return candidates
        return candidates or None

    def critique_patch(self, patch, context):
        return {"fatal": False, "issues": [], "penalty": 0.0, "note": "stub"}


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP backend
# ---------------------------------------------------------------------------

_PLANS_SYSTEM = (
    "You are the planning module of Lumen, a bounded decision kernel. "
    "Given the mission, the focused goal, beliefs, and world state, respond with "
    "a JSON array of exactly 3 structurally different plans. Each plan is an "
    'object: {"name": str, "steps": [str, ...], "predicted_utility": 0..1, '
    '"risk": 0..1, "assumptions": [str, ...]}. Respond with JSON only, no prose.'
)

_PLAN_CRITIC_SYSTEM = (
    "You are the adversarial critic of Lumen. Try to kill the plan: find hidden "
    "assumptions, missing falsifiers, and risks. Respond with JSON only: "
    '{"fatal": bool, "issues": [str, ...], "penalty": 0..1, "note": str}. '
    "penalty is how much of the predicted utility the issues destroy."
)

_PATCHES_SYSTEM = (
    "You are the patch proposer of Lumen, pointed at a small repository with "
    "failing tests. Given the failing test output and the current file contents, "
    "respond with a JSON array of up to 3 alternative candidate patches. Each is "
    'an object: {"name": str, "rationale": str, "confidence": 0..1, "edits": '
    '[{"path": relative file path, "new_content": FULL new file content}]}. '
    "Rules: never edit test files or conftest.py; paths must stay inside the "
    "target; keep edits minimal. Respond with JSON only, no prose."
)

_PATCH_CRITIC_SYSTEM = (
    "You are the adversarial critic of Lumen reviewing a candidate patch. Try to "
    "kill it: look for wrong logic, broken behavior for untested inputs, and "
    "edits that game the tests instead of fixing the code. Respond with JSON "
    'only: {"fatal": bool, "issues": [str, ...], "penalty": 0..1, "note": str}.'
)


class OpenAICompatBackend(ModelBackend):
    """Any endpoint that speaks POST {base_url}/chat/completions."""

    name = "openai-compat"

    def __init__(self, base_url, api_key=None, model="", timeout=120.0):
        if not base_url:
            raise ModelError(f"{self.name}: base_url is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.last_error = None

    def chat(self, system, user, temperature=0.2, max_tokens=4000):
        """One chat completion. Returns the text, or None on any failure."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, OSError, ValueError, KeyError,
                IndexError, TypeError) as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            print(f"[lumen] {self.name} request failed: {self.last_error}",
                  file=sys.stderr)
            return None

    def _json_call(self, system, context, validator):
        raw = self.chat(system, json.dumps(context, indent=2))
        if raw is None:
            return None
        return validator(extract_json(raw))

    def propose_plans(self, context):
        return self._json_call(_PLANS_SYSTEM, context, validate_plans)

    def critique_plan(self, plan, context):
        return self._json_call(_PLAN_CRITIC_SYSTEM,
                               {"plan": plan, "context": context},
                               validate_critique)

    def propose_patches(self, context):
        return self._json_call(_PATCHES_SYSTEM, context, validate_patches)

    def critique_patch(self, patch, context):
        return self._json_call(_PATCH_CRITIC_SYSTEM,
                               {"patch": patch, "context": context},
                               validate_critique)


class AmaliaBackend(OpenAICompatBackend):
    """Amália (Portugal's national LLM) served on the owner's other machine.

    Assumes an OpenAI-compatible chat completions endpoint. If the Amália
    server (see github.com/fitzyracing1/amalia2.0) ends up exposing a
    different shape, only this class needs to change — override `chat`.
    """

    name = "amalia"

    DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"
    DEFAULT_MODEL = "amalia"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def backend_from_env(env=None):
    """Build the backend selected by LUMEN_MODEL. Defaults to the stub."""
    env = os.environ if env is None else env
    choice = env.get("LUMEN_MODEL", "stub").strip().lower()
    if choice in ("", "stub", "offline", "none"):
        return StubBackend()
    if choice == "amalia":
        return AmaliaBackend(
            base_url=env.get("AMALIA_BASE_URL", AmaliaBackend.DEFAULT_BASE_URL),
            api_key=env.get("AMALIA_API_KEY"),
            model=env.get("AMALIA_MODEL", AmaliaBackend.DEFAULT_MODEL),
        )
    if choice in ("openai", "openai-compat", "openai_compat"):
        base_url = env.get("LUMEN_BASE_URL") or env.get("OPENAI_BASE_URL")
        if not base_url:
            raise ModelError(
                "LUMEN_MODEL=openai requires LUMEN_BASE_URL or OPENAI_BASE_URL")
        return OpenAICompatBackend(
            base_url=base_url,
            api_key=env.get("LUMEN_API_KEY") or env.get("OPENAI_API_KEY"),
            model=env.get("LUMEN_MODEL_NAME") or env.get("OPENAI_MODEL", ""),
        )
    raise ModelError(
        f"unknown LUMEN_MODEL={choice!r} (expected stub, amalia, or openai)")
