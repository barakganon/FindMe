# FindMe — Deferred Work Log

> Items surfaced during code reviews that are real concerns but out-of-scope for the current story.
> Each entry includes the originating review, the file location, and the deferral reason.

## Deferred from: code review of story 5-1 & 5-2 (2026-05-15)

**Story 5.1 (eval harness):**

- `_tag_for` regex uses `\b` ASCII word boundary — fine for English-only `notes` today but would miss F-XX inside Hebrew prefixes in future versions of `golden_queries.yaml` [tests/eval/runner.py: _tag_for]. *Deferred: English-only notes today; revisit if Hebrew notes are added.*
- `asyncio.get_event_loop().time()` raises DeprecationWarning on Python 3.10+ and breaks on 3.12 with no running loop. Works today on this stack because the call is inside an `await`. [tests/eval/runner.py: call_chat]. *Deferred to Python version upgrade.*
- `p95 = latencies[int(len(latencies) * 0.95)]` index is sloppy for small N (≤20 it ≈ p100). Works for our baseline of 42 queries. [tests/eval/runner.py: render_report]. *Deferred: baseline N always > 20.*

**Story 5.2 (agent loop thin slice):**

- Tool description currently teaches Gemini to translate Hebrew product types to English (`'אוזניות סוני' → query='headphones'`). This may hurt recall against Hebrew-only catalog rows. [api/agent/tools/search_products.py: SEARCH_PRODUCTS_SPEC description]. *Deferred to W6 — A/B both behaviors during prompt iteration sprint.*
- `ChatMessage.role` allows `"tool"` in history coercion, but `ChatMessage` schema lacks `tool_call_id` field — replaying history with `role=tool` turns will produce LLM API 400 errors (tool message must have tool_call_id). [api/agent/loop.py: history coercion + api/schemas.py: ChatMessage]. *Deferred to W3 — Redis session memory work needs to address this contract change.*
- `_run_product_search` is imported inside `execute_search_products` as a circular-dependency band-aid. The comment in `search_products.py` acknowledges this. [api/agent/tools/search_products.py: execute_search_products]. *Deferred to W4 — when audit fixes refactor search code, move `_run_product_search` to a shared `api/search_core.py` module so it has no chat-route imports.*
- `result.store_results` is never populated; tool-result-handling hardcodes `if tool_name == "search_products"` and ignores other tools. Comment in loop.py notes "Future: store_search tool would extend result.store_results here." [api/agent/loop.py: tool dispatch result handling]. *Deferred to W3 — generalize when `search_stores` tool lands.*
- `needs_location` hardcoded `False` in `chat_v2.py` — no equivalent of v1's GPS prompt mechanism. Documented in the W2 baseline interpretation. [api/routes/chat_v2.py: ChatResponseV2 construction]. *Deferred to W3 — `clarify` / `needs_location` tool lands then.*
