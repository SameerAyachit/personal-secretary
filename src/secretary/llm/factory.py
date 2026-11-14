"""Single place that builds the LLM client and limiter from config (plan §6.2).

Limits are config, never code constants. A limit of ``0`` means "meter
disabled, rely on provider headers and 429 handling", so no local limiter is
built when either rpm or tpm is 0.
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
    client = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=model)
    lim = cfg.llm.limits.get(cfg.llm.active + "_primary")
    if lim is None or lim.rpm <= 0 or lim.tpm <= 0:
        return client, None
    return client, Limiter(rpm=lim.rpm, tpm=lim.tpm, safety=lim.safety_factor)
