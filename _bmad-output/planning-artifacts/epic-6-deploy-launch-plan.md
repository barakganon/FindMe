# Epic 6 — Production Deploy + Soft Launch

> Drafted 2026-06-14 (autonomous). Follows Epic 5 (agentic refactor, merged to master).
> Epic 5 made the backend deploy-ready (cost guard, rate limits, body guard, `render.yaml`,
> port-agnostic `scripts/start.sh`) but **no live deploy ran** — that deferred W5 work is
> the spine of this epic. Goal restated from the v2 wall-list: *"BuyMe holder, 3 turns,
> taps a link, trusts it."*

## Why this epic, why now

The v2 agentic loop works and is hardened (254 tests green). The single biggest piece
of unrealized value is that **nobody outside the laptop can use it.** Everything else
(Epics 2/3/4 — monitoring depth, data-quality phase 2, multi-voucher) is downstream of
having real traffic. This epic ships v2 to a small real audience and instruments it.

**Hard gate before public:** the v2 soft-launch kill gate from the original plan —
*"Do 5 friends complete a 3-turn conversation?"* — was never run because there was no
deploy. Epic 6 finally runs it.

## Scope (in)

| # | Story | Summary | Depends on |
|---|-------|---------|-----------|
| 6.1 | **Render backend deploy** | Apply the `render.yaml` blueprint; provision external pgvector Postgres + Render Key Value (Redis); wire secrets; migrate schema (alembic 0008); smoke-test `/api/chat/v2/stream` in prod. | render.yaml (done) |
| 6.2 | **Frontend rebuild + deploy** | The deferred W5 ChatInterface rebuild (conversation + Tray + streaming state line) finished and deployed (Vercel/Render static); CORS origins locked to the prod frontend; prod `X-Session-ID` wiring. | 6.1 |
| 6.3 | **5.7 manual validation + anon-chip fix** | Walk the 5.7 manual checklist against the deployed app; resolve the flagged anon `👦 ילד 3` chip (decide: extract child-age into derived_facts, or scope the chip to logged-in only and update the spec). | 6.2 |
| 6.4 | **Monitoring + alerts** | UptimeRobot on `/health` (Epic 2.1); structured error logging review; a daily cost-guard summary (did the $20/day or any session $0.50 cap ever trip?). | 6.1 |
| 6.5 | **Soft-launch + first-week analytics** | Invite ~5–10 BuyMe holders (the existing invite allowlist gates access); run the 3-turn kill gate; capture the first-week analytics pass (Epic 2.2) — intent distribution, tool-call success, latency p95, conversations-to-link-tap. | 6.2, 6.4 |

## Scope (out / explicitly deferred)

- Epic 3 data-quality phase 2 (installment-price fix, thin geo categories, chain rollout) —
  order it by what the 6.5 analytics actually surface, not by guess.
- Epic 4 multi-voucher (תו הזהב / נופשונית) — hard-blocked until v2 is stable in prod.
- The Epic 5 deferred-work items (cost-cap TOCTOU, streaming partial-cost, chunked-body
  bypass) — revisit only if 6.4 monitoring shows abuse.

## Kill gates

| Gate | Question | Failure trigger |
|------|----------|-----------------|
| End 6.1 | Does `/api/chat/v2/stream` return a real Hebrew answer in prod against the live catalog? | If no → fix infra/secrets before any frontend work. |
| End 6.2 | Can an anonymous browser visitor complete one search end-to-end on the deployed site? | If no → CORS / session / streaming wiring bug; block 6.5. |
| End 6.5 | Do ≥4 of 5 invited friends complete a 3-turn conversation and tap a result link? | If no → do NOT open public; iterate on prompts/UX (revive a W6-style prompt-iteration loop). |

## Risks / unknowns to resolve early

- **pgvector hosting.** Render Postgres lacks pgvector (documented in 5.9 deploy notes).
  6.1's first task is choosing the provider (Supabase / Neon / self-managed) and confirming
  the 135,865-row embedded catalog imports + queries at acceptable latency.
- **Cold-start latency.** Render free/standard dynos sleep; first-request latency may hurt
  the "thinking…" experience. Measure in 6.1; consider a keep-warm ping in 6.4.
- **Deploy authority.** A live deploy spends money and is outward-facing. **Not yet
  explicitly authorized** — confirm with Barak before executing 6.1, even under autonomous mode.

## Suggested sequence

6.1 → (6.2 ∥ 6.4) → 6.3 → 6.5. 6.4 can start as soon as 6.1's URL exists.

## This epic's first concrete action

Decide the **pgvector Postgres provider** and stand up an empty instance — everything in
6.1 blocks on it. Draft a one-pager comparing Supabase vs Neon vs Render-private on
pgvector support, price, region (eu-central for Israel latency), and connection limits.
