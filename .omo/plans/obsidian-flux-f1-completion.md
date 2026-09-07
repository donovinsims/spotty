# Obsidian Flux — F1 Completion Plan

## TL;DR

> **Summary**: Update stale plan/test-plan docs from iOS-native to Obsidian Flux reality, bump SW cache version to force iPhone refresh, re-score diagnostic criteria, run on-device QA, commit.

> **Deliverables**:
> - Updated `.omo/plans/ios-native-mobile-ui.md` → reflects Obsidian Flux design system
> - Updated `docs/iphone-test-plan.md §4b` → diagnostic criteria for Obsidian Flux
> - `sw.js` cache version bump `pt-shell-v3` → `pt-shell-v4` (forces iPhone SW reinstall)
> - Updated `HANDOFF.md` → current state
> - On-device diagnostic score recorded in test plan

> **Estimated Effort**: Small (docs + SW bump + on-device test)
> **Parallel Execution**: NO — sequential: docs → SW bump → commit → on-device test
> **Critical Path**: Update docs → bump SW → commit → user runs on-device → record scores

---

## Context

### What happened
1. iOS-native UI committed `8aa6d03` (Aug 11) — tokens, tab bar, chevron back, PWA metas
2. Overwritten by Spotify design `0d91cdd` then Obsidian Flux `aaacbd3` (Aug 18)
3. Current HEAD `063d6d3` has full Obsidian Flux: dark-only, glass morphism, sidebar nav, Inter + JetBrains Mono, Spotify green accent
4. Plan file `.omo/plans/ios-native-mobile-ui.md` **stale** — still describes iOS-native work
5. `docs/iphone-test-plan.md §4b` **stale** — diagnostic criteria reference iOS tokens, light/dark, systemBlue
6. iPhone has old CSS cached via service worker (cache-first for static assets)

### Current design system (Obsidian Flux)
- **Dark-only** — no `prefers-color-scheme`, hard-coded `#050505` void stage
- **Glass morphism** — `backdrop-filter: blur(20px)`, `rgba(0,0,0,0.4)` glass bg, hairline `rgba(255,255,255,0.05)` borders
- **Sidebar nav** — 280px glass rail (desktop), hamburger drawer (mobile ≤560px)
- **Bottom tab bar** — ≤560px and/or `display-mode: standalone`, glass blur, safe-area padding
- **Typography** — Inter (UI) + JetBrains Mono (code/labels), Material-3-style type tokens
- **Accent** — Spotify green `#53e076` primary, `#1db954` container, mint `#00ffa3` secondary
- **Status colors** — ok `#1ed760`, warn `#ffc862`, err `#ff453a`, pending `#576dd6`, running `#7358ff`

---

## Work Objectives

### Core Objective
Replace stale iOS-native plan/docs with Obsidian Flux reality, force iPhone SW refresh, and complete on-device diagnostic.

### Concrete Deliverables
1. Rewrite `.omo/plans/ios-native-mobile-ui.md` → new file `.omo/plans/obsidian-flux-f1-completion.md`
2. Rewrite `docs/iphone-test-plan.md §4b` → diagnostic criteria matching Obsidian Flux design
3. Bump `sw.js` CACHE from `pt-shell-v3` → `pt-shell-v4`
4. Update `HANDOFF.md` to reflect current state
5. User runs on-device diagnostic, scores recorded

### Definition of Done
- [ ] Plan file reflects Obsidian Flux reality
- [ ] §4b diagnostic criteria match Obsidian Flux design system
- [ ] SW cache version bumped (v3 → v4)
- [ ] All 131 pytest + compileall green after SW bump
- [ ] On-device diagnostic scored and recorded in §4b

### Must Have
- Dark-mode requirement DROPPED (Obsidian Flux is dark-first, user confirmed)
- Diagnostic criteria tailored to Obsidian Flux (dark void stage, glass morphism, sidebar nav, green accent)
- SW bump forces iPhone to re-fetch CSS (cache-first strategy needs version bump)

