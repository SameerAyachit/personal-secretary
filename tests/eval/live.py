"""Live eval against the configured real model (human-run; see docs/eval_runbook.md).

    python -m tests.eval.live [--max N] [--delay SECONDS] [--only create-1,query-2]

Sends only the eval cases' own sentences (no personal data), the app's system prompt
and the real tool schemas to the provider in Settings > AI, using the key already in
Credential Manager (never printed). One model call per case; the first tool call is
scored with the same checks as the FakeLLM contract run. The report goes to
``docs/eval_results/<date>_<model>.md`` and maps onto plan 7.9's decision table.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from tests.eval.cases import CASES
from tests.eval.harness import normalise_tool_call, run_case, write_report

from secretary.agent.loop import _build_context, _hide_tz
from secretary.agent.normalize_response import normalize_response
from secretary.agent.wiring import build_registry_and_router
from secretary.config import default_timezone, load_config
from secretary.controller import get_active_llm_key
from secretary.llm.factory import build_llm

logger = logging.getLogger(__name__)
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "eval_results"


def make_chat_fn(llm, registry, router, cfg):
    """A harness ``chat_fn`` that asks ``llm`` exactly as the app's agent loop would."""
    tz = default_timezone()

    async def chat_fn(messages, tools):
        user_text = messages[-1]["content"]
        now = dt.datetime.now(ZoneInfo(tz))
        ctx = {"now": now.isoformat(timespec="minutes"), "tz": tz, "today_iso": now.date().isoformat()}
        selected = {t.name for t in router.select(user_text, ctx)}
        schemas = [_hide_tz(s) for s in registry.schemas() if s["name"] in selected] or [
            _hide_tz(s) for s in registry.schemas()
        ]
        resp = await llm.chat(
            messages=_build_context(user_text, ctx),
            tools=schemas,
            max_tokens=cfg.llm.max_output_tokens,
            temperature=cfg.llm.temperature_tools,
            purpose="tool",
        )
        resp = normalize_response(resp, allowed_tools={s["name"] for s in schemas})
        chat_fn.last_reply = resp.text or ""  # judged by cases with no tool call (asks / claims)
        return normalise_tool_call(resp)

    chat_fn.last_reply = ""
    return chat_fn


async def run_live(llm, cases, cfg, delay: float = 0.0):
    registry, router = build_registry_and_router()
    chat_fn = make_chat_fn(llm, registry, router, cfg)
    results = []
    for case in cases:
        results.append(await run_case(case, chat_fn))
        mark = "ok " if results[-1].passed else "FAIL"
        sys.stdout.write(f"{mark} {case.id}: {case.user_text!r} -> {results[-1].got_tool}\n")
        if delay:
            await asyncio.sleep(delay)
    return results


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max", type=int, default=0, help="run only the first N cases")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between calls (rate limit)")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    args = parser.parse_args(argv)

    cfg = load_config()
    client, _limiter = build_llm(cfg, get_active_llm_key())
    if client is None:
        sys.stdout.write("No usable LLM: open Settings > AI, pick a model and save your key.\n")
        return 2
    cases = [c for c in CASES if not args.only or c.id in set(args.only.split(","))]
    if args.max:
        cases = cases[: args.max]
    model = cfg.llm.providers[cfg.llm.active].primary_model or "model"
    sys.stdout.write(f"Running {len(cases)} case(s) against {cfg.llm.active}/{model}\n")
    results = await run_live(client, cases, cfg, args.delay)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_model = model.replace("/", "_")
    path = REPORT_DIR / f"{dt.date.today().isoformat()}_{safe_model}.md"
    report = write_report(results, str(path), model=model)
    passed = sum(1 for r in results if r.passed)
    sys.stdout.write(f"\n{passed}/{len(results)} passed. Report: {path}\n")
    del report
    return 0 if passed == len(results) else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(_main(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
