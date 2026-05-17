# FindMe v2 — Agentic Conversation Refactor — Sprint Plan

*Version 1.0 · 2026-05-15 · Owner: Barak · Re-read weekly*

## Thesis

We are rebuilding FindMe's chat layer from a one-shot **intent-parser → search → composer** pipeline into an **agentic conversation loop** — an LLM that calls tools (search_products, search_stores, get_user_context, recall_history, clarify), holds multi-turn state in Redis, and streams its thinking to the user. Target: **soft-launch to 5 friends end of Week 5, public-ready end of Week 11.** "Done" means a Hebrew speaker with a BuyMe card can have a 3-turn conversation that ends with them tapping a store link they trust. In parallel, we audit the catalog against 8 dimensions until it is **agent-grade**: strict enough that the agent can make a definitive claim without lying.

## The Four Commitments

| Agent | Deliverable |
|---|---|
| 🛠 **Amelia** | 11-week sprint with eval harness as the spine and a hard kill-gate at end of W1 |
| 🏛 **Winston** | Provider-agnostic agent loop; keep the SQL/embeddings/JWT, rewrite chat.py + ChatInterface.tsx |
| 🎨 **Sally** | 5 canonical scenarios + two-column UI with memory chips, Tray, streaming state line |
| 🔬 **Mary** | Data audit across 8 dimensions, P0/P1/P2 severity, ship-gate = all P0 pass |

## 11-Week Calendar

| Week | Theme | Single Deliverable | Gate Question |
|------|-------|--------------------|---------------|
| **W1** | Eval harness | `tests/eval/golden_queries.yaml` + `runner.py` + baseline | Does Gemini-2.5-flash emit Hebrew tool-calls correctly? |
| **W2** | Agent thin slice | `api/agent/loop.py` + `search_products` tool, feature-flagged `/api/chat/v2` | Is the eval harness scoring meaningfully? **Kill-gate: <80% tool-call accuracy → swap to Claude Sonnet 4.7 in 1 day.** |
| **W3** | Tools + memory | 4 more tools + Redis session memory (2h TTL) | Can the agent recall the last turn? |
| **W4** | Audit fixes + telemetry | Brand backfill (727 nulls), city canonicalizer, chain detection (migration 0009), `agent_traces` table | Does multi-turn coherence hold with state? |
| **W5** | SSE + soft launch | Streaming + invite-only deploy to 5 friends, cost guard (50¢/session, $20/day) | Do real humans complete a 3-turn convo? |
| **W6** | Prompt iteration | Push eval from ~75% → 90%+ | Are we above 90% on the golden set? |
| **W7** | UI polish | Conversation repair + memory chips | Does the mind-changer scenario survive? |
| **W8** | Tests | 40+ tests rewritten around tools | Is the harness green on CI? |
| **W9** | Cost + deploy hardening | Caching, batching, rate limits | Can a stranger break it? |
| **W10–11** | Buffer | — | Ship or extend? |

## Architecture: Keep / Rewrite / Defer

| Verdict | Components |
|---------|-----------|
| ✅ **Keep — become tools** | `_embed`, `_vec_literal`, hybrid SQL, geo query, `inference.py`, Redis, JWT, schema, ResultCard, StoreCard, embedding pipeline |
| ♻ **Rewrite** | `api/routes/chat.py` (parser+composer → agent loop) · `ChatInterface.tsx` (single column → conversation + Tray with streaming) |
| ⏸ **Defer** | Admin dashboard · blanket data relabel · voice input · dark mode · language switcher |

**Provider strategy:** OpenAI-SDK shape, swap `base_url`. Lock provider **after** the W1 Hebrew tool-calling test, not before.

## UX Spec (Compressed)

