# Epic 5 Retrospective — Agentic Conversation Refactor

> **Status:** Draft — awaiting sign-off from Barak  
> **Drafted:** 2026-06-14  
> **Epic period:** 2026-05-15 → 2026-06-14 (W1–W9, planned 11 weeks)  
> **Retrospective type:** Solo engineering, post-epic (Epic 5 stories 5.1–5.9)

---

## 1. Epic Summary

### Goal

Rebuild FindMe's chat layer from a one-shot **intent-parser → search → composer** pipeline into a fully agentic conversation loop: a Gemini-2.5-flash LLM calling tools (`search_products`, `search_stores`, `get_user_context`, `recall_history`, `clarify`), holding multi-turn state in Redis, and streaming its thinking to the user via SSE. Target: a Hebrew-speaking BuyMe card holder can complete a 3-turn conversation and tap a store link they trust.

### The Strategic Pivot (2026-05-15)

Epic 1 (AWS + Vercel public launch) was **superseded** on 2026-05-15 following a 5-round party-mode architecture discussion. Decision: the single-shot v1 chat.py pipeline was fundamentally insufficient for the product thesis. Rather than ship it and iterate, the plan pivoted to an 11-week solo rebuild. Epic 1 stories 1.2–1.5 (Render infra, Vercel frontend, production smoke test, private-beta QA fixes) were marked `superseded`; the deploy target moved to Render but the Render deploy itself was deferred to W9 (Story 5.9). The pivot also superseded the v1 AWS deploy design (Dockerfile, EC2 setup, S3 OAC) that had been built in the months prior.

### Keep / Rewrite / Defer Outcome

| Verdict | Planned | Actual outcome |
|---------|---------|----------------|
| Keep | `_embed`, `_vec_literal`, hybrid SQL, geo query, `inference.py`, Redis, JWT, schema, ResultCard, StoreCard, embedding pipeline | All kept; search algorithm untouched |
| Rewrite | `api/routes/chat.py` → agent loop; `ChatInterface.tsx` → conversation + Tray + streaming | Both rewritten (W2–W7); v1 chat.py kept as cost-guard fallback |
| Defer | Admin dashboard, blanket data relabel, voice input, dark mode, language switcher | All deferred; no scope creep |

### Story Status at Close of Epic (2026-06-14)

| Week | Story | Status | Key facts |
|------|-------|--------|-----------|
| W1 | 5.1 Eval harness | done | 42 golden queries, v1 baseline 61.9%. Reviewed + patched 2026-05-16 |
| W2 | 5.2 Agent loop thin slice | done | Kill-gate PASSED: 21/21 = 100% tool_call_match (harness-measured post-patch). PR #2 merged |
| W3 | 5.3 Tools + memory | done | 4 new tools + Redis session memory. Gate: 32/35 = 91.4% tool_call_match. PR #3 merged |
| W4 | 5.4 Audit fixes + telemetry | done | F-11 100%, F-09 67%, telemetry live. PR #4 merged |
| W5 | 5.5 Streaming + soft launch | done (partial) | SSE + cost guard + invite allowlist. Frontend rebuild + Render deploy **deferred**. PR #5 merged |
| W6 | 5.6 Prompt iteration | done | brand_top_result +49 pts, intent 91.8%, overall 63.6% → 69.4%. PR #6 merged |
| W7 | 5.7 UI polish + repair | review | Results tray, memory chips, mind-changer. 18 code-review patches applied (commit `2ea592f`). **Manual validation not yet run** (template at `tests/eval/baselines/w7-ui-validation-template.md`). PR #8 merged to master |
| W8 | 5.8 Test rewrite | ready-for-dev | 40+ tests around tools. PR #9 opened (in review per sprint-status). Target: ≥187 tests total (was 141) |
| W9 | 5.9 Cost + deploy hardening | backlog | Caching, rate limits, prod Render deploy. PR #10 opened per task description (not confirmed by artifacts) |

---

## 2. What Shipped vs Planned — Kill Gates

### End W1 Gate: Does Gemini-2.5-flash emit Hebrew tool-calls correctly?

**Result: PASS** (measured in W2 after first baseline).  
W1 established the eval harness and v1 baseline (26/42 = 61.9%). The W2 thin slice confirmed Gemini can emit Hebrew tool-calls. Provider swap to Claude Sonnet 4.7 was **not triggered**.

