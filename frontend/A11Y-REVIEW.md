# Accessibility Review — Chat UI

Scope: `ChatInterface.tsx` (+ `ResultCard`, `StoreCard`, `ProfileDrawer`, `SearchBox`).
Hebrew-first RTL app — `dir="rtl"` / `lang="he"` at root confirmed correct.

## Fixes applied

- **`ChatInterface.tsx`**
  - Streaming status line: added `role="status" aria-live="polite" aria-atomic="true"` so screen readers announce "חושב…" / "מחפש בקטלוג…" etc. as they change, instead of silently updating.
  - Profile/avatar header button: added `aria-label` (mirrors existing `title`) so it's announced even when tooltips aren't read.
  - Message textarea: added `aria-label="הודעה לצ'אט"` (placeholder alone isn't a reliable accessible name).
  - Registration form inputs (name/email/password): added `aria-label` matching each placeholder.
  - Mobile tray toggle button: added `aria-expanded`/`aria-controls` wired to the items panel (`id="tray-items-panel"`) so its open/closed state is exposed.
- **`ProfileDrawer.tsx`**
  - Drawer: added `role="dialog" aria-modal="true" aria-label="פרופיל משתמש"`.
  - Backdrop: added `aria-hidden="true"` (decorative click-to-dismiss layer).
  - Escape key now closes the drawer (was mouse-only).
  - Close (`✕`), confirm (`✓`), delete (`✗`) icon buttons: added `aria-label` (previously only `title`, which isn't consistently exposed to assistive tech).
- **`SearchBox.tsx`**
  - Input: added `aria-label` matching its placeholder (legacy/unused-in-chat component, fixed for parity since it was in scope).

## Recommendations deferred (not applied — risk of layout/behavior change or judgment call needed)

1. **Focus management on drawer open/close.** Opening `ProfileDrawer` doesn't move focus into it, and closing doesn't restore focus to the trigger button. A full fix needs a focus-trap and a stored "return focus" ref — more than a one-line aria attribute, and risks interaction bugs if done hastily. Recommend a follow-up ticket.
2. **Message list live-region.** Didn't add `aria-live` to the full scrolling messages container — with product/store result grids inside each bubble, a live region would cause screen readers to re-announce large chunks of card content on every turn (noisy, arguably worse UX than silence). A better fix is a dedicated visually-hidden "new message from FindMe" live region that only announces the new text bubble, not the results grid — needs product input on wording, so left as a recommendation.
3. **Memory chips (`chipStrip`) contrast/semantics.** Chips are rendered as `<span>` (correct, since they're non-interactive display-only badges — no `onClick`), but the confirmed/unconfirmed color pair (`bg-blue-100`/`bg-blue-50` text `blue-800`/`blue-700`) should be spot-checked against WCAG AA contrast on final backgrounds; deferred since it's a visual/design call, not a markup fix.
4. **`ResultCard`/`StoreCard` distance/price "card as link" pattern.** The whole card is a `<div>` with a separate `<a>` "לרכישה ←" link at the bottom — keyboard/AT users can already tab to the real link, so this is compliant, but larger touch/click target coverage (make the whole card the link) is a design decision outside "safe fix" scope.
5. **Suggestion chips / registration prompt focus-in.** These appear conditionally mid-conversation; no fix applied to auto-focus them since it could yank keyboard/scroll focus away from where the user is reading, which is arguably worse. Left as-is.
