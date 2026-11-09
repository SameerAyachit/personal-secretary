"""Configuration loading: ``config.toml`` merged with Appendix A defaults.

Limits are config, never code constants. Unknown limits are ``0`` meaning
"meter disabled, rely on headers and 429 handling" (plan §6.2).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from .paths import config_path, ensure_dirs

_DEFAULTS: dict[str, Any] = {
    "app": {
        "timezone": "Asia/Kolkata",
        "language": "en",
        "theme": "system",
        "start_minimized": True,
        "hotkey": "Ctrl+Alt+Space",
        "quiet_hours_enabled": False,
        "quiet_hours_start": "23:00",
        "quiet_hours_end": "07:00",
    },
    "llm": {
        "active": "groq",
        "history_messages": 8,
        "max_steps": 5,
        "turn_timeout_seconds": 90,
        "temperature_tools": 0.1,
        "providers": {
            "groq": {
                "base_url": "https://api.groq.com/openai/v1",
                "primary_model": "",
                "fallback_model": "openai/gpt-oss-20b",
                "key_name": "llm_api_key:groq",
            },
            "gemini": {
                "base_url": "",
                "primary_model": "",
                "fallback_model": "",
                "key_name": "llm_api_key:gemini",
            },
        },
        "limits": {
            "groq_primary": {"rpm": 0, "rpd": 0, "tpm": 0, "tpd": 0, "safety_factor": 0.7},
            "groq_fallback": {"rpm": 0, "rpd": 0, "tpm": 0, "tpd": 0, "safety_factor": 0.7},
        },
    },
    "tokens": {
        "tool_schema_margin": 800,
        "per_message_margin": 8,
        "tool_result_budget": 800,
    },
    "notifications": {
        "toast": True,
        "popup_card": True,
        "repeat_after_minutes": 10,
        "repeat_once": True,
    },
    "pending_actions": {
        "default_ttl_hours": 24,
        "email_send_ttl_hours": 2,
        "expired_retention_days": 7,
    },
    "backup": {"dir": "", "keep": 7, "min_hours_between": 20},
    "search": {
        "provider": "ddgs",
        "cache_hours": 24,
        "breaker_failures": 3,
        "breaker_open_minutes": 10,
    },
    "research": {
        "max_sources": 4,
        "tokens_per_source": 1500,
        "max_llm_calls": 8,
        "token_budget": 20000,
    },
    "google": {"enabled": False, "sync_minutes": 15, "window_past_days": 7, "window_future_days": 60},
}


class _Limit(BaseModel):
    rpm: int = 0
    rpd: int = 0
    tpm: int = 0
    tpd: int = 0
    safety_factor: float = 0.7
    model_config = ConfigDict(extra="ignore")


class _Provider(BaseModel):
    base_url: str = ""
    primary_model: str = ""
    fallback_model: str = ""
    key_name: str = ""
    model_config = ConfigDict(extra="ignore")


class LLM(BaseModel):
    active: str = "groq"
    history_messages: int = 8
    max_steps: int = 5
    turn_timeout_seconds: int = 90
    temperature_tools: float = 0.1
    providers: dict[str, _Provider] = {}
    limits: dict[str, _Limit] = {}
    model_config = ConfigDict(extra="ignore")


class App(BaseModel):
    timezone: str = "Asia/Kolkata"
    language: str = "en"
    theme: str = "system"
    start_minimized: bool = True
    hotkey: str = "Ctrl+Alt+Space"
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
    model_config = ConfigDict(extra="ignore")


class Tokens(BaseModel):
    tool_schema_margin: int = 800
    per_message_margin: int = 8
    tool_result_budget: int = 800
    model_config = ConfigDict(extra="ignore")


class Notifications(BaseModel):
    toast: bool = True
    popup_card: bool = True
    repeat_after_minutes: int = 10
    repeat_once: bool = True
    model_config = ConfigDict(extra="ignore")


class PendingActions(BaseModel):
    default_ttl_hours: int = 24
    email_send_ttl_hours: int = 2
    expired_retention_days: int = 7
    model_config = ConfigDict(extra="ignore")


class Backup(BaseModel):
    dir: str = ""
    keep: int = 7
    min_hours_between: int = 20
    model_config = ConfigDict(extra="ignore")


class Search(BaseModel):
    provider: str = "ddgs"
    cache_hours: int = 24
    breaker_failures: int = 3
    breaker_open_minutes: int = 10
    model_config = ConfigDict(extra="ignore")


class Research(BaseModel):
    max_sources: int = 4
    tokens_per_source: int = 1500
    max_llm_calls: int = 8
    token_budget: int = 20000
    model_config = ConfigDict(extra="ignore")


class Google(BaseModel):
    enabled: bool = False
    sync_minutes: int = 15
    window_past_days: int = 7
    window_future_days: int = 60
    model_config = ConfigDict(extra="ignore")


class Config(BaseModel):
    app: App = App()
    llm: LLM = LLM()
    tokens: Tokens = Tokens()
    notifications: Notifications = Notifications()
    pending_actions: PendingActions = PendingActions()
    backup: Backup = Backup()
    search: Search = Search()
    research: Research = Research()
    google: Google = Google()
    model_config = ConfigDict(extra="ignore")


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: Path | None = None) -> Config:
    """Load config from ``config.toml`` (data root) merged with defaults.

    Creates the data root and writes a default ``config.toml`` on first run.
    """
    cfg_path = path or config_path()
    merged = _deep_merge(_DEFAULTS, {})
    if cfg_path.exists():
        with cfg_path.open("rb") as fh:
            user = tomllib.load(fh)
        if isinstance(user, dict):
            merged = _deep_merge(merged, user)
    return Config.model_validate(merged)


def save_config(config: Config, path: Path | None = None) -> None:
    """Persist config to ``config.toml`` (used by the wizard / Test connection)."""
    cfg_path = path or config_path()
    ensure_dirs()
    data = config.model_dump(mode="python")
    lines: list[str] = []
    for section_name in (
        "app", "llm", "tokens", "notifications", "pending_actions", "backup",
        "search", "research", "google",
    ):
        section = data[section_name]
        lines.append(f"[{section_name}]")
        for key, value in section.items():
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    with cfg_path.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        items = [f"{k} = {_toml_value(v)}" for k, v in value.items()]
        return "{" + ", ".join(items) + "}"
    return f'"{value}"'
