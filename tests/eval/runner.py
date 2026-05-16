"""
tests/eval/runner.py — Eval harness CLI for FindMe v2 sprint.

Reads golden_queries.yaml, calls POST /api/chat (or /api/chat/v2) for each
query, scores responses against the rubric in rubric.md, and emits a per-query
pass/fail table + summary.

Usage (W1 baseline):
    .venv/bin/python -m tests.eval.runner \\
        --base-url http://localhost:8000 \\
        --output tests/eval/baselines/$(date +%F)-v1-baseline.md

For fast iteration:
    .venv/bin/python -m tests.eval.runner --limit 5 --base-url http://localhost:8000

The harness is read-only against the chat endpoint. It does not modify any data.
Each run makes one real Gemini call per query — use --limit while iterating.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GoldenQuery:
    """One query loaded from golden_queries.yaml."""

    id: str
    query: str
    expected_intent: str
    expected_needs_location: bool
    expected_has_results: bool
    history: list[dict[str, str]] = field(default_factory=list)
    expected_brand: Optional[str] = None
    expected_city: Optional[str] = None
    expected_max_price: Optional[float] = None
    brand_in_top: int = 1
    expected_tool_calls: Optional[list[dict[str, Any]]] = None
    notes: str = ""


@dataclass
class DimensionResult:
    """Score for one dimension on one query."""

    name: str
    applied: bool
    passed: bool
    expected: Any = None
    got: Any = None
    detail: str = ""


@dataclass
class QueryResult:
    """All dimension scores + meta for one query."""

    query: GoldenQuery
    dimensions: list[DimensionResult]
    response: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: float = 0.0

    @property
    def overall_pass(self) -> bool:
        if self.error:
            return False
        applied = [d for d in self.dimensions if d.applied]
        return bool(applied) and all(d.passed for d in applied)

    @property
    def failed_dimensions(self) -> list[DimensionResult]:
        return [d for d in self.dimensions if d.applied and not d.passed]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


_REQUIRED_QUERY_FIELDS = ("id", "query", "expected_intent")


def load_queries(path: Path) -> list[GoldenQuery]:
    """Parse golden_queries.yaml into typed GoldenQuery objects.

    Raises a clear error if the YAML is malformed, the `queries` key is
    missing/empty, a query is missing a required field, or IDs are duplicated.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not raw or not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level is not a mapping (empty or malformed YAML)")
    items = raw.get("queries")
    if items is None:
        raise ValueError(f"{path}: missing top-level 'queries:' key")
    if not isinstance(items, list):
        raise ValueError(f"{path}: 'queries' must be a list, got {type(items).__name__}")
    if not items:
        raise ValueError(f"{path}: 'queries' list is empty")

    queries: list[GoldenQuery] = []
    seen_ids: dict[str, int] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: query #{idx} is not a mapping")
        for required in _REQUIRED_QUERY_FIELDS:
            if required not in item:
                raise ValueError(
                    f"{path}: query #{idx} (id={item.get('id', '<unknown>')!r}) "
                    f"missing required field {required!r}"
                )
        qid = item["id"]
        if qid in seen_ids:
            raise ValueError(
                f"{path}: duplicate query id {qid!r} (first seen at index {seen_ids[qid]}, "
                f"again at index {idx})"
            )
        seen_ids[qid] = idx
        queries.append(
            GoldenQuery(
                id=qid,
                query=item["query"],
                expected_intent=item["expected_intent"],
                expected_needs_location=item.get("expected_needs_location", False),
                expected_has_results=item.get("expected_has_results", False),
                history=item.get("history", []),
                expected_brand=item.get("expected_brand"),
                expected_city=item.get("expected_city"),
                expected_max_price=item.get("expected_max_price"),
                brand_in_top=item.get("brand_in_top", 1),
                expected_tool_calls=item.get("expected_tool_calls"),
                notes=item.get("notes", ""),
            )
        )
    return queries


# ---------------------------------------------------------------------------
# Scoring (v1 — observable ChatResponse fields only)
# ---------------------------------------------------------------------------

# F-04 — these phrases must not appear in the reply when results are non-empty
_CONTRADICTION_PATTERNS = [
    "לא מצאתי",
    "לא מצאנו",
    "לא נמצא",
    "לא נמצאו",
    "no results found",
]


def _safe_lower(value: Any) -> str:
    """Lower-case for case-insensitive substring matching."""
    return str(value or "").lower()


def _results_count(response: dict[str, Any]) -> int:
    products = response.get("product_results") or []
    stores = response.get("store_results") or []
    return len(products) + len(stores)


