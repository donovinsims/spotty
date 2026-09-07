# iOS Native Mobile UI — Work Plan

## TL;DR

> **Quick Summary**: Restyle the existing FastAPI+Jinja2/HTMX web UI in place — no framework change, no image generation — so on the iPhone (Safari + standalone PWA) it looks and behaves like a native iOS app: semantic iOS color/type/spacing tokens (dark + light, system-matched), safe-area-aware layout, iOS nav idiom (blur bar, large title, bottom tab bar, chevron back), iOS component restyle, microinteractions, and PWA iOS integration — scored >= 9/10 on the ios-hig-design Quick Diagnostic with all 131 pytest + compileall green.

> **Deliverables**:
> - iOS semantic token layer (dark + light, system-matched) in style.css
> - Safe-area-aware layout + iOS nav (blur topbar, large title, bottom tab bar New/Jobs, chevron back)
> - iOS component restyle (tinted/filled buttons, grouped lists, capsule badges, UIProgressView-style bar, grouped tables)
> - Microinteractions (tap scale, HTMX swap animations, progress easing)
> - PWA iOS integration (apple-mobile-web-app metas, status-bar style, 180px icon, splash, display-mode handling)
> - ios-hig-design diagnostic >= 9/10 + updated docs/iphone-test-plan.md

> **Estimated Effort**: Medium
> **Parallel Execution**: NO — 5 sequential waves + final verification (single style.css, each wave gated)
> **Critical Path**: Tokens → Nav → Components → Microinteractions → PWA → Diagnostic

---

## Context

### Original Request
User asked that Spotty's web UI look and behave like a native iOS app on iPhone (Safari + standalone PWA). Draft approved at `.omo/drafts/ios-native-mobile-ui.md` (status: approved, 2026-08-10) after four owner-forks were answered (D4–D7).

