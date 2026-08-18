# Task 1: iOS Semantic Token System (C1)

You are implementing Task 1 of the approved plan `/Users/forex/Spotty/.omo/plans/ios-native-mobile-ui.md` — the foundation wave (Wave 1). Everything else (T2–T8) depends on your tokens.

## Task Description

Define the iOS semantic token system in `src/podcast_transcriber/web/static/style.css`, remapping the existing `:root` custom properties (currently at `style.css:3-30`) to iOS semantics with BOTH system-matched appearances, per C1:

**Colors (both schemes):**
- Background: `--ios-system-background` #FFFFFF (light) / #000000 (dark); `--ios-secondary-system-background` #F2F2F7 (light) / #1C1C1E (dark); `--ios-grouped-background`
- Text: `--ios-label` #000000 (light) / #FFFFFF (dark); `--ios-secondary-label` #3C3C4399 (light) / #EBEBF599 (dark); `--ios-tertiary-label`
- Separators: `--ios-separator` #C6C6C8CC (light) / #38383A66 (dark); `--ios-opaque-separator`
- Fills: `--ios-system-fill` #78788033 (light) / #78788052 (dark); `--ios-secondary-system-fill`
- Accent: `--ios-tint` #007AFF (light) / #0A84FF (dark); indigo pair #5856D6 (light) / #5E5CE6 (dark). The old brand purple `#8b7cf6` is DROPPED for the iOS tint (D5).

**Appearance switching:** Both schemes live under `@media (prefers-color-scheme: light)` and `@media (prefers-color-scheme: dark)` per D4. The default (no-preference) scheme should follow the dark-first existing design — keep the current dark palette as the fallback default under `:root`, then override for light under the light media query.

**Spacing scale:** iOS spacing tokens — 4 / 8 / 12 / 16 / 24 / 32 (e.g. `--ios-space-1`…`--ios-space-6`, or equivalent clearly-named tokens).

**Dynamic Type scale:** iOS type tokens — Large Title 34/28, Title 1–3, Headline 17 semibold, Body 17, Callout 16, Subhead 15, Footnote 13, Caption 12. Keep the existing `-apple-system` font stack (renders SF Pro on iOS).

## Context

- Repo: `/Users/forex/Spotty` — Podcast Transcriber, FastAPI + Jinja2/HTMX. Presentation layer only.
- File to modify: `src/podcast_transcriber/web/static/style.css` (382 lines). Tokens currently at lines 1–90; component rules at lines ~121–341 consume the OLD raw hex/px values directly.
- This task is the token DEFINITION layer only (per plan Wave 1: "T1 token system, T2 spacing/type token adoption audit"). The component-rule refactor to consume tokens is Task 2 — do NOT refactor component rules in this task. You define the tokens; T2 adopts them. Do not touch template files, base.html, sw.js, or any Python.
- Existing type/spacing tokens were introduced in prior phases (see current `:root` block) — remap/rename them to iOS semantics rather than duplicating.

## Constraints (from plan Must NOT have + D1–D7)

- CSS-only change. NO Python edits, NO routes/behavior/worker/auth/DB changes, NO new deps, NO CDNs, NO frameworks.
- NO image generation / icon artwork.
- NO Android/Material idioms. Accent per D5 (systemBlue, not purple #8b7cf6).
- Keep `aria-*` attributes and semantic HTML intact (you shouldn't touch HTML at all).
- Both dark AND light must render cleanly (no dark-only regression).
- Do not weaken, disable, or bypass existing tests.

## References

- Plan: `/Users/forex/Spotty/.omo/plans/ios-native-mobile-ui.md` — C1 (line 25), C2–C7 for context, Scope/Must NOT (lines 33–41), Success criteria (lines 97–100).
- Current token block + component rules: `src/podcast_transcriber/web/static/style.css` lines 1–90 (tokens) and 121–341 (components — read-only for this task).
- Findings (why): current `:root` is "NOT iOS-semantic: custom hex palette + purple accent #8b7cf6, no systemBlue/label/secondaryLabel/systemBackground mapping" (`.omo/drafts/ios-native-mobile-ui.md:33`).

## Acceptance Criteria (agent-executable)

1. `python -m pytest tests/test_web.py -q` — all 131 tests pass (0 regressions).
2. `python -m compileall src/podcast_transcriber` — exits 0.
3. `:root` defines the full iOS semantic token set (colors both schemes, spacing, Dynamic Type) per C1 above.
4. `--ios-tint` is #007AFF (light) / #0A84FF (dark); old purple accent `#8b7cf6` no longer used as the accent.
5. Both `@media (prefers-color-scheme: light)` and `(prefers-color-scheme: dark)` blocks present; default no-preference fallback renders the existing dark look.
6. No raw layout/type px introduced in this task's token definitions beyond the token values themselves.

## QA Scenarios

- Happy path: run the two acceptance commands; both green.
- Visual sanity: confirm the CSS parses (no unbalanced braces) — e.g. `python -m compileall` doesn't cover CSS; a quick brace-balance check or browser render is fine if you have one, otherwise report that CSS wasn't runtime-verified.

## Commit

Yes — commit after verification, conventional style matching repo history (see `git log --oneline`). Suggested: `style(web): iOS semantic token system (colors, spacing, dynamic type)`.
Never commit `.omo/` workflow state.

## Report

Write your full report to `/Users/forex/Spotty/.superpowers/sdd/task-1-report.md` per the implementer template (what you implemented, tests run + results, files changed, self-review findings, concerns). Then reply with ONLY: Status (DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT), commit short SHA + subject, one-line test summary, concerns if any, report file path.