def _top_product(response: dict[str, Any]) -> Optional[dict[str, Any]]:
    products = response.get("product_results") or []
    return products[0] if products else None


def _top_store(response: dict[str, Any]) -> Optional[dict[str, Any]]:
    stores = response.get("store_results") or []
    return stores[0] if stores else None


def score_response_v1(
    query: GoldenQuery,
    response: dict[str, Any],
) -> list[DimensionResult]:
    """Score a ChatResponse against the v1 rubric. Returns one DimensionResult per dimension."""
    dims: list[DimensionResult] = []

    # intent
    dims.append(
        DimensionResult(
            name="intent",
            applied=True,
            passed=response.get("intent") == query.expected_intent,
            expected=query.expected_intent,
            got=response.get("intent"),
        )
    )

    # needs_location
    dims.append(
        DimensionResult(
            name="needs_location",
            applied=True,
            passed=bool(response.get("needs_location")) == query.expected_needs_location,
            expected=query.expected_needs_location,
            got=response.get("needs_location"),
        )
    )

    # has_results
    actual_has = _results_count(response) > 0
    dims.append(
        DimensionResult(
            name="has_results",
            applied=True,
            passed=actual_has == query.expected_has_results,
            expected=query.expected_has_results,
            got=f"{_results_count(response)} results",
        )
    )

    # brand_top_result (only when expected_brand is set AND results are non-empty)
    if query.expected_brand:
        top = _top_product(response)
        if top is None:
            dims.append(
                DimensionResult(
                    name="brand_top_result",
                    applied=actual_has,  # only applies if results came back
                    passed=False,
                    expected=query.expected_brand,
                    got="no product results",
                )
            )
        else:
            top_brand = _safe_lower(top.get("brand"))
            expected_lower = _safe_lower(query.expected_brand)
            passed = expected_lower in top_brand
            dims.append(
                DimensionResult(
                    name="brand_top_result",
                    applied=True,
                    passed=passed,
                    expected=query.expected_brand,
                    got=top.get("brand"),
                    detail=top.get("canonical_name", ""),
                )
            )

    # city_top_result (only when expected_city is set AND store results came back)
    if query.expected_city:
        top = _top_store(response)
        if top is None:
            dims.append(
                DimensionResult(
                    name="city_top_result",
                    applied=actual_has,
                    passed=False,
                    expected=query.expected_city,
                    got="no store results",
                )
            )
        else:
            top_city = _safe_lower(top.get("city"))
            expected_lower = _safe_lower(query.expected_city)
            dims.append(
                DimensionResult(
                    name="city_top_result",
                    applied=True,
                    passed=expected_lower in top_city,
                    expected=query.expected_city,
                    got=top.get("city"),
                )
            )

    # price_filter_respected (only when expected_max_price is set)
    if query.expected_max_price is not None:
        products = response.get("product_results") or []
        tolerance = query.expected_max_price * 1.05
        # null prices allowed (OOS items)
        violators = [
            p for p in products
            if p.get("price") is not None and p["price"] > tolerance
        ]
        dims.append(
            DimensionResult(
                name="price_filter_respected",
                applied=bool(products),
                passed=len(violators) == 0,
                expected=f"all prices <= {tolerance:.0f}",
                got=f"{len(violators)} violators out of {len(products)}",
                detail=(
                    f"first violator: {violators[0].get('canonical_name')} @ {violators[0].get('price')}"
                    if violators else ""
                ),
            )
        )

    # no_contradiction (always applies)
    message = response.get("message", "") or ""
    has_results = actual_has
    contradicts = any(p in message for p in _CONTRADICTION_PATTERNS)
    dims.append(
        DimensionResult(
            name="no_contradiction",
            applied=True,
            passed=not (has_results and contradicts),
            expected="positive reply when results > 0",
            got=("contradiction" if (has_results and contradicts) else "ok"),
            detail=message[:80] if (has_results and contradicts) else "",
        )
    )

    return dims


