# FindMe — Implementation Artifacts

This directory holds BMad story specs and the live sprint tracker.

## Files

| File | Purpose |
|---|---|
| [sprint-status.yaml](sprint-status.yaml) | Single source of truth for epic and story status. Edited by `/bmad-create-story`, `/bmad-dev-story`, and humans. |
| `<epic>-<story>-<slug>.md` | Per-story dev specs created by `/bmad-create-story`. **Stories 1.1–1.4 deliberately do not have these — see below.** |

## Stories 1.1–1.4 — read this before running BMad against Epic 1

Epic 1 (Public Launch) does **not** use per-story BMad spec files. Its
implementation spec is [`START_PROMPT.md`](../../START_PROMPT.md) at the repo
root. Phases 0–4 of that document map 1:1 to Stories 1.1–1.4 in
[epics.md](../planning-artifacts/epics.md).

This was a deliberate choice on 2026-05-03 — generating BMad story files
for ~45-min ops tasks (run a SQL UPDATE, edit two files, drive Render MCP)
adds more ceremony than value, and the deploy plan is already exhaustively
written.

### To work on a story in Epic 1

Just open `START_PROMPT.md` and execute the relevant phase. Update
`sprint-status.yaml` manually as you finish:

```yaml
1-1-pre-deploy-cleanup: ready-for-dev → in-progress → review → done
```

If you need `/bmad-dev-story` to drive Epic 1 anyway, pass START_PROMPT.md
as the explicit `story_path` when prompted.

### To work on Epics 3 or 4

Run `/bmad-create-story` normally. Those are multi-day code-heavy stories
(per-scraper investigation, new voucher network end-to-end, chain
enrichment rollout) where the upfront BMad ceremony — Dev Notes,
architecture compliance, source hints, previous-story intelligence —
genuinely prevents rabbit-holes.

## Status flow reminder

```
backlog → ready-for-dev → in-progress → review → done
```

- `backlog`: story exists only in `epics.md`, no spec file yet
- `ready-for-dev`: spec ready (or — for Epic 1 — START_PROMPT.md is the spec)
- `in-progress`: dev actively working
- `review`: implementation done, awaiting code review
- `done`: shipped to master, verified
