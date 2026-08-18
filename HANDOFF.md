# HANDOFF — iOS Semantic Token System (C1), Task 1

## 1. Objective
Implement Task 1 (Wave 1 foundation) of the approved plan `.omo/plans/ios-native-mobile-ui.md`: define the iOS semantic token system in `src/podcast_transcriber/web/static/style.css` — iOS colors (both `prefers-color-scheme` schemes), spacing scale, and Dynamic Type scale — remapping existing `:root` custom properties to iOS semantics. Token DEFINITION only; component-rule refactor is Task 2.

## 2. Constraints
- CSS-only change. NO Python edits, NO templates/base.html/sw.js edits, NO routes/behavior/worker/auth/DB changes, NO new deps, NO CDNs, NO frameworks, NO icon/image artwork.
- NO Android/Material idioms. Accent = systemBlue (`--ios-tint`), old brand purple `#8b7cf6` is DROPPED (plan D5).
- Keep `aria-*` and semantic HTML intact (don't touch HTML).
- Both dark AND light must render cleanly (no dark-only regression).
- Do not weaken/disable/bypass existing tests. `python -m pytest tests/test_web.py -q` must stay green (131 tests).
- Do NOT refactor component rules in this task — T2 adopts the tokens. Task 1 is token layer only.
- Commit after verification, conventional style, matching repo history. NEVER commit `.omo/` workflow state.
- Per `.superpowers/sdd/task-1-brief.md`: write report to `.superpowers/sdd/task-1-report.md`; reply Status + commit SHA + test summary + concerns + report path.

## 3. Plan & progress
Plan: `.omo/plans/ios-native-mobile-ui.md` (C1 at line 25; D4/D5; Scope/Must NOT lines 33–41; success criteria lines 97–100). Findings/why: `.omo/drafts/ios-native-mobile-ui.md:33` (old `:root` "NOT iOS-semantic: custom hex palette + purple accent #8b7cf6").

Progress:
- [DONE] Rewrote `.superpowers/sdd/task-1-brief.md` to the new C1 task brief.
- [DONE] Implemented token system in `style.css` working tree (uncommitted):
  - `:root` = dark values (no-preference fallback renders existing dark look).
  - `@media (prefers-color-scheme: light)` block overrides iOS tokens + semantic status colors.
  - `@media (prefers-color-scheme: dark)` block re-asserts dark values.
  - Dynamic Type tokens: display 2.125rem (34), headline 17 semibold, body 17, callout 16, subhead 15, footnote 13, caption 12.
  - Spacing: `--space-1..6` = 4/8/12/16/24/32px.
  - Legacy aliases (`--bg`, `--bg-soft`, `--card`, `--card-2`, `--border`, `--text`, `--muted`, `--accent`, `--accent-ink`, `--ok/warn/err/pending/running`, `--text-*`, `--sp-*`) remapped to the semantic tokens so component rules keep working until T2.
- [NOT DONE] Verification (tests, compileall, CSS brace-balance). [NOT DONE] Commit. [NOT DONE] `task-1-report.md`.

## 4. Repository state
- Branch: `master`, tracking `origin/master`. HEAD: `94c2cb8` "UX review: apply all high + medium impact fixes (H1-H15, M1-M19)".
- `git status`: clean except:
  - `M .superpowers/sdd/task-1-brief.md` — brief rewritten for the C1 token task.
  - `M src/podcast_transcriber/web/static/style.css` — token system implemented.
  - `?? .DS_Store`, `?? .omo/` — untracked; `.omo/` is workflow state, DO NOT commit.
- `git diff --stat`: `task-1-brief.md` +44/−386; `style.css` +91/−24. Style diff is confined to the `:root` block and new media queries (lines ~1–99); component rules untouched.

## 5. Files touched
- `.superpowers/sdd/task-1-brief.md` (modified) — replaced old UX-review-fixes brief with the iOS Semantic Token System (C1) task brief (scope, constraints, acceptance criteria, QA, commit/report instructions).
- `src/podcast_transcriber/web/static/style.css` (modified) — added iOS semantic color tokens (dark default + light/dark media queries), Dynamic Type scale, spacing scale; remapped legacy aliases; dropped purple `#8b7cf6`.
- `.superpowers/sdd/task-1-report.md` (pending) — not yet written; required by the brief.
- Untracked and must NOT be committed: `.DS_Store`, `.omo/`.

## 6. Tests run
- NONE run yet this session. Required by acceptance criteria:
  - `python -m pytest tests/test_web.py -q` — expect all 131 tests pass.
  - `python -m compileall src/podcast_transcriber` — expect exit 0.
  - Quick CSS brace-balance check (compileall doesn't cover CSS). A browser render of both schemes is optional; if skipped, report that CSS was not runtime-verified.

## 7. Unresolved issues
- Verification not yet executed (tests/compileall/CSS parse) — do this before committing.
- Confirmed no `#8b7cf6` remains in the diff; but grep the whole CSS for stray old values before committing.
- Consider whether light-mode contrast of `--ios-separator: rgba(198,198,200,0.8)` and `--accent-ink: #ffffff` (buttons) holds in the light scheme — visual sanity check recommended.

## 8. Decisions made
- Dark-first fallback: `:root` holds dark values (matches "default should follow the dark-first existing design"); light applied via media query; dark re-asserted under its own media query (per brief D4).
- Legacy aliases remapped via `var()` instead of duplicating raw values, so existing component rules (lines ~121–341) render correctly with zero changes until Task 2 adopts tokens directly.
- Accent dropped to systemBlue `#0A84FF` (dark) / `#007AFF` (light); semantic status colors now iOS system values (`#30C759`/`#FF9F0A`/`#FF453A`) instead of the old palette.
- `--accent-ink` set to `#ffffff` (was `#17141f` for the purple accent).

## 9. Next action
Run the two acceptance commands and a CSS brace-balance check, fix anything that fails, then commit (conventional, e.g. `style(web): iOS semantic token system (colors, spacing, dynamic type)`), write `.superpowers/sdd/task-1-report.md` per the brief's Report section, and report back Status + SHA + test summary + concerns. Suggested sequence:
1. `python -m pytest tests/test_web.py -q`
2. `python -m compileall src/podcast_transcriber`
3. CSS brace-balance sanity check (e.g. node/python counter or browser render)
4. `git add src/podcast_transcriber/web/static/style.css` (+ task brief if intended) then commit; leave `.omo/` and `.DS_Store` untracked
5. Write `.superpowers/sdd/task-1-report.md`
