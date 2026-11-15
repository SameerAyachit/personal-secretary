"""LLM probe: list available models and print per-model rate-limit headers.

Run: ``python -m secretary.llm.probe`` (or ``python -m secretary --probe``).
The API key is read from keyring (service ``secretary``, key ``llm_api_key:nvidia``)
or env ``SECRETARY_PROBE_KEY``. Results belong in ``docs/nvidia_limits_<date>.md``.

This is HUMAN-GATED: a real key is required for the live run. Without a key it
runs in dry mode and reports that no key was found.
"""

from __future__ import annotations

import asyncio
import os
import sys

import keyring

from secretary.config import load_config

from .openai_compat import OpenAICompatClient

SERVICE = "secretary"
KEY_NAME = "llm_api_key:nvidia"
BASE_URL = "https://integrate.api.nvidia.com/v1"


def _read_key() -> str | None:
    return (
        os.environ.get("SECRETARY_PROBE_KEY")
        or keyring.get_password(SERVICE, KEY_NAME)
    )


async def _probe_once(key: str, model: str, base_url: str = BASE_URL) -> dict:
    client = OpenAICompatClient(base_url=base_url, api_key=key, model=model)
    try:
        models = await client.list_models()
        resp = await client.chat(
            messages=[{"role": "user", "content": "Say ping"}],
            max_tokens=10,
            temperature=0.0,
            purpose="probe",
        )
        return {
            "model": model,
            "listed": models,
            "chat_ok": bool(resp.text or resp.tool_calls),
            "prompt_tokens": resp.usage.get("prompt_tokens"),
            "completion_tokens": resp.usage.get("completion_tokens"),
            "total_tokens": resp.usage.get("total_tokens"),
            "latency_ms": round(resp.latency_ms, 1),
            "finish_reason": resp.finish_reason,
            "headers": {
                k: v
                for k, v in resp.headers.items()
                if k.lower()
                in (
                    "x-ratelimit-limit-requests",
                    "x-ratelimit-remaining-requests",
                    "x-ratelimit-limit-tokens",
                    "x-ratelimit-remaining-tokens",
                    "retry-after",
                )
            },
        }
    finally:
        await client.aclose()


async def _main() -> int:
    key = _read_key()
    if not key:
        print(
            "No LLM API key found. Set env SECRETARY_PROBE_KEY or store it in "
            "Credential Manager (service 'secretary', key 'llm_api_key:nvidia').",
            file=sys.stderr,
        )
        print("Dry mode: cannot list models or measure limits without a key.")
        return 1

    cfg = load_config()
    models = [cfg.llm.providers[cfg.llm.active].primary_model or "nvidia/nemotron-3.5-super-vl-120b-a12b"]
    print(f"Probing {BASE_URL} ...\n")
    for model in models:
        try:
            result = await _probe_once(key, model)
        except Exception as exc:  # probe reports any failure
            print(f"{model}: ERROR {exc}")
            continue
        print(f"Model: {result['model']}")
        print(f"  chat ok: {result['chat_ok']}")
        print(f"  tokens: {result['total_tokens']} "
              f"(prompt {result['prompt_tokens']}, completion {result['completion_tokens']})")
        print(f"  latency_ms: {result['latency_ms']}")
        print(f"  finish_reason: {result['finish_reason']}")
        if result["headers"]:
            print("  rate-limit headers:")
            for k, v in result["headers"].items():
                print(f"    {k}: {v}")
        else:
            print("  rate-limit headers: none returned")
        print()
    print("Copy this table into docs/nvidia_limits_<date>.md (the console is the source of truth).")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())