### End W2 Gate: Tool-call accuracy ≥80%?

**Result: PASS — 100% (21/21)** (harness-measured, `2026-05-15-v2-w2-killgate.md` → patched to `2026-05-16-v2-post-review-patches.md`).  
Initial author-narrated figure was 96.8% (30/31 Hebrew queries). A code-review finding flagged that the rubric's `tool_call_match` dimension scored only 1 query. After backfilling `expected_tool_calls` across the golden set, the harness confirmed 21/21 = 100%. The "surprising regression" at the overall level (61.9% → 33.3%) was expected: v2 had only `search_products`; F-11 store queries (7) and F-03 near-me queries (4) correctly returned nothing because the tools didn't exist yet.

### End W4 Gate: Does multi-turn coherence hold with Redis state?

**Result: PASS** (not explicitly named "gate cleared" in status notes, but W4 delivered all expected deliverables).  
Telemetry live (agent_traces table); session memory confirmed via unit tests. F-11 reached 100%, F-09 reached 67%. The "freeze + slip 1 week" failure condition was not triggered.

### End W5 Gate: Do 5 friends complete a 3-turn conversation?

**Result: NOT RUN.** The Render deploy and frontend rebuild were deferred out of W5. The backend SSE endpoint shipped but no real-user test was conducted. This was the most significant gap between plan and execution: the "soft-launch to 5 friends end of Week 5" commitment was not met. No failure email or gate decision is recorded in the artifacts.

---

## 3. Metrics — What the Numbers Actually Show

### Eval harness: overall pass rate trajectory

| Checkpoint | Queries scored | Pass rate | Notes |
|------------|---------------|-----------|-------|
| v1 baseline (W1) | 42 | **61.9%** | Single-shot intent parser, all categories |
| v2 W2 thin slice | 42 | 33.3% | v2 with search_products only; F-11 + F-03 absent by design |
| v2 post-review patches | 44 | 34.1% | Rubric expanded; no substantive code change |
| v2 W3 (tools + memory) | 44 | 56.8% | +22.7 pts; F-11 back, F-03 at 100% |
| v2 W4 (audit fixes) | 44 | 63.6% | +6.8 pts; F-11 at 100%, F-09 67% |
| v2 W6 (prompt iteration) | 49 | **69.4%** | +5.8 pts from W4; rubric expanded to 49 queries |

### Per-dimension highlights at W6 (final measured state)

| Dimension | W1 (v1) | W6 (v2) | Change |
|-----------|---------|---------|--------|
| brand_top_result | 22.2% (2/9) | **77.8%** (7/9) | **+55.6 pts** |
| intent | 81.0% | **91.8%** | +10.8 pts |
| tool_call_match | N/A | **100%** (36/36) | new dimension |
| F-11 city queries | 85.7% | **100%** | +14.3 pts |
| F-03 location synonyms | 0% | **100%** | +100 pts |
| F-09 single brand | 33.3% | **100%** | +66.7 pts |
| needs_location | 100% | 100% | unchanged |
| price_filter_respected | 100% | 100% | unchanged |
| no_contradiction | 97.6% | 89.8% | -7.8 pts (expected: agent now surfaces mismatches honestly) |
| Clarify section | 100% (2/2) | 0% (0/4) | regression — see Section 5 |
| Sally scenarios | 40% (2/5) | 60% (3/5) | +20 pts; Avi + mind-changer pass, Rinat + comparison fail |

### tool_call_match progression

| Week | Score | Threshold |
|------|-------|-----------|
| W2 pre-patch | 0/1 = 0% (rubric gap, not a model failure) | ≥80% |
| W2 post-patch | **21/21 = 100%** | ≥80% |
| W3 | 32/35 = 91.4% | ≥80% |
| W4 | 33/35 = 94.3% | ≥80% |
| W6 | **36/36 = 100%** | ≥80% |

### brand_top_result: +49 pts from W6 prompt iteration alone

Per the W6 baseline notes: the brand re-rank in `search_products` (3-tier: brand-match first, other-brand second, no-brand last) lifted brand_top_result from 28.6% (W4) to 77.8% (W6) — a gain of +49.2 percentage points in one week. This is the single biggest quality jump in the epic.

### Cost guard (non-negotiable per wall-list)

