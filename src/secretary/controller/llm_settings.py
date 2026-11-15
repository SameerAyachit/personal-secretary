"""LLM provider settings, key status, model list and connection test."""

from __future__ import annotations

import logging

from PySide6.QtCore import Slot

from secretary.config import load_config, save_config
from secretary.llm.factory import build_llm
from secretary.llm.metered import MeteredClient
from secretary.llm.openai_compat import OpenAICompatClient
from secretary.llm.probe import _probe_once
from secretary.secrets import get_secret, set_secret

logger = logging.getLogger(__name__)


def get_active_llm_key() -> str | None:
    """Return the API key for the configured LLM provider from Credential Manager.

    Uses the same service and key name that ``diagnose`` checks: service
    ``Secretary``, key ``llm_api_key:{provider}`` where ``provider`` is the
    active provider from config.
    """
    cfg = load_config()
    provider = cfg.llm.active
    return get_secret(_llm_key_name(provider))


def _llm_key_name(provider: str) -> str:
    """Credential key name for a provider: ``llm_api_key:{provider}``."""
    return f"llm_api_key:{provider}"


class LLMSettingsMixin:
    """LLM provider settings, key status, model list and connection test."""

    def set_llm_provider(
        self, provider: str, key: str, base_url: str, model: str
    ) -> None:
        """Save an LLM API key to Credential Manager and persist provider config.

        Never overwrites a stored key with a blank field: if ``key`` is empty,
        the previously saved key is left in place so the user can't accidentally
        erase it by leaving the field blank.
        """
        cfg = load_config()
        cfg.llm.active = provider
        cfg.llm.providers[provider].base_url = base_url
        cfg.llm.providers[provider].primary_model = model
        cfg.llm.providers[provider].key_name = _llm_key_name(provider)
        save_config(cfg)
        if key and key.strip():
            set_secret(_llm_key_name(provider), key.strip())
        self.rebuild_llm()

    def rebuild_llm(self) -> None:
        """Rebuild the LLM client and limiter from the current config.

        Called when the provider, key, or model changes so the active turn
        loop uses the new settings without a restart (plan A5). Limiter values
        come from config, not code constants.
        """
        self.llm, self.limiter = build_llm(load_config(), get_active_llm_key())
        # Research reads ``conn.llm``; it shares the chat rate-limit budget at background priority.
        self.conn.llm = MeteredClient(self.llm, self.limiter) if self.llm is not None else None

    def get_llm_config(self) -> dict:
        """Return LLM provider config for the AI settings tab (no secrets)."""
        cfg = load_config()
        providers: dict[str, dict] = {}
        for name, prov in cfg.llm.providers.items():
            providers[name] = {
                "base_url": prov.base_url,
                "model": prov.primary_model,
                "key_name": prov.key_name,
            }
        return {"active": cfg.llm.active, "providers": providers}

    def get_llm_key_status(self, provider: str | None = None) -> dict:
        """Return LLM key status for the AI settings tab (never the value).

        Status: "missing" (no key in Credential Manager), "placeholder"
        (key shorter than 20 chars or starts with fake/test), or "saved".
        """
        cfg = load_config()
        provider = provider or cfg.llm.active
        key_name = f"llm_api_key:{provider}"
        key = get_secret(key_name)
        if not key:
            return {"status": "missing", "provider": provider, "key_name": key_name}
        if len(key) < 20 or key.lower().startswith(("fake", "test")):
            return {"status": "placeholder", "provider": provider, "key_name": key_name}
        return {"status": "saved", "provider": provider, "key_name": key_name}

    @Slot(str)
    def get_available_models(self, provider: str | None = None) -> None:
        """List the provider's models on the worker loop; emit models_loaded.

        Never blocks the Qt thread. Returns immediately; results arrive via
        the models_loaded signal (provider, list[str]). Falls back to the
        configured primary_model on failure.
        """
        cfg = load_config()
        provider = provider or cfg.llm.active
        prov = cfg.llm.providers.get(provider)
        if prov is None:
            self.models_loaded.emit(provider, [])
            return
        key = get_secret(_llm_key_name(provider))
        if not key:
            self.models_loaded.emit(provider, [])
            return
        client = OpenAICompatClient(base_url=prov.base_url, api_key=key, model=prov.primary_model or "x")

        async def _list_and_close() -> list[str]:
            try:
                return await client.list_models()
            finally:
                await client.aclose()

        if self._submit_coro is None:
            self.models_loaded.emit(provider, [])
            return
        future = self._submit_coro(_list_and_close())
        future.add_done_callback(
            lambda f: self.models_loaded.emit(
                provider,
                f.result() if not f.exception() else [],
            )
        )

    @Slot(str, str, str)
    def test_llm_connection(self, base_url: str, api_key: str, model: str) -> None:
        """Send a tiny probe request on the worker loop; emit connection_tested.

        Uses the stored key when the field is blank, and the provider's
        base_url (not a hardcoded provider URL) so it works for Gemini too.
        """
        cfg = load_config()
        provider = cfg.llm.active
        key = api_key.strip() if api_key and api_key.strip() else get_active_llm_key()
        if not key:
            self.connection_tested.emit(
                provider,
                {"error": "No LLM key configured. Save one in Settings > AI first."},
            )
            return

        async def _probe() -> dict:
            try:
                return await _probe_once(key, model, base_url=base_url)
            except Exception as exc:  # surface exact error, never secrets
                return {"error": str(exc)}

        if self._submit_coro is None:
            self.connection_tested.emit(
                provider, {"error": "Worker loop not available"}
            )
            return
        future = self._submit_coro(_probe())
        future.add_done_callback(
            lambda f: self.connection_tested.emit(
                provider, f.result() if not f.exception() else {"error": str(f.exception())}
            )
        )
