"""R2: 0 limits in config mean "meter disabled", never a 1-token bucket."""

from __future__ import annotations

import copy

from secretary.config import _DEFAULTS, Config
from secretary.llm.factory import build_llm


def _cfg(tpm: int, rpm: int, model: str = "openai/gpt-oss-120b") -> Config:
    cfg = Config.model_validate(copy.deepcopy(_DEFAULTS))
    cfg.llm.providers["groq"].primary_model = model
    cfg.llm.limits["groq_primary"].tpm = tpm
    cfg.llm.limits["groq_primary"].rpm = rpm
    return cfg


def test_zero_limits_disable_limiter():
    llm, limiter = build_llm(_cfg(0, 0), "k" * 30)
    assert llm is not None
    assert limiter is None


def test_positive_limits_build_limiter():
    _llm, limiter = build_llm(_cfg(6000, 30), "k" * 30)
    assert limiter is not None
    assert limiter.tpm_cap > 1


def test_no_key_or_placeholder_model_gives_none():
    assert build_llm(_cfg(0, 0), None) == (None, None)
    assert build_llm(_cfg(0, 0, model="fake-1"), "k" * 30) == (None, None)
    assert build_llm(_cfg(0, 0, model=""), "k" * 30) == (None, None)


def test_daily_limits_alone_build_a_limiter():
    cfg = _cfg(0, 0)
    cfg.llm.limits["groq_primary"].rpd = 1000
    _llm, limiter = build_llm(cfg, "k" * 30)
    assert limiter is not None


def test_reasoning_effort_only_for_gpt_oss_models():
    cfg = _cfg(0, 0)
    cfg.llm.reasoning_effort = "low"
    llm, _ = build_llm(cfg, "k" * 30)
    assert llm.reasoning_effort == "low"
    other, _ = build_llm(_cfg(0, 0, model="llama-3.3-70b-versatile"), "k" * 30)
    assert other.reasoning_effort == ""
    cfg.llm.reasoning_effort = ""
    off, _ = build_llm(cfg, "k" * 30)
    assert off.reasoning_effort == ""
