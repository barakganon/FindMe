# Story 2.1 — UptimeRobot Monitoring

> Drafted 2026-07-11 (autonomous, pre-launch). Wiring is **blocked on a live prod URL**
> (Story 6.1 backend deploy). The runbook for this already exists at
> `_bmad-output/implementation-artifacts/6-4-monitoring-setup.md` §1 — this story is
> the ticket to actually *execute* that runbook once the URL exists, plus the
> keep-warm mitigation that runbook flagged but didn't implement.

## Why this epic, why now

Epic 6.4 shipped the cost-summary endpoint and wrote the UptimeRobot runbook, but
explicitly deferred account setup ("no UptimeRobot account created... no production
URL exists"). Epic 2 (post-launch hardening) is where that deferred setup actually
happens, once 6.1 gives us a URL to point at. Cold-start on Render free/standard
dynos (flagged as a risk in the epic-6 plan) makes this more than uptime paging —
the keep-warm ping doubles as UX mitigation for the "thinking…" screen. See
`_bmad-output/planning-artifacts/cold-start-mitigation.md` for the full analysis.

## Scope (in)

- Create UptimeRobot account; add HTTP(s) monitor on `GET /health` (5-min interval)
  per the existing runbook (`6-4-monitoring-setup.md` §1). `/health` has no DB/Redis
  dependency (`api/main.py:123`) — correct choice for liveness, don't change it.
- Alert routing: email at minimum; Slack webhook if available at launch time.
- Keep-warm ping: a second monitor (or the same one, tuned) hitting `/health` at an
  interval short enough to keep the Render dyno warm between real user requests —
  concretely, whatever interval the chosen Render plan's sleep timeout requires
  (verify against the actual plan in `render.yaml` at deploy time; free-tier dynos
  sleep after ~15 min idle).
- Optional secondary keyword monitor on `/api/admin/health/detailed` (warning-only,
  not paging) per the existing runbook — carry over as-is, no changes needed.
- Document the final monitor config (URLs, intervals, alert contacts) in
  `6-4-monitoring-setup.md` §4, replacing the "not set up yet" bullets with what's
  actually live.

## Scope (out)

- Cost-guard monitoring (`/api/admin/cost-summary` polling) — already speced in
  `6-4-monitoring-setup.md` §2, not this story's job to re-derive.
- Log-based alerting (Render → Papertrail/Logtail) — `6-4-monitoring-setup.md` §3
  already covers this; only revisit if plain Render log tab proves insufficient
  post-launch.
- Paid Render plan bump purely for uptime reasons — that's a cost decision for
  `cold-start-mitigation.md`'s recommendation, not this story.

## Dependencies

- **Hard block:** Story 6.1 (Render backend deploy) — no prod URL, no monitor.
- Soft dependency: `cold-start-mitigation.md` recommendation should land before
  picking the keep-warm interval, so the interval is chosen deliberately rather
  than guessed.

## Acceptance criteria

1. UptimeRobot monitor exists, pointed at the real prod `/health` URL, 5-min
   interval, with at least one working alert contact (verify by triggering a
   test alert, not just by saving the config).
2. A keep-warm ping is live and its interval is justified against the deployed
   Render plan's actual sleep behavior (not copy-pasted from a guess).
3. `6-4-monitoring-setup.md` is updated to reflect what's actually wired (no more
   "not set up yet" placeholders for the uptime piece).
4. One observed alert-and-recovery cycle (even a manual restart test) to confirm
   the alert path works end-to-end, not just that the monitor is green.

## Kill gate

If Render's plan/region for the live service can't sustain a keep-warm ping without
meaningfully raising cost (e.g. paid-plan bump required for min-instances), stop and
surface the trade-off in `cold-start-mitigation.md` rather than silently absorbing
the cost — this is a Barak-gated spend decision per CLAUDE.md norms.