### Interview Summary
**Key Discussions**:
- Q1 → D4: Color system = dark + light, system-matched (`prefers-color-scheme`); semantic iOS colors for both appearances
- Q2 → D5: Accent shifts to iOS systemBlue/Indigo (#007AFF / #5856D6); brand purple #8b7cf6 dropped as tint (kept only where iOS uses its tint)
- Q3 → D6: Mobile nav idiom = iOS bottom tab bar (New / Jobs, 49pt, blur) at <=560px and/or `display-mode:standalone`; desktop keeps topbar
- Q4 → D7: Tests-after — all 131 pytest + compileall stay green after each wave; render assertions updated only where templates change

### Research Findings
- Token base exists but is NOT iOS-semantic: custom hex palette + purple accent, no systemBlue/label/secondaryLabel/systemBackground mapping (style.css:3-30); raw px remain in many component rules (style.css:121-341)
- Cards: 14px radius + 1px border + heavy shadow (style.css:122-128) vs iOS grouped-list near-flat surfaces, 10-12px radius, hairline separators
- Buttons: filled accent, radius 10px, min-height 44px, `:active translateY(1px)` (style.css:187-213) — needs iOS tinted style + scale feedback
- Inputs: dark bg + border + 10px radius + purple focus outline (style.css:149-182) — needs systemFill bg + iOS focus
- Labels: uppercase + letter-spacing (style.css:141-147) — Android idiom; iOS uses plain footnote/caption case
- Badges: capsule 999px pills with per-status tints (style.css:223-238) and progress: 10px pill, flat accent fill, width .4s ease (style.css:256-269) — already near-iOS; polish only
- Topbar: opaque bg-soft, no blur (style.css:69-80); tables: desktop table + mobile stacked cards (style.css:329-381); segments: 84px ts col + text grid (style.css:288-316) — solid, need iOS restyle
- base.html: `viewport-fit=cover` ✓, `theme-color` ✓, 192px apple-touch-icon ✓ (base.html:5-11); MISSING `apple-mobile-web-app-capable`/`status-bar-style`, no 180px icon, no splash
- manifest: standalone ✓, theme #12151c ✓, 192/512 icons only (manifest.webmanifest:1-24); sw.js: pt-shell-v3 network-first "/" + cache-first static (sw.js:10-18,28-33) — SHELL list must gain new assets
- status.html polls every 5s with visibilityState guard + ARIA progressbar (status.html:2,10-14); jobs_list polls 10s with hx-select (jobs_list.html:6)
- 131 pytest tests incl. test_web.py template rendering; `compileall -q src` is the compile gate

### Gap Analysis (Metis)
- G1: Template markup changes (tab bar, chevron back, metas) touch render assertions in test_web.py → update assertions only where templates change (D7); zero Python behavior changes
- G2: `display-mode:standalone` changes chrome/insets → tab bar must also show there; safe-area `env()` must be consumed via tokens in both modes
- G3: Light mode must not regress desktop Safari (Scope OUT) → both appearances token-driven, verified in both modes
- G4: sw.js SHELL list must include the 180px apple-touch-icon + any new static asset, or first offline load breaks → update in Wave 5
- G5: iOS splash (`apple-touch-startup-image`) is device-size-specific → ship primary-size splash only; note limitation in docs/iphone-test-plan.md
- G6: Accessibility must survive restyle: `aria-current` on nav, ARIA progressbar on status, 44pt touch targets, Dynamic Type scale via rem tokens
- G7: No raw px for layout/type after Wave 1 → enforce via px audit (grep) at every wave verification; exceptions only for radius/borders/hairlines

---

## Work Objectives

### Core Objective
Restyle Spotty's web UI (FastAPI + Jinja2/HTMX, single style.css) to native-iOS look & behavior on iPhone Safari and standalone PWA, scoring >= 9/10 on the ios-hig-design Quick Diagnostic, without touching Python/behavior/worker, without new deps/CDNs/icon art, keeping all 131 pytest + compileall green after every wave.

### Concrete Deliverables
- iOS semantic token system on `:root` (color/type/spacing, dark + light)
- Safe-area-aware layout; blur topbar + large title; bottom tab bar (New/Jobs); chevron back links
- Components restyled to iOS idioms (tinted/filled buttons, grouped lists, capsules, UIProgressView-style bar, grouped tables, transcript segments)
- Microinteractions: tap scale, HTMX swap animations, progress easing, badge pop
- PWA iOS: apple-mobile-web-app metas, status-bar style, 180px apple-touch-icon (reused PNG), splash, sw.js SHELL update, display-mode handling
- ios-hig-design diagnostic >= 9/10 on iPhone Safari (browser + standalone); docs/iphone-test-plan.md updated

### Definition of Done
- [x] Wave 1: `:root` token system (dark + light) in place; every component rule consumes tokens (no raw px for layout/type)
- [x] Wave 2: safe-area layout + iOS nav (blur bar, large title, bottom tab bar, chevron back)
- [x] Wave 3: components restyled to iOS specs
- [x] Wave 4: microinteractions live
- [x] Wave 5: PWA iOS metas/icons/splash/SW shell complete
- [ ] ios-hig-design diagnostic >= 9/10 on iPhone Safari (browser + standalone) — F1, on-device; code review expects 8–9, 10 blocked by web-platform limits
- [x] All 131 pytest + `compileall -q src` green after every wave — compileall green every wave; final run: **131 passed** with `PT_AUTH_TOKEN=` env-override (no .env change); without override, 21 pre-existing auth-gated failures identical to HEAD baseline (zero regressions)
- [x] docs/iphone-test-plan.md updated

### Must Have
- D1–D7 honored (presentation-only, token seam, system-matched light, systemBlue/Indigo accent, bottom tab bar, tests-after)
- Every component consumes iOS tokens only — no raw px for layout/type (D2)
- `env(safe-area-inset-*)` respected in browser + standalone modes
- 44pt touch targets; `aria-current` on active nav; ARIA progressbar preserved on status page
- sw.js SHELL list updated for new assets

### Must NOT Have
- NO image generation / AI design-image phase (user explicitly excluded)
- NO new app-icon artwork, NO external CDNs, NO new JS/CSS frameworks, NO new Python deps
- NO route/behavior/worker/auth/rate-limit/DB/schema changes
- NO Android/Material styling (no uppercase micro-labels, no ripple, no Android nav patterns)
- NO hamburger menus, NO desktop-first layouts
- NO dark-mode-only regression for desktop Safari

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES — 131 pytest tests incl. test_web.py template rendering
- **Automated tests**: Tests after implementation (D7); render assertions updated only where templates change
- **Framework**: pytest + `compileall -q src`
- **No TDD**: tests-after per D7

### QA Policy
Every wave ends with: 131 pytest green + compileall clean + no-raw-px audit + template render spot check. Final wave adds on-device iPhone Safari QA per docs/iphone-test-plan.md with the ios-hig-design diagnostic score recorded.

---

## Execution Strategy

### Sequential Execution Waves

**Wave 1 (Foundation — iOS token system):**
- Task 1: Define semantic iOS token set on `:root` — colors (systemBackground/label/secondaryLabel/separator/systemFill/systemBlue tint), type scale (largeTitle/title/headline/body/footnote/caption), spacing scale — dark + light via `prefers-color-scheme` (D4)
- Task 2: Retire brand purple #8b7cf6 as tint; accent = systemBlue #007AFF / Indigo #5856D6 family (D5)
- Task 3: Remap every component rule in style.css to consume tokens only — no raw px for layout/type (D2)
- Task 4: Wave verification: 131 pytest + compileall + no-raw-px audit

**Wave 2 (Layout + iOS nav):**
- Task 5: Safe-area-aware layout: `env(safe-area-inset-*)` on topbar, bottom, tables — browser + standalone (C2)
- Task 6: Topbar → iOS blur bar (backdrop-filter saturate, translucent material) + large title (C3)
- Task 7: Mobile bottom tab bar New / Jobs, 49pt, blur, active tint + `aria-current` at <=560px and/or `display-mode:standalone` (D6)
- Task 8: Chevron back links on subpages (transcript.html:4) + wave verification

**Wave 3 (Component restyle):**
- Task 9: Buttons → iOS tinted + filled styles, 10-12px radius, 44pt targets (style.css:187-213)
- Task 10: Inputs → systemFill bg, iOS focus ring (style.css:149-182)
- Task 11: Cards → iOS grouped lists: near-flat, 10-12px radius, hairline separators, no heavy shadows (style.css:122-128)
- Task 12: Labels → plain footnote/caption case (no uppercase/letter-spacing); badges capsule polish (style.css:141-147, 223-238)
- Task 13: Progress → UIProgressView-style (track tint, eased); tables → grouped-list styling; transcript segments (style.css:256-269, 288-316, 329-381) + wave verification

**Wave 4 (Microinteractions):**
- Task 14: Tap scale feedback on interactive elements (C5)
- Task 15: HTMX swap enter/exit animations (C5)
- Task 16: Progress easing + badge pop polish + wave verification

**Wave 5 (PWA iOS integration + verification):**
- Task 17: `apple-mobile-web-app-capable` + `status-bar-style` metas in base.html head (C6)
- Task 18: 180px apple-touch-icon (reuse existing PNG) + splash/startup handling (C6)
- Task 19: sw.js SHELL list updated for new assets; `display-mode:standalone` handling (C6)
- Task 20: Full verification: ios-hig-design diagnostic >= 9/10 on iPhone Safari; 131 pytest + compileall; docs/iphone-test-plan.md updated (C7)

**Wave FINAL (Verification):**
- Task F1: ios-hig-design diagnostic >= 9/10 confirmed on-device (browser + standalone)
- Task F2: Full regression: 131 pytest + `compileall -q src` green
- Task F3: Plan compliance audit + docs/iphone-test-plan.md accuracy review

---

## TODOs

- [x] 1. Semantic iOS token set on `:root` (dark + light)
- [x] 2. Accent → systemBlue/Indigo; retire brand purple as tint
- [x] 3. Remap all component rules to tokens (no raw px layout/type)
- [x] 4. Wave 1 verification (pytest + compileall + px audit)
- [x] 5. Safe-area-aware layout (browser + standalone)
- [x] 6. iOS blur topbar + large title
- [x] 7. Bottom tab bar (New/Jobs, 49pt, blur, aria-current)
- [x] 8. Chevron back links + wave 2 verification
- [x] 9. iOS tinted/filled buttons
- [x] 10. iOS inputs (systemFill + focus)
- [x] 11. Cards → grouped lists (flat, hairline separators)
- [x] 12. Labels plain case + badge capsule polish
- [x] 13. UIProgressView-style progress + grouped tables + segments + wave 3 verification
- [x] 14. Tap scale feedback
- [x] 15. HTMX swap animations
- [x] 16. Progress easing + badge pop + wave 4 verification
- [x] 17. apple-mobile-web-app metas + status-bar style
- [x] 18. 180px apple-touch-icon (reused icon-192.png) + splash documented (G5: no artwork allowed)
- [x] 19. sw.js SHELL verified — no new assets (static/* already cache-first); display-mode handled in Wave 2
- [x] 20. Full regression + iphone-test-plan update; on-device diagnostic score → F1
- [ ] F1. On-device diagnostic >= 9/10 (browser + standalone) — user-owned, run docs/iphone-test-plan.md §4b
- [x] F2. Full regression: compileall green; pytest **131 passed** via `PT_AUTH_TOKEN=` env-override (dotenv honors present-empty var; no .env change) — and baseline-identical (21 pre-existing auth-gated failures) without the override
- [x] F3. Final plan compliance audit + iphone-test-plan updated

---

## Success Criteria

### Verification Commands
```bash
python -m pytest -q            # Expected: 131 passed
python -m compileall -q src    # Expected: no errors
# ios-hig-design Quick Diagnostic on iPhone Safari (browser + standalone): >= 9/10
# no-raw-px audit: grep px style.css → only radius/border/hairline exceptions, no layout/type
```

### Final Checklist
- [x] All 20 implementation tasks complete
- [x] F2 + F3 final verification pass (compileall, jinja, CSS braces, px audit, pt doctor); F1 on-device pending
- [ ] ios-hig-design diagnostic >= 9/10 on iPhone Safari + standalone (user-owned, §4b)
- [x] 131 pytest green — `PT_AUTH_TOKEN= .venv/bin/python -m pytest -q` → **131 passed** (no .env change); compileall green
- [x] docs/iphone-test-plan.md updated
