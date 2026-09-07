---
slug: ios-native-mobile-ui
status: approved
intent: clear
review_required: false
pending-action: F1 on-device verification — run docs/iphone-test-plan.md §4b (ios-hig-design >= 9/10, browser + standalone) and record scores
approach: Restyle the existing FastAPI+Jinja2/HTMX web UI in place — no framework change, no image generation — so on the iPhone (Safari + standalone PWA) it looks and behaves like a native iOS app: semantic iOS color/Dynamic Type/spacing tokens, safe-area-aware layout, iOS nav idiom, iOS component restyle, microinteractions, and PWA iOS integration, scored against the ios-hig-design rubric.
---

# Draft: ios-native-mobile-ui

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->
- C1 tokens | `:root` remapped to semantic iOS color/type/spacing tokens; every component rule consumes tokens (no raw px for layout/type) | active | style.css:3-30
- C2 layout/safe-areas | content respects env(safe-area-inset-*); standalone and browser modes both clean | active | base.html:5, style.css:359-382
- C3 nav | topbar becomes iOS-style blur bar + large title + mobile tab bar (New/Jobs); chevron back links; aria-current preserved | active | base.html:31-44, transcript.html:4
- C4 components | buttons/inputs/cards/badges/progress/tables/segments restyled to iOS idioms (tinted+filled buttons, grouped lists, capsule badges, UIProgressView-style bar, no heavy shadows/gradients/uppercase micro-labels) | active | style.css:121-341
- C5 microinteractions | tap scale feedback, HTMX swap enter/exit animations, smooth progress easing, badge pop | active | style.css:204, style.css:264-269
- C6 PWA iOS integration | apple-mobile-web-app metas, status-bar style, 180px apple-touch-icon (reuse existing PNG assets), splash/startup, display-mode:standalone handling | active | base.html:5-11, manifest.webmanifest
- C7 verification | full ios-hig-design 10-point diagnostic >= 9/10 on mobile; 131 pytest suite + compileall stay green; iPhone test-plan updated | active | tests/, docs/iphone-test-plan.md

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
<!-- assumption | adopted default | rationale | reversible? -->
- Icon asset | No new icon artwork (user excluded image generation). Reuse existing icon-192.png as apple-touch-icon (Safari scales it); keep manifest 192/512. Squircle-perfect icon deferred. | No image-creation phase; single-user local tool | yes (later task)
- Font | Keep -apple-system stack (renders SF Pro on iOS) — the native typeface on device | iOS HIG typography without bundling fonts | no
- Scope of change | CSS + template markup + PWA metas only; no Python route/behavior changes, no new deps/CDNs | Minimal risk to 131-test suite | n/a
- File organization | Keep single style.css (382 lines) — append iOS layer; no CSS framework | Simplicity, existing convention | no
- Dark theme | Dark-first; whether to ALSO ship light mode is an open owner-decision (Q1) | | depends on Q1

## Findings (cited - path:lines)
- Token base exists but is NOT iOS-semantic: custom hex palette + purple accent #8b7cf6, no systemBlue/label/secondaryLabel/systemBackground mapping (style.css:3-30). Type/spacing tokens exist (M6/M7) but raw px remain in many component rules (style.css:121-341).
- Cards: 14px radius + 1px border + heavy shadow (style.css:122-128) — iOS grouped lists use near-flat surfaces, 10-12px radius, hairline separators, no drop shadows.
- Buttons: filled accent, radius 10px, min-height 44px, :active translateY(1px) (style.css:187-213) — close, needs iOS tinted style + scale feedback.
- Inputs: dark bg + border + 10px radius + purple focus outline (style.css:149-182) — close to iOS; needs systemFill bg, iOS focus.
- Labels: uppercase + letter-spacing (style.css:141-147) — Android idiom; iOS uses plain footnote/caption case.
- Badges: capsule 999px pills with per-status tints (style.css:223-238) — already iOS-capsule-like; polish only.
- Progress: 10px pill, flat accent fill, width .4s ease (style.css:256-269) — already near-UIProgressView; needs iOS track tint + animation timing.
- Topbar: opaque bg-soft, no blur (style.css:69-80); nav links pill buttons — iOS uses blur materials + large title.
- Tables: desktop table + mobile stacked cards (style.css:329-381, H10) — solid; needs iOS grouped-list styling.
- Segments: 84px ts col + text grid, hairline separators (style.css:288-316) — already iOS-list-like.
- base.html: viewport-fit=cover ✓, theme-color ✓, apple-touch-icon 192px (base.html:5-11); MISSING apple-mobile-web-app-capable/status-bar-style, no 180px icon, no splash.
- manifest: standalone ✓, theme #12151c ✓, 192/512 icons only (manifest.webmanifest:1-24).
- sw.js: pt-shell-v3 network-first "/" + cache-first static (sw.js:10-18,28-33) — correct; ensure new metas/assets added to SHELL list.
- status.html polls every 5s with visibilityState guard + ARIA progressbar (status.html:2,10-14); jobs_list polls 10s with hx-select (jobs_list.html:6).
- 131 pytest tests exist incl. test_web.py template rendering (README). compileall -q src is the compile gate.