**The 5 scenarios — every code change must serve one of these:**
1. **Sarah** (₪300, no plan) → ambiguous open, agent asks ONE warm clarifying question
2. **Yael** (mom of 3yo) → constraint discovery, memory chip 👦 ילד 3 glows
3. **Avi** (Sony/Bose/JBL in tray) → comparison turn, no new search
4. **Rinat** ("מסעדות ת"א כמו פעם שעברה") → memory surfacing
5. **Mind-Changer** ("אופנה → אוכל → מתנה לאמא") → repair, no restart

**Screen anatomy:**

```
┌──────────────────────────────────────┬──────────────────┐
│  👦 ילד 3   💰 ₪300   📍 ת"א          │                  │
│  ────────── memory chip strip ────── │     TRAY         │
│                                       │   (shortlist     │
│  [agent bubble — streaming]           │    persists      │
│  חושב… → מחפש בקטלוג… → מסנן…         │    across whole  │
│                                       │    conversation) │
│  [user bubble]                        │   drag · swipe   │
│  [agent bubble + cards]               │   · tap          │
│                                       │                  │
│  ┌─────────────────────────────────┐ │                  │
│  │ @ reference · text input        │ │                  │
│  └─────────────────────────────────┘ │                  │
└──────────────────────────────────────┴──────────────────┘
  60% chat                                40% tray
  (stacks on mobile)
```

**Voice (2 sentences):** Brisk Tel Aviv friend who knows every store and has opinions. Warm not gushy, funny not cringe, Hebrew first, uses "בוא/בואי", never "אשמח לעזור".

**NOT designing in v1 — read this when tempted:**
> ✖ voice input · ✖ dark mode · ✖ language switcher · ✖ share-conversation · ✖ save-as-PDF · ✖ emoji reactions · ✖ avatars beyond initials · ✖ animations >200ms · ✖ onboarding tour · ✖ tutorial bubbles · ✖ settings page

## Data Audit at a Glance

| # | Dimension | Target | Severity |
|---|-----------|--------|----------|
| 1 | Price truthfulness | <0.5% suspect rows | P0 |
| 2 | Availability freshness | median staleness ≤14 days | P0 |
| 3 | Brand attribution | null + mis-attr <3% | P0 |
| 4 | Category accuracy | LLM-judge on 200 stratified samples | P1 |
| 5 | Chain coverage | pg_trgm clusters (expect 20–40 hidden) | P1 |
| 6 | City normalization | canonical map coverage | P1 |
| 7 | Embedding relevance | P@10 ≥0.7 on 50 canonical queries | P0 |
| 8 | Duplicate & image hygiene | <2% dupes, >60% images | P2 |

**Ship-gate:** all P0 pass + ≤2 P1 open with documented mitigations. Lives in `_bmad-output/data-audit-v1.md`. Cost: 6–8 engineering days, slotted into W2–W4 parallel to the eval harness.

## The Kill Gates

| Gate | Question | Failure trigger |
|------|----------|-----------------|
| **End W1** | Does Gemini emit Hebrew tool-calls correctly? | If raw accuracy looks weak → flag, decide at W2 |
| **End W2** | Tool-call accuracy ≥80% on Gemini-2.5-flash? | **<80% → swap to Claude Sonnet 4.7 in 1 day** |
| **End W4** | Does multi-turn coherence hold with Redis state? | If no → freeze tool surface, fix memory, slip 1 week |
| **End W5** | Do 5 friends complete a 3-turn conversation? | If no → extend W6 prompt-iteration before public push |

## This Week's Three Concrete Actions

1. 🛠 **Amelia → write `tests/eval/golden_queries.yaml`** — 30 Hebrew + 10 English queries, each with expected intent + expected tool sequence.
2. 🎨 **Sally → write Canonical Scenarios doc** — 5 scenarios on one page, pinned above laptop.
3. 🔬 **Mary → run first audit SQL** — rank installment-bug stores in one query, paste output into `_bmad-output/data-audit-v1.md`.

(Winston's work is structural — already encoded in the calendar above. No standalone "this week" action.)

## The Wall-List

> Read these when you're tempted to add scope.

- The eval harness is the spine. No code ships without a test in the golden set.
- The 5 scenarios are the spec. If a change doesn't serve one, defer it.
- Keep the SQL, the embeddings, the JWT. Rewrite only chat.py and ChatInterface.tsx.
- Provider is locked after W1, not before. Don't pick Claude on vibes.
- All P0 audit dimensions must pass before the public launch. P1 can have mitigations.
- Cost guard is non-negotiable: 50¢/session, $20/day, circuit-breaks to old `/api/chat`.
- Memory chips, Tray, streaming state line. Everything else is decoration.
- "אשמח לעזור" is banned. We are not a call center.
- If W5 soft-launch fails, slip the public date. Do not ship a broken first impression.
- Done means: BuyMe holder, 3 turns, taps a link, trusts it.

---

*A note from Paige to Barak — this doc is your compass when the codebase is foggy: re-read it every Monday morning before you open your editor, and once more whenever you catch yourself building something that isn't in the calendar. Update it at the end of each week: cross off the gate you cleared, mark the next one in bold, and adjust the wall-list only when reality teaches you something the plan didn't know.*
