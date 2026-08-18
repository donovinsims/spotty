# iPhone End-to-End Test Plan (Phase 4)

Manual checklist to run **on the phone** against the Tailscale-exposed instance.
Everything here assumes the Mac is on, the launchd service is running, and
`scripts/tailscale-serve.sh` has been run at least once (see
[`docs/deployment-runbook.md`](deployment-runbook.md), §6).

The iPhone URL is:

```
https://donovins-macbook-pro.taila94639.ts.net:8765
```

(replace with the hostname printed by `scripts/tailscale-serve.sh`).

> **Note on "Add to Home Screen" (PWA):** this app is PWA-lite. The Home Screen
> icon opens the *same web app*; there is no offline transcription and no
> offline transcripts. Only the app shell (login page / static assets) is
> cached by the service worker for offline start. The Mac must be on and
> reachable for anything useful to happen.

---

## 0. Preflight (on the Mac, once)

- [ ] `scripts/status.sh` shows the service loaded, running, and
      `health: {"status":"ok","db":"ok"}`.
- [ ] `scripts/tailscale-serve.sh` prints the iPhone URL and does not complain.
- [ ] On the iPhone: Settings → VPN & Device Management → Tailscale is connected
      (or the tailnet apps can reach the Mac).

---

## 1. Happy path: full transcription on the phone