## Decisions (with rationale)
- D1: Plan scope = presentation layer only (CSS + templates + PWA metas). Zero Python route/behavior changes → protects 131 tests, worker untouched. CONFIRMED by user.
- D2: Build iOS compliance INTO tokens/components so violations are structurally prevented (the "impossible to fail" mechanism): if a component can only consume iOS tokens + iOS component specs, it cannot drift.
- D3: Score with the objective ios-hig-design Quick Diagnostic (10/10 = 6 rubric rows + up to 4 native-idiom points); target >= 9/10 at C7.
- D4 (user, Q1): Color system = Dark + light, system-matched (prefers-color-scheme). Semantic iOS colors for both appearances; token seam used now.
- D5 (user, Q2): Accent = shift toward iOS systemBlue/Indigo (#007AFF / #5856D6 family). Brand purple #8b7cf6 dropped for the iOS tint; used only where iOS uses its tint (tinted buttons, links, progress, selection).
- D6 (user, Q3): Mobile nav idiom = iOS bottom tab bar (New / Jobs, 49pt, blur) at <=560px and/or display-mode:standalone; desktop keeps the topbar.
- D7 (user, Q4): Test strategy = tests-after. All 131 pytest + compileall stay green after each wave; add render assertions only where templates change; agent-executed browser QA final.

## Scope IN
- Restyle all templates + fragments + style.css to iOS semantics (token-first).
- base.html head: apple-mobile-web-app metas, status-bar style, 180px apple-touch-icon (reuse existing PNG), splash/startup image, display-mode handling.
- iOS nav: blur topbar, large title, mobile tab bar (or approved nav idiom), chevron back links.
- Microinteractions: tap scale, HTMX swap animations, progress easing.
- Verify: ios-hig-design diagnostic >= 9/10 on iPhone Safari; 131 tests + compileall green; docs/iphone-test-plan.md updated.

## Scope OUT (Must NOT have)
- NO image generation / AI design-image phase (user explicitly excluded).
- NO new app-icon artwork, NO external CDNs, NO new JS/CSS frameworks, NO new Python deps.
- NO route/behavior/worker/auth/rate-limit changes; NO DB/schema changes.
- NO Android/Material styling (no uppercase micro-labels, no ripple, no Android nav patterns).
- NO hamburger menus, NO desktop-first layouts.
- NO dark-mode-only regression for desktop Safari (desktop must stay usable).

## Open questions
- Q1 Color system: keep dark-only, or add system-matched light mode (tokens are the cheap seam)?
- Q2 Accent hue: keep brand purple #8b7cf6 (styled iOS-tinted) or shift toward iOS systemBlue/Indigo?
- Q3 Navigation idiom on mobile: iOS bottom tab bar (New/Jobs), vs keep current topbar, vs large-title + segmented control?
- Q4 Test strategy confirmation: tests-after (existing pytest render suite stays green + agent-executed browser QA) vs TDD-first for the CSS layer?

## Approval gate
status: awaiting-approval
approach: Five waves — (1) iOS semantic token system incl. system-matched light mode; (2) layout/safe-areas + iOS nav (blur bar, large title, bottom tab bar, chevron back); (3) component restyle to iOS spec (tinted/filled buttons, grouped lists, capsules, UIProgressView-style, grouped tables, transcript segments); (4) microinteractions (tap scale, HTMX swap animations, progress easing); (5) PWA iOS integration (apple-mobile-web-app metas, status-bar style, 180px icon via existing PNG, splash, display-mode) then ios-hig-design diagnostic >= 9/10 + full regression. All 4 owner-forks answered (D4-D7). Next workflow action after approval: run scaffold-plan.mjs ios-native-mobile-ui --clear → mandatory Metis gap analysis → APPEND todos → fill TL;DR last.
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->
- User reply required: explicit approval ("yes" / "proceed" / "write the plan") or scope change.
