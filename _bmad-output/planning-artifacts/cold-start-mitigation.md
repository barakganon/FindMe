# Cold-Start Mitigation — Analysis

> Drafted 2026-07-11 (autonomous, pre-launch). Referenced by Epic 6's risk list
> ("Cold-start latency... measure in 6.1; consider a keep-warm ping in 6.4") and by
> Story 2.1 (UptimeRobot monitoring), which needs this recommendation before picking
> a keep-warm interval. This is analysis, not an implementation — no code changes.

## The problem

`epic-6-deploy-launch-plan.md` flags: "Render free/standard dynos sleep; first-request
latency may hurt the 'thinking…' experience." The v2 chat flow already has a visible
"thinking…" state during the agentic loop (`api/agent/`, streamed via SSE from
`POST /api/chat/v2/stream`) — that's *already* a multi-second wait for a normal warm
request (tool calls + LLM round-trips). A cold dyno stacks Render's spin-up time
(commonly 30s–1min+ on free tier, several seconds on paid tiers with persistent
disk/image caching) **in front of** that existing wait. For a first-touch anonymous
user during the 6.5 soft launch, that's the difference between "an answer arrived
in ~3s" and "nothing happened for 40s, did it break?" — a real risk to the "3 turns,
taps a link, trusts it" kill gate.

`render.yaml`'s intended target is `standard` plan (comment: "1 GB RAM / 10 GB
storage — sized for ~135k vector(768) rows"), but the currently-*running*
`findme-api` service is noted as `oregon/free` (per `6-1-deploy-status.md`,
referenced in `render.yaml`'s "Intended-vs-running note"). **Free-tier Render web
services sleep after a period of inactivity** and cold-start on next request — this
is the concrete mechanism, not a hypothetical.

## Options

### 1. Keep-warm ping (external, e.g. via UptimeRobot)
Hit `/health` on an interval shorter than Render's sleep timeout, so the dyno never
goes idle long enough to sleep.
- **Pros:** zero infra change, zero cost (UptimeRobot free tier), reuses the
  monitor already being stood up for Story 2.1.
- **Cons:** doesn't work at all on some Render plan tiers (free-tier services can
  still sleep regardless of external pings on certain configurations — verify
  against Render's current docs at deploy time, this detail drifts). Even where it
  works, it's a workaround for a limit, not a fix — a burst of real users right
  after a ping-miss window still eats the cold-start once.
- **Cost:** $0.

### 2. Render min-instances / "always on"
Configure the service to keep at least one instance running at all times — no
scale-to-zero.
- **Pros:** eliminates cold-start entirely, deterministic.
- **Cons:** requires a paid plan tier that supports min-instances (free tier does
  not); ongoing monthly cost regardless of traffic.
- **Cost:** plan-dependent — `render.yaml`'s intended `standard` plan for the *web
  service* isn't priced in the file (only the DB/KV plans are commented with
  price); verify current Render pricing for a standard web service with
  always-on at decision time, not from a stale number here.

### 3. Plan bump (paid tier)
Move off free tier generally — paid tiers on Render have faster cold boots even
without min-instances (better base image caching), and unlock min-instances as
an option (folds into option 2).
- **Pros:** addresses cold-start and gives headroom for the ~135k-row pgvector
  workload the DB is already sized for on `standard`.
- **Cons:** direct recurring cost; per CLAUDE.md, live-deploy spend is
  Barak-gated — this is exactly the kind of decision that needs explicit
  sign-off, not silent adoption.
- **Cost:** recurring, plan-dependent.

## Recommendation

**Start with Option 1 (keep-warm ping) for the soft launch (Story 2.1), because
it's free and already piggybacks on infrastructure being stood up anyway.** It
won't fully eliminate cold-start (a ping-miss window followed by a burst of real
first-touch users can still hit it), but it covers the common case at zero
incremental cost — appropriate for a 5–10-person soft launch where traffic is
sparse and predictable enough that ping cadence can realistically stay ahead of it.

**Escalate to Option 2/3 (min-instances / plan bump) only if:**
- the 6.5 soft-launch kill gate ("≥4 of 5 friends complete a 3-turn conversation
  and tap a result link") fails or is marginal, **and** first-request latency
  (measurable via `agent_traces.total_latency_ms` for each session's first turn,
  see `2-2-first-week-analytics.md`) is the identified cause — not another factor
  (prompt quality, search relevance, etc.), or
- traffic grows past what a 5-min keep-warm ping can keep ahead of.

Do not pre-emptively spend on min-instances before the soft launch shows it's
needed — Epic 6 already flags this as Barak-gated spend, and the whole point of
2.2's first-week analytics is to let real data (not a guess) drive Epic 3/4
prioritization; the same principle applies here.

## Open verification items (resolve at Story 2.1 execution time, not now)

- Confirm current Render free-tier sleep timeout and whether external pings
  reliably prevent it (Render's own docs/behavior may have changed since this
  was last checked).
- Confirm actual `standard`-plan web-service pricing before treating Option 3 as
  a real menu item for Barak to approve.