Implemented in W5: 50¢/session, $20/day, circuit-breaks to v1 `/api/chat`. Specific measured trigger rates are **not recorded** in the artifacts.

### Test suite growth

| Checkpoint | Test count |
|------------|-----------|
| Pre-W8 (Story 5.8 spec) | **141 collected** |
| W8 target | **≥ 187** (≥ 46 net new) |
| W8 actual (not yet merged) | not recorded |

Note: test count between W1 and pre-W7 is not recorded in artifacts beyond the W8 spec baseline of 141.

### Latency (from eval baselines)

| Checkpoint | p50 | p95 | max |
|------------|-----|-----|-----|
| v1 baseline | 3,420 ms | 5,602 ms | 37,358 ms |
| v2 W2 | 3,008 ms | 4,389 ms | 4,775 ms |
| v2 W6 | 2,973 ms | 5,097 ms | 5,900 ms |

v2 eliminated the v1 p95 outlier (37s cold-start/rate-limit spike). The v1 max was a one-off; the v2 p95 is stable in the 4–5s range.

### Data catalog state (from CLAUDE.md)

- **135,865 products**, 99.3% embedded at end of epic
- Brand backfill (W4): 58 products tagged (Sony 13, HP 14, Bosch 9, Samsung 7, etc.)
- Image URLs: 1,743 scraped for Femina; rest pending (not a sprint blocker)

---

## 4. What Went Well

**Eval harness as a disciplined spine.** The golden queries file + runner were built in W1 before any agent code. Every subsequent week had a measured baseline to compare against. The W2 code-review finding (rubric only scored 1 query for tool_call_match) was caught and corrected within the same week, before it could mislead W3 decisions. The harness was the most important thing built in the epic.

**Gemini-2.5-flash held up in Hebrew.** The W2 kill-gate was the highest-stakes decision point (swap to Claude or continue). 30/31 Hebrew product queries triggered correct tool calls on the first harness run, well above the 80% threshold. No provider swap was needed. Eleven weeks later, tool_call_match sits at 100%.

**Brand re-rank was a high-leverage, low-risk intervention.** W6's 3-tier brand re-rank (a post-search sort on the tool output, not a SQL filter change) lifted brand_top_result by +49 pts without touching the search algorithm. This validated the "boost not restrict" architecture rule written into CLAUDE.md.

**Code review discipline per PR.** Every story PR went through code review and produced a batch of patches before merge: 27 findings on stories 5.1+5.2 (commit `e861a84`), 18 patches on 5.7 (commit `2ea592f`). The deferred-work log captured items that were real concerns but correctly out of scope, preventing scope creep while preserving the signal.

**Keep/Rewrite/Defer held.** The wall-list was respected: the search algorithm (`search.py`, `stores.py`) was not touched; LLM prompts stayed in `api/prompts.py`; anonymous user access was never blocked; no APScheduler crept in.

**City synonym expansion (W4) was a force multiplier.** F-11 went from 0% (W2, no search_stores tool) → 86% (W3, single store returned) → 100% (W4, expand_city returning full TLV/Jerusalem/Haifa/Eilat buckets). The fix — an OR-of-ILIKEs across synonym variants — was cheap relative to its rubric impact.

---

## 5. What Was Hard / Went Wrong

**W5 soft-launch never happened.** The plan committed to "soft-launch to 5 friends end of Week 5." The backend (SSE + cost guard + allowlist) shipped, but the frontend rebuild and Render deploy were deferred out of W5. No real-user feedback was collected at any point in the epic. The W7 manual validation template was created but was not filled in (notes marked "fill in" remain blank). This is the most significant unmet commitment.

**W7 manual validation is outstanding.** Story 5.7 is in `review` status with PR #8 merged to master, but AC-8 (manual run against all 5 canonical scenarios, signed off by Barak) has not been completed. The UI gate question ("Does the mind-changer scenario survive?") has no recorded answer. The validation template lives at `tests/eval/baselines/w7-ui-validation-template.md`.

**Clarify section regressed at W6 and stayed regressed.** At W6, 4 new probe queries were added (`?`, `מה?`, `abc`, SQL injection junk). All 4 failed because Gemini calls `search_products` on short ambiguous strings despite the system prompt's "DO NOT" rules. The Clarify section dropped from 100% (2/2 at v1) to 0% (0/4 at W6). This is a known model-behavior limitation; no code-level fix was shipped.