### Must NOT Have
- NO light-mode testing (dropped per user)
- NO iOS-native token references (systemBlue/Indigo dropped)
- NO changes to CSS or templates (design is final)
- NO Python/behavior/route changes

---

## Execution Waves

### Wave 1 (Docs Update)
**Task 1**: Rewrite `.omo/plans/ios-native-mobile-ui.md`
- Rename/replace with `.omo/plans/obsidian-flux-f1-completion.md`
- Reflect current Obsidian Flux design system
- Update success criteria, deliverables, context
- Remove all iOS-native references (tokens, light/dark, systemBlue)

**Task 2**: Rewrite `docs/iphone-test-plan.md §4b`
- New diagnostic criteria for Obsidian Flux:
  - Row 1: Safe areas (unchanged — still relevant)
  - Row 2: Touch targets ≥44pt (unchanged)
  - Row 3: **Dark void stage** (replaces "Dark Mode" — no toggle, dark-only)
  - Row 4: **Typography scaling** (replaces "Dynamic Type" — Inter + JetBrains Mono, rem tokens)
  - Row 5: VoiceOver (unchanged)
  - Row 6: Native navigation (rephrase for sidebar + tab bar)
  - Native idiom: semantic tokens, glass morphism, standard gestures, inline SVG icons
- Remove light/dark toggle test
- Update known limitations (no splash, haptics N/A, web limits)

**Task 3**: Update `HANDOFF.md`
- Reflect current HEAD state (Obsidian Flux, not iOS tokens)
- Reference new plan file

### Wave 2 (SW Bump + Verification)
**Task 4**: Bump `sw.js` cache version
- Change `const CACHE = "pt-shell-v3"` → `const CACHE = "pt-shell-v4"` in `src/podcast_transcriber/web/static/sw.js`
- This forces the SW to reinstall on all clients, dropping old cached CSS

**Task 5**: Verify
- `compileall -q src` green
- `PT_AUTH_TOKEN= python -m pytest -q` → 131 passed
- CSS brace balance check
- Commit: `chore(web): bump SW cache v3→v4, update plan/docs for Obsidian Flux`

### Wave 3 (On-Device — User-owned)
**Task 6**: User opens iPhone URL in Safari
- URL: `https://donovins-macbook-pro.taila94639.ts.net:8765`
- If old design appears: Safari → clear website data for the domain, or Settings → Safari → Clear History
- SW bump should auto-refresh, but manual clear is fallback

**Task 7**: User scores diagnostic per new §4b criteria
- Record: `On-device score (browser): ___ / 10 · (standalone): ___ / 10`
- Target: ≥9/10

**Task 8**: Fix any failures
- If score <9: identify specific issues, fix CSS/templates, re-test
- If score ≥9: commit final scores, mark F1 complete

---

## TODOs

- [ ] 1. Rewrite plan file for Obsidian Flux
- [ ] 2. Rewrite §4b diagnostic criteria
- [ ] 3. Update HANDOFF.md
- [ ] 4. Bump SW cache v3 → v4
- [ ] 5. Run pytest + compileall verification
- [ ] 6. Commit docs + SW bump
- [ ] 7. User runs on-device diagnostic (browser + standalone)
- [ ] 8. Record scores, fix if needed, commit final

---

## Success Criteria

### Verification Commands
```bash
python -m compileall -q src    # Expected: no errors
python -m pytest -q            # Expected: 131 passed
# On-device: obsidian-flux diagnostic >= 9/10 on iPhone Safari + standalone
```

### Final Checklist
- [ ] Plan file reflects Obsidian Flux (no iOS-native references)
- [ ] §4b criteria match Obsidian Flux design system
- [ ] SW cache bumped to v4
- [ ] pytest + compileall green
- [ ] On-device diagnostic scored ≥9/10
- [ ] Scores recorded in docs/iphone-test-plan.md
