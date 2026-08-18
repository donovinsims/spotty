# ios-native-mobile-ui - Work Plan

## TL;DR (For humans)
<!-- Fill this LAST, after the detailed plan below is written, so it summarizes the REAL plan. -->
<!-- Plain English for a non-engineer: NO file paths, NO todo numbers, NO wave/agent/tool names. -->

**What you'll get:** <fill last - deliverables in human terms, 1-2 sentences>

**Why this approach:** <fill last - the one or two load-bearing decisions and why>

**What it will NOT do:** <fill last - 1-3 plain lines mirroring Must NOT have>

**Effort:** <Quick | Short | Medium | Large | XL>
**Risk:** <Low | Medium | High> - <one-line driver>
**Decisions to sanity-check:** <fill last - the few choices worth a human glance>

Your next move: <fill - e.g. approve, or run a high-accuracy review>. Full execution detail follows below.

---

> TL;DR (machine): <1 line - effort, risk, deliverables>

## Scope
### Must have
- **C1 — iOS semantic token system.** Remap `:root` custom properties in `src/podcast_transcriber/web/static/style.css:3-30` to iOS semantics, both appearances: background (`--ios-system-background` #FFFFFF dark #000000, `--ios-secondary-system-background` #F2F2F7 / #1C1C1E, `--ios-grouped-background`), text (`--ios-label` #000000/#FFFFFF, `--ios-secondary-label` #3C3C4399/#EBEBF599, `--ios-tertiary-label`), separators (`--ios-separator` #C6C6C8CC/#38383A66, `--ios-opaque-separator`), fills (`--ios-system-fill` #78788033/#78788052, `--ios-secondary-system-fill`), and accent → iOS systemBlue/Indigo per D5 (`--ios-tint` #007AFF dark #0A84FF, indigo #5856D6/#5E5CE6). Both schemes under `@media (prefers-color-scheme: light|dark)` per D4. Add iOS spacing scale (4/8/12/16/24/32) and iOS Dynamic Type scale (Large Title 34/28, Title 1-3, Headline 17 semibold, Body 17, Callout 16, Subhead 15, Footnote 13, Caption 12) as tokens. Refactor every component rule to consume tokens — NO raw px for layout/type anywhere.
- **C2 — Layout & safe areas.** `.container`, `.topbar`, and (new) `.tabbar` pad with `env(safe-area-inset-top/right/bottom/left)`; correct `viewport-fit=cover` is already in `base.html:5`. Clean in both `display-mode: standalone` (PWA) and browser tabs on iPhone; desktop Safari unchanged.
- **C3 — iOS navigation.** Blur material on topbar (`backdrop-filter: blur(20px) saturate(180%)`, translucent bg); large-title pattern on New/Jobs pages; **mobile bottom tab bar (New / Jobs, ~49pt, blur, safe-area-bottom) at `max-width: 560px` AND `display-mode: standalone`** per D6; chevron back links (`‹ Back`-style chevron) on transcript/job-detail; `aria-current` nav state preserved.
- **C4 — Component restyle to iOS spec.** Buttons: tinted (`--ios-tint` bg at 15% alpha, tint text) + filled (tint bg, white text) styles, 44pt min-height, radius 10-12, no uppercase; inputs: `--ios-secondary-system-background` + `--ios-system-fill` field style; cards → iOS grouped-list surfaces (hairline `--ios-separator`, 10-12px radius, NO heavy drop shadow, near-flat); badges → iOS capsule pills; progress → UIProgressView-style flat track+fill, no gradient; tables → grouped iOS lists; transcript `.seg` rows → iOS inset grouped list; REMOVE Android idioms (uppercase `letter-spacing` micro-labels in `style.css:141-147, 268-271` → plain iOS caption/footnote).
- **C5 — Microinteractions.** Tap feedback `scale(0.97)` with `transition: transform .18s cubic-bezier(.4,0,.2,1)` on `.btn`/`.topnav a`/`.tabbar a`; HTMX swap enter animation (`opacity 0→1, translateY(8px→0)`, ~300-400ms) for `.card`, `.seg`, `.status-card`, `#episode-results` via `hx-swap` + CSS; progress-fill easing `cubic-bezier(.4,0,.2,1)`; status badge pop-in. ALL motion respects `@media (prefers-reduced-motion: reduce)` → disable.
- **C6 — PWA iOS integration.** In `base.html` head: `apple-mobile-web-app-capable`, `apple-mobile-web-app-status-bar-style` (black-translucent), `apple-mobile-web-app-title`, 180px `apple-touch-icon` (reuse existing `/static/icon-192.png` per open assumption — Safari scales), splash/startup image handling; `display-mode: standalone` CSS rules; add any new static asset to `sw.js` SHELL (`pt-shell-v3` list at `sw.js:4-9`).
- **C7 — Verification.** Update `docs/iphone-test-plan.md` for the new UI; run the objective ios-hig-design Quick Diagnostic (10-point rubric from `/Users/forex/.agents/skills/ios-hig-design/SKILL.md`) on iPhone Safari → **≥ 9/10**; full regression: `pytest` (131 tests incl. `test_web.py` render suite) + `python -m compileall -q src` green after every wave; desktop Safari must stay usable (no dark-only regression).

### Must NOT have (guardrails, anti-slop, scope boundaries)
- NO image generation / AI design-image phase (user explicitly excluded).
- NO new app-icon artwork (reuse existing PNG assets only).
- NO external CDNs, NO new JS/CSS frameworks, NO new Python deps.
- NO route/behavior/worker/auth/rate-limit changes; NO DB/schema changes. Zero Python edits.
- NO Android/Material styling: no uppercase micro-labels, no ripple effects, no Android nav patterns.
- NO hamburger menus. NO desktop-first layouts.
- NO `as any`/silent fallbacks; keep `aria-*` attributes and semantic HTML intact.
- NO dark-only regression: desktop Safari and light mode must both render cleanly.

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after + existing framework (pytest render suite). No new Python code → 131 existing tests must stay green; add render assertions in `tests/test_web.py` ONLY where template markup changes demand it. CSS/HTML validated by browser QA + static checks.
- Evidence: .omo/evidence/task-<N>-ios-native-mobile-ui.md (attemptDir = currentAttemptDir from 'omo ulw-loop status --json', .omo/evidence/ulw/<session>/<goalId>/a<attempt>; outside ulw-loop use .omo/evidence/)
- Every todo carries QA scenarios with exact invocation; final wave runs `pytest -q`, `python -m compileall -q src`, `pt doctor`, and iPhone Safari manual pass per `docs/iphone-test-plan.md`.

## Execution strategy
### Parallel execution waves
> Target 5-8 todos per wave. Fewer than 3 (except the final) means you under-split.

- **Wave 1** (foundation, strictly first — everything depends on tokens): T1 token system, T2 spacing/type token adoption audit. 2 todos (must be sequential; T2 depends on T1).
- **Wave 2** (layout + nav, depends on Wave 1): T3 safe areas & standalone/browser layout, T4 nav (blur bar, large title, tab bar, chevron back). 2 todos, parallelizable with each other.
- **Wave 3** (components, depends on Wave 1, parallel with Wave 2): T5 button/input/badge/progress restyle, T6 card/table/segments/meta grouped-list restyle + remove uppercase labels. 2 todos.
- **Wave 4** (microinteractions, depends on Waves 2+3): T7 tap feedback + HTMX swap animations + progress easing + reduced-motion. 1 todo.
- **Wave 5** (PWA iOS integration, depends on Wave 2, parallel with Wave 4): T8 base.html metas + 180px icon + splash + display-mode + sw.js SHELL. 1 todo.
- **Wave 6** (verification, last): T9 ios-hig-design diagnostic ≥ 9/10 + update iphone-test-plan + full regression. 1 todo.
- **Final verification wave**: F1-F4 in parallel after ALL todos.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| T1 tokens | — | T2, T3, T4, T5, T6 | — |
| T2 type/spacing audit | T1 | T3-T8 | — |
| T3 safe areas | T1 | T7, T9 | T4, T5, T6 |
| T4 nav | T1 | T7, T8, T9 | T3, T5, T6 |
| T5 buttons/inputs/badges/progress | T1 | T7, T9 | T3, T4, T6 |
| T6 cards/tables/segments/labels | T1 | T7, T9 | T3, T4, T5 |
| T7 microinteractions | T3, T4, T5, T6 | T9 | T8 |
| T8 PWA iOS metas | T4 | T9 | T7 |
| T9 verification + regression | T2-T8 | F1-F4 | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [ ] 1. <title>
  What to do / Must NOT do: <...>
  Parallelization: Wave <N> | Blocked by: <...> | Blocks: <...>
  References (executor has NO interview context - be exhaustive): <src/path:lines>
  Acceptance criteria (agent-executable): <exact command or assertion>
  QA scenarios (name the exact tool + invocation): happy + failure, Evidence <attemptDir>/task-1-ios-native-mobile-ui.<ext>
  Commit: <Y/N> | <type>(<scope>): <summary>

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [ ] F1. Plan compliance audit
- [ ] F2. Code quality review
- [ ] F3. Real manual QA
- [ ] F4. Scope fidelity

## Commit strategy
- One commit per todo (or per logical wave), conventional style, matching repo history (check `git log --oneline` first).
- Suggested: `style(web): iOS semantic tokens` / `style(web): safe areas + bottom tab bar` / `style(web): component restyle to iOS idioms` / `style(web): microinteractions` / `feat(web): PWA iOS metas + 180px icon` / `docs(web): update iPhone test plan`.
- Never commit the plan artifact itself (.omo/ is local workflow state).

## Success criteria
- `ios-hig-design` Quick Diagnostic scores **≥ 9/10** on iPhone Safari in both standalone and browser modes.
- `pytest -q` passes (131 tests, zero regressions) and `python -m compileall -q src` exits 0.
- `pt doctor` preflight clean.
- iPhone Safari: native-feeling blur bars, large titles, bottom tab bar, chevron back, tinted iOS buttons, grouped lists, capsule badges, safe-area padding, springy tap feedback — no Android idioms, no hamburger, no heavy shadows/gradients/uppercase micro-labels.
- Light + dark both clean; desktop Safari unaffected.
- `docs/iphone-test-plan.md` updated and passable.