**no_contradiction regressed by design but the rubric still penalizes it.** Once the agent received structured item-level data (W2 post-patch), it started writing honest replies that acknowledge brand mismatches ("לא מצאתי Sony, אבל הנה Edifier"). The contradiction guard flags these because the reply says "didn't find" while returning results. The right fix (SQL-layer brand filter) was deferred; the rubric regression (-7.8 pts from W1 to W6) is real but reflects more honest behavior, not worse behavior.

**F-08 (Sony WH-1000XM5 → D-LINK) never fixed.** The exact-model brand query returning D-LINK IP CAM 3MP (which has "SONY EXMOR LENS" in the product name) was present in the W1 baseline and was still failing at W6. The brand re-rank can only sort Sony results to the top if any Sony products appear in the candidate set; if the candidate set has zero Sony items (because the SQL doesn't filter by brand), sorting can't help. The SQL-layer fix was deferred to a future story.

**Sally Rinat memory-recall never passed the harness.** "תראה לי שוב כמו פעם שעברה" should call `recall_history` before searching. At W6, Gemini called `search_stores` instead. Additional system-prompt examples didn't move the needle. This is not a blocker for soft-launch but degrades the Sally Scenario 4 story.

**Deferred data tasks remain unblocked but unexecuted.** Three pending tasks from CLAUDE.md have been deferred since before the epic:
- `python -m db.run_geocoding` (needs `GOOGLE_MAPS_API_KEY` — key not yet provisioned)
- `python -m normalization.deduplication` (dedup not run)
- Scraper re-run for `image_url` (only 1,743/135,865 products have images; Femina done, rest pending)

**v1 fallback complexity.** Keeping v1 `/api/chat` alive as a cost-guard fallback meant two chat code paths that diverged across the epic. The W7 frontend's `streamChatV2` includes a `503 → v1` fallback path. This was the right call (non-negotiable per the wall-list), but it created ongoing maintenance surface that shows up in the deferred-work log (e.g., `_dispatchFrame` silently dropping `partial_content` events because the backend doesn't emit them yet).

**Anon → logged-in derived_facts migration is a known gap.** When an anonymous user registers, the Redis key changes from `anon:<sid>` to `user:<id>`. The chip strip loses session-derived facts. The fix requires coordinating `/api/auth/import-session`, the frontend `register()` flow, and race-safe Redis operations. Deferred from W7; noted in `deferred-work.md`.

---

## 6. Lessons Learned

**Measure the kill gates before the week closes, not after.** The W2 kill-gate "96.8% Hebrew tool-call accuracy" was initially author-narrated (hand-counted, not harness-scored). The code review caught it, but it required a retroactive patch of the golden set. A rule: every gate metric must be emitted by the harness, not counted by the developer.

**The eval rubric is a contract — expanding it mid-sprint changes the score.** The golden set grew from 42 queries (W1) to 44 (W2 patch) to 49 (W6). Each expansion that adds failing queries lowers the headline score even when underlying quality improves. Future sprints should freeze the rubric for week-over-week comparison and only expand it when a new capability ships (W3 adding store tools was a legitimate expansion; W6 adding junk probes that the model reliably fails was not).

**"Soft-launch to 5 friends" needs a hard blocker, not a calendar date.** W5's soft-launch missed because the frontend wasn't ready. The gate question ("Do real humans complete a 3-turn convo?") required a deployed frontend — which wasn't treated as a prerequisite but should have been. In a future sprint, this would be a P0 story dependency, not a parallel track.

**Boost-not-restrict pays off fast.** The decision to have inferred attributes and brand re-rank boost search results rather than filter them was made early and held throughout. W6's +49 pt brand_top_result gain came from a sort, not a SQL change. This preserved catalog coverage while improving surface quality.

**Deferred work needs an owner and a home.** `deferred-work.md` captures 10+ items from code reviews. Some (anon→auth migration, MemoryChip.kind Literal) are small, well-scoped, and sitting idle. In the next epic, any deferred item that exceeds 2 engineering hours of future remediation should be filed as a story immediately rather than accruing indefinitely in a log.