def _args_superset(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """True iff every key in `expected` is in `actual` with a matching value.

    Match rules (unidirectional — actual must satisfy expected):
    - String values: case-insensitive containment. The expected substring must
      appear in the actual value. Single-letter or empty expected strings are
      treated as wildcards (always match) to prevent accidental over-matching.
    - Numeric values: relative tolerance of 5% (i.e. actual within ±5% of expected).
      No absolute floor — that previously matched anything near zero.
    - Booleans match exactly (NOT via numeric coercion).
    - Other types: equality.

    Bidirectional matching was rejected: under it, `expected={'brand': 'S'}`
    matched any brand containing 's', inflating tool_call_match scores.
    """
    for k, expected_v in expected.items():
        if k not in actual:
            return False
        actual_v = actual[k]
        # Bool must be checked BEFORE int (bool is a subclass of int in Python)
        if isinstance(expected_v, bool) or isinstance(actual_v, bool):
            if actual_v != expected_v:
                return False
        elif isinstance(expected_v, str) and isinstance(actual_v, str):
            exp_lower = expected_v.lower()
            # Tiny expected strings are not specific enough to be useful as a
            # discriminator — treat as wildcard so authors can pass `""` or
            # single letters as "any value" without false positives.
            if len(exp_lower) <= 1:
                continue
            if exp_lower not in actual_v.lower():
                return False
        elif isinstance(expected_v, (int, float)) and isinstance(actual_v, (int, float)):
            tolerance = abs(expected_v) * 0.05
            if abs(actual_v - expected_v) > tolerance:
                return False
        else:
            if actual_v != expected_v:
                return False
    return True


def score_response_v2(
    query: GoldenQuery,
    response: dict[str, Any],
) -> list[DimensionResult]:
    """Score a ChatResponseV2 (with trace) against v1 dims + v2 tool-call dims.

    v1 dimensions still apply (intent, has_results, etc.). v2 adds:
    - tool_call_match: every expected tool call has a matching real call
    - no_extra_tool_calls: agent didn't call more tools than expected (±1 tolerance)
    - empty_tool_calls: if expected_tool_calls == [], agent called ZERO tools
    """
    dims = score_response_v1(query, response)

    # v2 dims only apply when expected_tool_calls is explicitly set
    if query.expected_tool_calls is None:
        return dims

    trace = response.get("trace") or {}
    actual_calls = trace.get("tool_calls") or []
    expected_calls = query.expected_tool_calls

    # empty_tool_calls — Sally's comparison-turn scenario
    if not expected_calls:
        dims.append(
            DimensionResult(
                name="empty_tool_calls",
                applied=True,
                passed=len(actual_calls) == 0,
                expected="0 tool calls",
                got=f"{len(actual_calls)} tool calls",
                detail=", ".join(c.get("name", "?") for c in actual_calls) if actual_calls else "",
            )
        )
        return dims

    # tool_call_match — each expected call has a matching actual call
    matched = 0
    for expected in expected_calls:
        exp_name = expected.get("tool") or expected.get("name")
        exp_args = expected.get("args", {})
        found = any(
            actual.get("name") == exp_name
            and _args_superset(actual.get("args", {}), exp_args)
            for actual in actual_calls
        )
        if found:
            matched += 1

    dims.append(
        DimensionResult(
            name="tool_call_match",
            applied=True,
            passed=matched == len(expected_calls),
            expected=f"{len(expected_calls)} matching tool call(s)",
            got=f"{matched} matched",
            detail=", ".join(
                f"{c.get('name')}({list(c.get('args', {}).keys())})"
                for c in actual_calls
            ),
        )
    )

    # no_extra_tool_calls — ±1 tolerance (LLM may add a clarify-style call)
    diff = len(actual_calls) - len(expected_calls)
    dims.append(
        DimensionResult(
            name="no_extra_tool_calls",
            applied=True,
            passed=diff <= 1,
            expected=f"<= {len(expected_calls) + 1} tool calls",
            got=f"{len(actual_calls)} tool calls",
        )
    )

    return dims


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


async def call_chat(
    client: httpx.AsyncClient,
    base_url: str,
    endpoint: str,
    query: GoldenQuery,
) -> tuple[Optional[dict[str, Any]], Optional[str], float]:
    """POST to the chat endpoint. Returns (response_json, error_msg, latency_ms)."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    payload = {
        "message": query.query,
        "history": query.history,
        "voucher_network": "buyme",
    }
    start = asyncio.get_event_loop().time()
    try:
        resp = await client.post(url, json=payload, timeout=60.0)
        latency_ms = (asyncio.get_event_loop().time() - start) * 1000
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:200]}", latency_ms
        return resp.json(), None, latency_ms
    except httpx.TimeoutException:
        latency_ms = (asyncio.get_event_loop().time() - start) * 1000
        return None, "timeout (>60s)", latency_ms
    except Exception as exc:  # broad: harness must keep running
        latency_ms = (asyncio.get_event_loop().time() - start) * 1000
        return None, f"{type(exc).__name__}: {exc}", latency_ms


# ---------------------------------------------------------------------------
# Runner orchestration
# ---------------------------------------------------------------------------


async def run_all(
    queries: list[GoldenQuery],
    base_url: str,
    endpoint: str,
    concurrency: int,
) -> list[QueryResult]:
    """Run all queries against the chat endpoint with bounded concurrency."""
    results: list[QueryResult] = []
    sem = asyncio.Semaphore(concurrency)

    # Explicit connect/read/pool timeouts so a network-layer hang
    # (DNS, TCP connect) doesn't escape the per-call 60s timeout.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)
    ) as client:

        async def run_one(q: GoldenQuery) -> QueryResult:
            async with sem:
                response, error, latency_ms = await call_chat(client, base_url, endpoint, q)
                if error:
                    return QueryResult(
                        query=q,
                        dimensions=[],
                        error=error,
                        latency_ms=latency_ms,
                    )
                # v2 scoring when the response carries a trace (i.e. /api/chat/v2)
                if (response or {}).get("trace") is not None:
                    dims = score_response_v2(q, response or {})
                else:
                    dims = score_response_v1(q, response or {})
                return QueryResult(
                    query=q,
                    dimensions=dims,
                    response=response,
                    latency_ms=latency_ms,
                )

        tasks = [run_one(q) for q in queries]
        for fut in asyncio.as_completed(tasks):
            qr = await fut
            results.append(qr)
            # progress mark: "!" for infrastructure errors so operators can
            # tell them apart from legitimate eval failures (which are "✗").
            if qr.error:
                mark = "!"
            elif qr.overall_pass:
                mark = "✓"
            else:
                mark = "✗"
            sys.stderr.write(mark)
            sys.stderr.flush()
        sys.stderr.write("\n")

    # restore original query order
    order = {q.id: i for i, q in enumerate(queries)}
    results.sort(key=lambda r: order[r.query.id])
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _tag_for(query: GoldenQuery) -> str:
    """Extract a section tag from notes (F-XX, Sally, Edge, etc.)."""
    notes = query.notes
    m = re.search(r"\b(F-\d+(?:/F-\d+)?)", notes)
    if m:
        return m.group(1)
    if "Sally" in notes:
        return "Sally"
    if "Edge" in notes:
        return "Edge"
    if "Help" in notes or "help" in query.expected_intent:
        return "Help"
    if "Clarify" in notes or "clarify" == query.expected_intent:
        return "Clarify"
    if "English" in notes:
        return "English"
    return "Other"


def render_report(
    results: list[QueryResult],
    base_url: str,
    endpoint: str,
    command: str,
) -> str:
    """Render a Markdown report from the run."""
    total = len(results)
    passed = sum(1 for r in results if r.overall_pass)
    errors = sum(1 for r in results if r.error)
    overall_pct = (passed / total * 100) if total else 0.0

    # Per-dimension stats
    dim_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"applied": 0, "passed": 0})
    for r in results:
        for d in r.dimensions:
            if d.applied:
                dim_stats[d.name]["applied"] += 1
                if d.passed:
                    dim_stats[d.name]["passed"] += 1

    # Per-section stats
    section_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "passed": 0})
    for r in results:
        tag = _tag_for(r.query)
        section_stats[tag]["total"] += 1
        if r.overall_pass:
            section_stats[tag]["passed"] += 1

    lines: list[str] = []
    lines.append(f"# FindMe Eval Run — {endpoint}")
    lines.append("")
    lines.append(f"**Command:** `{command}`  ")
    lines.append(f"**Base URL:** {base_url}  ")
    lines.append(f"**Endpoint:** {endpoint}  ")
    lines.append(f"**Total queries:** {total}  ")
    lines.append(f"**Errors:** {errors}  ")
    lines.append(f"**Overall pass rate:** {passed}/{total} = **{overall_pct:.1f}%**")
    lines.append("")
    lines.append("## Per-dimension pass rate")
    lines.append("")
    lines.append("| Dimension | Pass / Applied | % |")
    lines.append("|---|---:|---:|")
    for name in sorted(dim_stats):
        s = dim_stats[name]
        pct = (s["passed"] / s["applied"] * 100) if s["applied"] else 0.0
        lines.append(f"| {name} | {s['passed']} / {s['applied']} | {pct:.1f}% |")
    lines.append("")
    lines.append("## Per-section pass rate")
    lines.append("")
    lines.append("| Section | Pass / Total | % |")
    lines.append("|---|---:|---:|")
    for tag in sorted(section_stats):
        s = section_stats[tag]
        pct = (s["passed"] / s["total"] * 100) if s["total"] else 0.0
        lines.append(f"| {tag} | {s['passed']} / {s['total']} | {pct:.1f}% |")
    lines.append("")
    lines.append("## Latency")
    lines.append("")
    latencies = sorted(r.latency_ms for r in results)
    if latencies:
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else latencies[0]
        lines.append(f"- p50: {p50:.0f} ms")
        lines.append(f"- p95: {p95:.0f} ms")
        lines.append(f"- max: {max(latencies):.0f} ms")
    lines.append("")

    # Top failures (up to 15)
    failures = [r for r in results if not r.overall_pass]
    lines.append(f"## Top failures ({len(failures)} total)")
    lines.append("")
    for r in failures[:15]:
        lines.append(f"### `{r.query.id}` — {r.query.notes}")
        lines.append(f"**Query:** `{r.query.query}`  ")
        if r.error:
            lines.append(f"**Error:** {r.error}  ")
        else:
            for d in r.failed_dimensions:
                lines.append(
                    f"- ❌ **{d.name}**: expected `{d.expected}`, got `{d.got}`"
                    + (f" — {d.detail}" if d.detail else "")
                )
        lines.append("")

    # Full per-query table
    lines.append("## All queries")
    lines.append("")
    lines.append("| # | ID | Pass? | Failed dimensions |")
    lines.append("|---:|---|:---:|---|")
    for i, r in enumerate(results, 1):
        mark = "✅" if r.overall_pass else "❌"
        if r.error:
            failed = f"ERROR: {r.error[:60]}"
        else:
            failed = ", ".join(d.name for d in r.failed_dimensions) or "—"
        lines.append(f"| {i} | `{r.query.id}` | {mark} | {failed} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="FindMe v2 eval harness")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Backend base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--endpoint",
        default="/api/chat",
        help="Chat endpoint path (default: /api/chat). Use /api/chat/v2 for v2 once it exists.",
    )
    parser.add_argument(
        "--queries-file",
        default=str(Path(__file__).parent / "golden_queries.yaml"),
        help="Path to golden_queries.yaml",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N queries (for fast iteration)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="Max concurrent requests (default: 3 — keep low to avoid rate limits)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write the report to this file (in addition to stdout summary)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of Markdown to stdout",
    )
    args = parser.parse_args()

    queries_path = Path(args.queries_file)
    if not queries_path.exists():
        print(f"ERROR: queries file not found: {queries_path}", file=sys.stderr)
        return 2

    queries = load_queries(queries_path)
    if args.limit:
        queries = queries[: args.limit]

    print(
        f"→ Running {len(queries)} queries against {args.base_url}{args.endpoint} "
        f"(concurrency={args.concurrency})",
        file=sys.stderr,
    )
    results = asyncio.run(
        run_all(queries, args.base_url, args.endpoint, args.concurrency)
    )

    # Whitelist args echoed into the report's "Command" line. Prevents future
    # auth/secret flags from leaking into committed baseline files.
    _ECHO_ARGS = {"base_url", "endpoint", "queries_file", "limit", "concurrency", "output", "json"}
    command = "python -m tests.eval.runner " + " ".join(
        f"--{k.replace('_', '-')}={v}"
        for k, v in vars(args).items()
        if k in _ECHO_ARGS and v not in (None, False)
    )

    # --json + --output are now compatible: write JSON to file when both given.
    if args.json:
        payload = {
            "total": len(results),
            "passed": sum(1 for r in results if r.overall_pass),
            "errors": sum(1 for r in results if r.error),
            "results": [
                {
                    "id": r.query.id,
                    "query": r.query.query,
                    "notes": r.query.notes,
                    "overall_pass": r.overall_pass,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                    "dimensions": [
                        {
                            "name": d.name,
                            "applied": d.applied,
                            "passed": d.passed,
                            "expected": d.expected,
                            "got": d.got,
                            "detail": d.detail,
                        }
                        for d in r.dimensions
                    ],
                }
                for r in results
            ],
        }
        json_text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json_text, encoding="utf-8")
            print(f"→ JSON written to {out_path}", file=sys.stderr)
        else:
            print(json_text)
    else:
        report = render_report(results, args.base_url, args.endpoint, command)
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report, encoding="utf-8")
            print(f"→ Report written to {out_path}", file=sys.stderr)
        # always print summary to stdout
        total = len(results)
        passed = sum(1 for r in results if r.overall_pass)
        errors = sum(1 for r in results if r.error)
        pct = (passed / total * 100) if total else 0.0
        print()
        print(f"Pass rate: {passed}/{total} = {pct:.1f}% (errors: {errors})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
