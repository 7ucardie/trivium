import pytest

from trivium import config, launch, policy, state

CFG = config.load(config.config_path())


def answers(kind, difficulty, tools, p=0.9):
    return {"kind": {"choice": kind, "p": p}, "difficulty": {"choice": difficulty, "p": p},
            "tools": {"choice": tools, "p": p}}


@pytest.mark.parametrize("labels, target", [
    (("quick_answer", "trivial", "none"), "local"),
    (("writing", "trivial", "none"), "local"),
    (("debugging", "trivial", "none"), "claude-haiku"),
    (("code_change", "moderate", "workspace"), "codex-sol"),
    (("code_change", "trivial", "workspace"), "codex-sol"),
    (("code_change", "hard", "workspace"), "codex-astra"),
    (("design", "hard", "none"), "claude-fable"),
    (("debugging", "hard", "workspace"), "claude-opus"),
    (("review", "trivial", "workspace"), "claude-haiku"),
    (("review", "moderate", "workspace"), "claude-sonnet"),
])
def test_bundled_rules(labels, target):
    assert policy.decide(CFG, answers(*labels)).target == target


def test_low_confidence_falls_back():
    a = answers("code_change", "hard", "workspace")
    a["difficulty"]["p"] = 0.3
    floors = {**CFG, "min_confidence": {"difficulty": 0.45}}  # the shipped config has no floors
    assert policy.decide(CFG, a).target == "codex-astra"
    d = policy.decide(floors, a)
    assert d.target == CFG["fallback"] and d.unsure == ["difficulty"]


def test_summarize_picks_argmax():
    s = policy.summarize({"tools": {"none": 0.2, "workspace": 0.8}})
    assert s["tools"]["choice"] == "workspace" and s["tools"]["p"] == 0.8


@pytest.mark.parametrize("target, vendor, expect", [
    ("codex-sol", "claude", "claude-sonnet"),
    ("claude-opus", "codex", "codex-astra"),
    ("claude-fable", "codex", "codex-astra-max"),
    ("local", "claude", "claude-haiku"),
    ("claude-haiku", "claude", "claude-haiku"),
])
def test_via_keeps_tier(target, vendor, expect):
    assert policy.via(CFG, target, vendor) == expect


@pytest.mark.parametrize("name, expect", [
    ("opus", "claude-opus"), ("sol", "codex-sol"), ("gpt-6-luna", "codex-luna"), ("local", "local"),
])
def test_resolve_to(name, expect):
    assert policy.resolve_to(CFG, name) == expect


def test_resolve_to_unknown():
    with pytest.raises(ValueError):
        policy.resolve_to(CFG, "gpt-2")


def test_launch_argv():
    t = CFG["targets"]
    assert launch.argv(t["claude-opus"], "hi", one_shot=True) == ["claude", "--model", "claude-opus-5-5", "-p", "hi"]
    assert launch.argv(t["codex-sol"], "hi", one_shot=False) == [
        "codex", "-m", "gpt-6-sol", "-c", 'model_reasoning_effort="high"', "hi"]
    assert launch.argv(t["codex-luna"], "hi", one_shot=True)[:2] == ["codex", "exec"]


def test_state_clip_keeps_head_and_tail():
    text = "HEAD " + "x" * 5000 + " TAIL"
    clipped = state.clip(text, 1000)
    assert clipped.startswith("HEAD") and clipped.endswith("TAIL") and len(clipped) < 1100


def test_state_context_in_words():
    assert "inside the code repository 'trivium'" in state.build("hi", "trivium", 100)["context"]
    assert "outside any code repository" in state.build("hi", None, 100)["context"]


def test_config_rejects_unknown_option():
    bad = {**CFG, "rules": [{"when": {"kind": "poetry"}, "to": "local"}]}
    with pytest.raises(ValueError, match="no option"):
        config.validate(bad)


def test_option_weights_shift_the_choice():
    raw = {"difficulty": {"trivial": 0.5, "moderate": 0.3, "hard": 0.2}}
    assert policy.summarize(raw)["difficulty"]["choice"] == "trivial"
    weighted = policy.summarize(raw, weights={"difficulty": {"moderate": 3, "hard": 2}})
    assert weighted["difficulty"]["choice"] == "moderate"
    assert sum(weighted["difficulty"]["probabilities"].values()) == pytest.approx(1.0)


def test_config_rejects_bad_weights():
    with pytest.raises(ValueError, match="option_weights"):
        config.validate({**CFG, "option_weights": {"difficulty": {"epic": 2}}})