**Manual validation is a story acceptance criterion, not a nice-to-have.** Story 5.7's AC-8 (manual run against 5 scenarios) was written and templated but not executed before the PR merged to master. The story remains in `review` status. In a future sprint, the story file would block `done` until the template is filled and signed.

**The wall-list worked.** "Re-read it every Monday" kept scope under control across 9 weeks. No dark mode, no voice input, no APScheduler, no frontend test framework, no mutation testing landed in the epic. The wall-list should be a standard artifact for every future epic.

---

## 7. Carry-Forward / Next Epic

### Open items from Epic 5

| Item | Priority | Notes |
|------|----------|-------|
| Story 5.7 manual validation | P0 | Run the 5 canonical scenarios against the W7 UI; fill in `w7-ui-validation-template.md`; sign off |
| Story 5.8 (W8 test rewrite) | P0 | PR #9 in review; target ≥187 tests; eval-nightly must not false-fail |
| Story 5.9 (W9 cost + deploy hardening) | P0 | PR #10 per task description; Render deploy is the first public deployment of v2 |
| W5 soft-launch: real-user test | High | 5-friend test never ran; needs Render deploy to complete |
| F-08 SQL-layer brand filter | Medium | Sony WH-1000XM5 → D-LINK not fixed by re-rank; requires `AND brand ILIKE '%Sony%'` in chat.py:372 |
| Sally Rinat memory-recall | Medium | `recall_history` routing fails; needs additional system-prompt examples or code-level heuristic |
| Clarify-on-junk-input | Medium | 0/4 on W6 clarify probes; may need a code-level short-circuit before the LLM sees the message |
| Anon → logged-in derived_facts migration | Low | Deferred from W7; `/api/auth/import-session` + frontend `register()` + Redis RENAME with race handling |
| MemoryChip.kind tighten to Literal | Low | Currently `str` in Python, `Literal` in TS — schema drift risk |
| `_dispatchFrame` partial_content handling | Low | Silently drops events when backend gains token-level streaming |
| `db.run_geocoding` | Low | Needs `GOOGLE_MAPS_API_KEY` provisioned |
| `normalization.deduplication` | Low | Not run; <2% dupes target (data audit P2) unverified |
| `image_url` backfill | Low | 1,743/135,865 products have images; scraper re-run needed |

### Pending Epics (all backlog, not yet started)

| Epic | Status | Blocker |
|------|--------|---------|
| Epic 2 — Post-launch hardening (UptimeRobot, analytics, background workers) | backlog | Blocked on Render deploy (5.9) |
| Epic 3 — Data quality Phase 2 (installment price fix, thin geo, store enrichment) | backlog | Blocked on Epic 2 analytics findings |
| Epic 4 — Multi-voucher network expansion (תו הזהב, נופשונית) | backlog | Hard-blocked: do not start until Epics 1+2 complete and stable |

### Architecture decisions that constrain future epics

- The v1 `/api/chat` endpoint must be kept alive until cost-guard triggers are measured in production and confirmed safe to change.
- `inference.py` (background attribute extraction via `asyncio.create_task()`) is untested under load; Epic 2 should add load tests.
- The `agent_traces` table (added W4) has data but no dashboard; Epic 2's analytics story should surface it.

---

## 8. Retro Status / Sign-Off

**Draft status:** This retrospective was drafted from sprint artifacts and git history. The following items are marked "not recorded" due to absent data:

- Real-user test results (W5 soft-launch never ran)
- W7 manual validation results (template not filled in)
- Cost-guard trigger rate and actual session cost in production (deploy not yet live)
- Test suite count at individual story boundaries W2–W7 (only W8 starting point of 141 is recorded)
- W9 (5.9) status in artifacts — described as "PR #10 in review" in the task brief but no story file or sprint-status entry exists beyond `backlog`

**Sign-off placeholder:**

| Item | Status |
|------|--------|
| Epic reviewed by Barak | [ ] |
| Story 5.7 manual validation completed | [ ] |
| Stories 5.8 + 5.9 merged to master | [ ] |
| epic-5-retrospective: `done` set in sprint-status.yaml | [ ] |

---

*Drafted by Claude Sonnet 4.6 from: `sprint-status.yaml`, `findme-v2-sprint-plan.md`, per-story spec files 5.7/5.8, `deferred-work.md`, `tests/eval/baselines/` (6 files), and `git log --oneline master | head -80`.*
