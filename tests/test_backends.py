import pytest

from lumen_backends import (
    AmaliaBackend,
    ModelError,
    OpenAICompatBackend,
    StubBackend,
    backend_from_env,
    extract_json,
    validate_critique,
    validate_patches,
    validate_plans,
)


# -- extract_json -------------------------------------------------------------

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('[1, 2]') == [1, 2]


def test_extract_json_fenced():
    text = 'Here you go:\n```json\n{"a": 1}\n```\nhope that helps'
    assert extract_json(text) == {"a": 1}


def test_extract_json_embedded_in_prose():
    text = 'Sure! The plans are [{"name": "x", "steps": ["s"]}] as requested.'
    assert extract_json(text) == [{"name": "x", "steps": ["s"]}]


@pytest.mark.parametrize("garbage", [None, "", "   ", "no json here", "{broken", 42])
def test_extract_json_garbage(garbage):
    assert extract_json(garbage) is None


# -- validators ---------------------------------------------------------------

def test_validate_plans_good():
    plans = validate_plans([
        {"name": "p1", "steps": ["a", "b"], "predicted_utility": 0.7,
         "risk": 0.2, "assumptions": ["x"]},
    ])
    assert plans is not None and plans[0]["name"] == "p1"


def test_validate_plans_clamps_and_defaults():
    plans = validate_plans([{"name": "p", "steps": ["s"],
                             "predicted_utility": 7, "risk": "bogus"}])
    assert plans[0]["predicted_utility"] == 1.0
    assert plans[0]["risk"] == 0.3  # default on unparseable


@pytest.mark.parametrize("bad", [
    None, {}, [], [{"steps": ["s"]}], [{"name": "p"}],
    [{"name": "p", "steps": "not a list"}], [{"name": "", "steps": ["s"]}],
    ["just a string"],
])
def test_validate_plans_bad(bad):
    assert validate_plans(bad) is None


def test_validate_critique():
    crit = validate_critique({"fatal": 1, "issues": ["bad"], "penalty": 0.4})
    assert crit == {"fatal": True, "issues": ["bad"], "penalty": 0.4, "note": ""}
    assert validate_critique("nope") is None
    assert validate_critique({"issues": "not a list"}) is None


def test_validate_patches_good_and_bad():
    good = validate_patches([
        {"name": "fix", "rationale": "r", "confidence": 0.8,
         "edits": [{"path": "calc.py", "new_content": "x = 1\n"}]},
    ])
    assert good is not None and good[0]["edits"][0]["path"] == "calc.py"
    assert validate_patches([{"name": "fix", "edits": []}]) is None
    assert validate_patches([{"name": "fix", "edits": [{"path": "p"}]}]) is None
    assert validate_patches("garbage") is None


# -- stub ----------------------------------------------------------------------

def test_stub_plans_match_original_catalog():
    stub = StubBackend()
    plans = stub.propose_plans({"focus": {"name": "g", "utility": 0.9,
                                          "success_test": "t"}})
    assert [p["name"] for p in plans] == ["direct", "decompose", "instrument-first"]
    assert plans[1]["predicted_utility"] == pytest.approx(0.9 * 0.84)


def test_stub_patches_include_the_fix():
    stub = StubBackend()
    patches = stub.propose_patches(
        {"files": {"calc.py": "def add(a, b):\n    return a - b\n"}})
    assert patches is not None
    contents = [p["edits"][0]["new_content"] for p in patches]
    assert any("return a + b" in c for c in contents)


def test_stub_is_deterministic():
    stub = StubBackend()
    ctx = {"files": {"calc.py": "x = 1 - 2 - 3\n"}}
    assert stub.propose_patches(ctx) == stub.propose_patches(ctx)


def test_stub_no_files_no_patches():
    assert StubBackend().propose_patches({"files": {}}) is None


# -- factory --------------------------------------------------------------------

def test_factory_default_is_stub():
    assert isinstance(backend_from_env({}), StubBackend)
    assert isinstance(backend_from_env({"LUMEN_MODEL": "stub"}), StubBackend)


def test_factory_amalia():
    backend = backend_from_env({
        "LUMEN_MODEL": "amalia",
        "AMALIA_BASE_URL": "http://192.168.1.50:8000/v1/",
        "AMALIA_API_KEY": "k",
        "AMALIA_MODEL": "amalia-7b",
    })
    assert isinstance(backend, AmaliaBackend)
    assert backend.base_url == "http://192.168.1.50:8000/v1"
    assert backend.model == "amalia-7b"


def test_factory_openai_requires_base_url():
    with pytest.raises(ModelError):
        backend_from_env({"LUMEN_MODEL": "openai"})
    backend = backend_from_env({"LUMEN_MODEL": "openai",
                                "OPENAI_BASE_URL": "http://localhost:11434/v1",
                                "OPENAI_MODEL": "qwen2.5-coder:1.5b"})
    assert isinstance(backend, OpenAICompatBackend)
    assert backend.model == "qwen2.5-coder:1.5b"


def test_factory_unknown_model():
    with pytest.raises(ModelError):
        backend_from_env({"LUMEN_MODEL": "skynet"})


# -- chat backend parsing (no network) -------------------------------------------

def test_json_call_handles_garbage(monkeypatch):
    backend = OpenAICompatBackend("http://example.invalid/v1", model="m")
    monkeypatch.setattr(backend, "chat", lambda *a, **k: "utter nonsense")
    assert backend.propose_plans({}) is None
    monkeypatch.setattr(backend, "chat", lambda *a, **k: None)
    assert backend.propose_patches({}) is None


def test_json_call_handles_valid(monkeypatch):
    backend = OpenAICompatBackend("http://example.invalid/v1", model="m")
    reply = '```json\n[{"name": "p", "steps": ["s"], "risk": 0.1}]\n```'
    monkeypatch.setattr(backend, "chat", lambda *a, **k: reply)
    plans = backend.propose_plans({})
    assert plans is not None and plans[0]["name"] == "p"
