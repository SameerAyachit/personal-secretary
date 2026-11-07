"""Eval harness: runs cases against an LLM client and writes a report (plan §17.4).

The harness is intentionally decoupled from the agent loop: it takes a
``chat_fn(messages, tools) -> dict | None`` that returns a normalised tool call
(the first tool call) or None. This lets CI run the harness against FakeLLM
contracts on every push, and later against the real agent loop (plan §17.4:
"CI runs the eval harness against FakeLLM contracts on every push").

Metrics per case: valid call, correct tool, correct args (when_text, not
resolved times). Report is saved to docs/eval_results/<date>_<model>.md.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from secretary.llm.base import LLMResponse

ChatFn = Callable[[list[dict], list[dict] | None], object]


@dataclass
class EvalResult:
    case_id: str
    category: str
    user_text: str
    passed: bool
    expected_tool: str | None
    got_tool: str | None
    got_args: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str = ""


def normalise_tool_call(resp: LLMResponse) -> dict | None:
    """Return the first tool call as {name, args}, or None if none."""
    if not resp.tool_calls:
        return None
    tc = resp.tool_calls[0]
    return {"name": tc.name, "args": dict(tc.args or {})}


async def run_case(case, chat_fn: ChatFn) -> EvalResult:
    messages = [{"role": "user", "content": case.user_text}]
    start = time.monotonic()
    try:
        maybe = chat_fn(messages, None)
        if asyncio.iscoroutine(maybe):
            tool_call = await maybe
        else:
            tool_call = maybe
        latency_ms = (time.monotonic() - start) * 1000
        passed = case.passes(tool_call)
        return EvalResult(
            case_id=case.id,
            category=case.category,
            user_text=case.user_text,
            passed=passed,
            expected_tool=case.expected_tool,
            got_tool=(tool_call or {}).get("name"),
            got_args=(tool_call or {}).get("args", {}) or {},
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return EvalResult(
            case_id=case.id,
            category=case.category,
            user_text=case.user_text,
            passed=False,
            expected_tool=case.expected_tool,
            got_tool=None,
            got_args={},
            latency_ms=latency_ms,
            error=repr(exc),
        )


async def run_all(cases, chat_fn: ChatFn) -> list[EvalResult]:
    return [await run_case(c, chat_fn) for c in cases]


def summary(results: list[EvalResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    by_category: dict[str, dict] = {}
    for r in results:
        b = by_category.setdefault(r.category, {"total": 0, "passed": 0})
        b["total"] += 1
        if r.passed:
            b["passed"] += 1
    latencies = [r.latency_ms for r in results if r.latency_ms]
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total * 100) if total else 0.0,
        "by_category": by_category,
        "median_latency_ms": statistics.median(latencies) if latencies else 0.0,
        "mean_latency_ms": statistics.mean(latencies) if latencies else 0.0,
    }


def generate_report(results: list[EvalResult], model: str = "fake") -> str:
    s = summary(results)
    lines: list[str] = [
        f"# Secretary eval report — {model}",
        f"Generated: {_dt.datetime.now().isoformat(timespec='seconds')}",
        "",
        f"Total cases: {s['total']}  |  Passed: {s['passed']}  |  Failed: {s['failed']}",
        f"Pass rate: {s['pass_rate']:.1f}%",
        f"Median latency: {s['median_latency_ms']:.1f} ms  |  Mean latency: {s['mean_latency_ms']:.1f} ms",
        "",
        "## Decision table (plan §7.9)",
        "| Result | Action |",
        "|---|---|",
        "| ≥ 90% | Proceed with this model as primary. |",
        "| 80-89% | Keep as primary; echo-before-write for all writes; route failures to fallback. |",
        "| < 80% | Promote another model for write tools only; keep this one for chat and summaries; re-measure. |",
        "",
        "## Per-category results",
        "| Category | Passed | Total | Pass rate |",
        "|---|---|---|---|",
    ]
    for cat, b in sorted(s["by_category"].items()):
        rate = (b["passed"] / b["total"] * 100) if b["total"] else 0.0
        lines.append(f"| {cat} | {b['passed']} | {b['total']} | {rate:.1f}% |")
    lines += [
        "",
        "## Case details",
        "| ID | Category | Passed | Expected tool | Got tool | Error |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.category} | {'YES' if r.passed else 'no'} | "
            f"{r.expected_tool or '—'} | {r.got_tool or '—'} | {r.error or '—'} |"
        )
    return "\n".join(lines) + "\n"


def write_report(results: list[EvalResult], path: str, model: str = "fake") -> str:
    report = generate_report(results, model)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(report)
    return report