1. [ ] Open the iPhone URL **in Safari** (not the Tailscale app's browser).
2. [ ] If `PT_AUTH_TOKEN` is set: you are redirected to **Sign in** — paste the
       token (from the repo `.env`), tap **Sign in**, and confirm you land on
       the home page. (If auth is off, skip.)
3. [ ] Tap the URL field, paste a **known-good Spotify episode URL** (a short
       episode, e.g. under 30 min, transcribes fastest).
4. [ ] Tap **Transcribe**. The button shows a disabled/spinner state.
5. [ ] Confirm the job page opens with the episode title and a
       **RUNNING/PENDING badge**.
6. [ ] Watch the **progress bar** advance (it updates every 2s while running).
7. [ ] When it flips to **COMPLETE**, tap **View transcript**.
8. [ ] Transcript shows timestamped segments; **font size is comfortable at
       16px+** and nothing overflows the ~390px screen.
9. [ ] Use the **Search** box: search a word from the episode — matching
       segments render with highlighted `<mark>`.
10. [ ] Tap **Download .txt** — the file downloads to the Files app and opens.
11. [ ] Tap **Download .srt** — downloads and opens (subtitle format).

## 2. Queue behaviour

1. [ ] Paste a long episode and submit it (it starts RUNNING).
2. [ ] Immediately paste a **second** episode and submit.
3. [ ] Confirm the second job shows **QUEUED** with the
       "another job is running" note — it must NOT start until the first
       finishes.
4. [ ] When the first completes, the second automatically starts and completes.

## 3. Negative tests

1. [ ] Paste a **garbage / non-Spotify URL** (e.g. `https://example.com`) and
       submit — expect a friendly **"Not a Spotify episode URL"** message, no
       job created.
2. [ ] Paste a valid Spotify URL of an episode that is **unavailable** (e.g. a
       deleted episode) — expect an **"Episode unavailable — no job created"**
       message.
3. [ ] Tap **Transcribe** rapidly 11+ times (the limit is
       `PT_RATE_LIMIT_PER_MIN`, default 10) — submissions after the 10th are
       rejected with a **"Too many requests"** message.
4. [ ] (If the Mac is on a network where someone could reach it without auth)
       confirm the **"No auth" warning banner** appears on the home page when
       `PT_AUTH_TOKEN` is empty **and** the app is bound to a non-loopback
       interface (e.g. `pt serve --host 0.0.0.0`). With the standard
       `127.0.0.1` + Tailscale setup the banner does not appear.

## 4. PWA / Home Screen

1. [ ] Safari: tap **Share → Add to Home Screen**, name it, **Add**.
2. [ ] Open the app from the Home Screen icon — it launches full-screen
       (standalone) and loads the app shell.
3. [ ] While **airplane mode is off but the Mac is unreachable** (or Tailscale
       off): the shell may open from cache, but transcription/search will fail
       with a network error — this is expected (PWA-lite, online app).
4. [ ] Reconnect Tailscale and confirm the app works again.

## 4b. iOS-native UI diagnostic (ios-hig-design)

Run against the live instance in **both** Safari and Home-Screen standalone.
Score the Quick Diagnostic (6 rows = 1 pt each) + up to 4 native-idiom
points. Target: **≥ 9/10**.

Checklist (one point per row):
- [ ] **Safe areas** — no content under the notch/Dynamic Island or home
      indicator; topbar, bottom tab bar, and page bottom clear the insets in
      browser and standalone modes (viewport-fit=cover + `env()` insets).
- [ ] **Touch targets ≥ 44pt** — buttons, nav links, tab bar items, back
      links; no mis-taps.
- [ ] **Dark Mode** — toggle appearance; both schemes render with semantic
      iOS colors (systemBlue/Indigo accent, label/secondaryLabel,
      systemBackground layers); cards, badges, progress, fields all legible.
- [ ] **Dynamic Type** — Settings → Accessibility → Display & Text Size →
      Largest; text scales (rem tokens), nothing clips or overflows on a
      ~390pt screen.
- [ ] **VoiceOver** — complete one flow (submit → status → transcript);
      `aria-live` results, ARIA progressbar, `aria-current` tabs, tab bar
      labels, skip link all present.
- [ ] **Native navigation** — blur topbar, large title, bottom tab bar
      (New/Jobs, 49pt, blur, safe-area bottom), chevron back links; no
      hamburger menus, no Android idioms.

Native idiom (up to 4):
- [ ] +1 Semantic colors/text styles throughout — no hardcoded layout/type
      values outside the `:root` token layer.
- [ ] +1 System controls / semantic HTML (web limitation: UIKit controls
      N/A — credit at reviewer's discretion).
- [ ] +1 Standard gestures — Safari edge-swipe back works; tap scale
      feedback present (haptics N/A on web).
- [ ] +1 SF-Symbol-like inline glyphs (chevron/plus/list) + iOS squircle
      icon mask (icon-192.png reused; 1024px icon deferred — no artwork).

General checks:
- [ ] Light + dark both render cleanly (appearance toggle).
- [ ] Desktop Safari (Mac): no dark-only regression; layout still usable.
- [ ] Settings → Accessibility → Reduce Motion: swap animations and tap
      scale disabled (CSS `prefers-reduced-motion`).

Known limitations (do not fail the run):
- **Splash screen:** no `apple-touch-startup-image` — image generation is
  excluded, so iOS shows its default launch screen. Revisit if artwork
  becomes available.
- **Haptics / true SF Symbols / native controls** require a native app —
  out of scope for this web UI.
- Expected from code review: **8–9/10** (9 requires crediting inline glyphs
  as the SF-Symbol equivalent; 10 is blocked by web-platform constraints).

On-device score (browser): ___ / 10 · (standalone): ___ / 10

## 5. Final pass

1. [ ] Rotate the phone (portrait/landscape) on the jobs list, job detail, and
       transcript pages — no horizontal scrolling, table scrolls within its
       card if at all.
2. [ ] Buttons/links are comfortably tappable (≥ 44px) — no mis-taps.
3. [ ] Reload `/jobs` — the job list is readable and long episode titles wrap
       instead of overflowing.

---

## Troubleshooting

- **iPhone can't reach the page** → run `scripts/status.sh` and
  `scripts/tailscale-serve.sh` on the Mac; confirm the phone is on the tailnet.
- **"Too many requests"** → you hit the per-minute rate limit; wait ~60 s
  (see runbook §7).
- **"Queue is full"** → too many queued jobs; wait for the active transcription
  to finish (runbook §7).
- Everything else → see [`docs/deployment-runbook.md`](deployment-runbook.md),
  especially §7 Troubleshooting and `pt doctor`.
