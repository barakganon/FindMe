# FindMe — Deferred Work Log

> Items surfaced during code reviews that are real concerns but out-of-scope for the current story.
> Each entry includes the originating review, the file location, and the deferral reason.

## Deferred from: code review of story 5-7-ui-polish-and-repair (2026-05-29)

- **Anon → logged-in derived_facts migration.** Redis key changes from `anon:<sid>` to `user:<id>` at registration; chip strip loses session-derived facts. Fix touches `/api/auth/import-session` (accept `X-Session-ID` header, do a Redis `RENAME` or copy+delete with race handling), the frontend `register()` flow (send `X-Session-ID`), plus tests. *Deferred: out of scope for UI story; tiny incidence at soft-launch scale; a 1–2 commit follow-up.*


- `tests/api/test_chips.py::test_logged_in_both_ordering_and_cap` feeds 7 chips (2 prefs + 5 inferred); 6-cap assertion `len(chips) <= 6` would pass at 5 or 7 too. *Deferred: behavior is correct in `chips.py` (slice `[:6]`); strengthen the assertion in a test-pass story.*
- No test asserts unconfirmed chips are sorted confidence-desc within the unconfirmed group. Behavior is correct via `order_by(UserInferredAttribute.confidence.desc())` in `chips.py`. *Deferred: pure test-coverage gap.*
- `MemoryChip.kind` is a free `str` in Pydantic but a `Literal['preference'|'inferred'|'session']` in TS — a future schema drift could produce wire values the frontend casts blindly. *Deferred: tighten to `Literal` in a follow-up schema-hardening pass.*
- `_dispatchFrame` in `frontend/src/api.ts` silently drops `partial_content` SSE events because the backend doesn't emit them yet. If W8+ adds token-level streaming and rolls out gradually, this case becomes a landmine. *Deferred: implement when backend gains token streaming.*

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

## Deferred from: Story 5.9 review + polish (2026-06-14)

- **Cost-cap TOCTOU.** `is_session_over_budget` is read-then-act; two concurrent turns in one session can both pass the gate before either `register_session_cost`. [api/routes/chat_v2.py, chat_v2_stream.py]. *Acceptable under the fail-open design; revisit with an atomic Redis check-and-increment (Lua/`INCRBYFLOAT`-then-compare) if real abuse appears.*
- **Streaming partial-cost on error.** If `run_agent` raises mid-stream, the early return skips `register_session_cost`, so partial LLM spend for that turn is never counted toward the session/daily ceilings. [api/routes/chat_v2_stream.py]. *Deferred — needs the loop to surface partial cost on exception before it can be registered.*
- **Chunked-body bypass of the size guard.** `BodySizeLimitMiddleware` checks only `Content-Length`; a chunked request with no length header isn't byte-counted. [api/middleware.py]. *uvicorn framing limits are the backstop; the realistic large-JSON-POST attack always sends Content-Length. Revisit only if chunked abuse is observed.*
