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
    # ``reasoning_effort`` is a gpt-oss parameter; other models would reject it.
    effort = cfg.llm.reasoning_effort if "gpt-oss" in model.lower() else ""
    client = OpenAICompatClient(
        base_url=prov.base_url, api_key=key, model=model, reasoning_effort=effort
    )
    lim = cfg.llm.limits.get(cfg.llm.active + "_primary")
    if lim is None or not (lim.rpm > 0 or lim.tpm > 0 or lim.rpd > 0 or lim.tpd > 0):
        return client, None
    return client, Limiter(
        rpm=lim.rpm, tpm=lim.tpm, safety=lim.safety_factor, rpd=lim.rpd, tpd=lim.tpd
    )
