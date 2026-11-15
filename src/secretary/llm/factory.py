"""Single place that builds the LLM client and limiter from config (plan §6.2).

Limits are config, never code constants. A limit of ``0`` means "meter
disabled, rely on provider headers and 429 handling". A local limiter is
built only when at least one of rpm/tpm/rpd/tpd is set.
"""

from __future__ import annotations

from secretary.config import Config
from secretary.llm.limiter import Limiter
from secretary.llm.openai_compat import OpenAICompatClient


def build_llm(cfg: Config, key: str | None) -> tuple[OpenAICompatClient | None, Limiter | None]:
    """Return ``(client, limiter)``; ``(None, None)`` if no usable key/model."""
    prov = cfg.llm.providers.get(cfg.llm.active)
    if prov is None or not key:
        return None, None
    model = prov.primary_model or ""
    if not model or model.lower().startswith(("fake", "test")):
        return None, None
    # Nemotron models think by default; ``enable_thinking`` is their on/off switch
    # (NVIDIA model card). Other models could reject the unknown field.
    extra = None
    if "nemotron" in model.lower():
        extra = {"chat_template_kwargs": {"enable_thinking": cfg.llm.thinking}}
    client = OpenAICompatClient(
        base_url=prov.base_url, api_key=key, model=model, extra_body=extra
    )
    lim = cfg.llm.limits.get(cfg.llm.active + "_primary")
    if lim is None or not (lim.rpm > 0 or lim.tpm > 0 or lim.rpd > 0 or lim.tpd > 0):
        return client, None
    return client, Limiter(
        rpm=lim.rpm, tpm=lim.tpm, safety=lim.safety_factor, rpd=lim.rpd, tpd=lim.tpd
    )
