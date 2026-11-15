"""R2: 0 limits in config mean "meter disabled", never a 1-token bucket."""

from __future__ import annotations

import copy

from secretary.config import _DEFAULTS, Config
from secretary.llm.factory import build_llm


def _cfg(tpm: int, rpm: int, model: str = "nvidia/nemotron-3.5-super-vl-120b-a12b") -> Config:
    cfg = Config.model_validate(copy.deepcopy(_DEFAULTS))
    cfg.llm.providers["nvidia"].primary_model = model
    cfg.llm.limits["nvidia_primary"].tpm = tpm
    cfg.llm.limits["nvidia_primary"].rpm = rpm
    cfg.llm.limits["nvidia_primary"].rpd = 0  # defaults ship a daily limit; these tests cover "all 0"
    cfg.llm.limits["nvidia_primary"].tpd = 0
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
    cfg.llm.limits["nvidia_primary"].rpd = 1000
    _llm, limiter = build_llm(cfg, "k" * 30)
    assert limiter is not None


def test_thinking_switch_is_sent_for_nemotron_models_only():
    cfg = _cfg(0, 0)
    llm, _ = build_llm(cfg, "k" * 30)
    assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    cfg.llm.thinking = True
    llm, _ = build_llm(cfg, "k" * 30)
    assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": True}}
    other, _ = build_llm(_cfg(0, 0, model="meta/llama-3.3-70b-instruct"), "k" * 30)
    assert other.extra_body is None


def test_default_config_builds_the_nvidia_limiter():
    cfg = Config.model_validate(copy.deepcopy(_DEFAULTS))
    _llm, limiter = build_llm(cfg, "k" * 30)
    assert limiter is not None
    assert limiter.rpd_cap == 10000 * 0.7
