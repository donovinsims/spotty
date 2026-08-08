# Task 1: Apply all High + Medium UX Review Fixes

## Context
Podcast-transcriber web UI: FastAPI + Jinja2 templates + HTMX + plain CSS, dark-theme-only, mobile-first.
All changes are in `src/podcast_transcriber/web/templates/` (HTML) and `src/podcast_transcriber/web/static/style.css`.

## Global Constraints
- DO NOT change color palette, font choices, or visual identity
- All changes must work in dark mode (no light mode exists but use CSS custom properties)
- All changes must be responsive (mobile ≤560px, tablet 561–768px, desktop 1024px+)
- Follow existing code patterns, use existing CSS custom properties (--bg, --border, --text, --muted, --accent, etc.)
- This is a Python project: the view layer `src/podcast_transcriber/web/app.py` provides context/templates
- Run `python -m pytest tests/ -x -q` after ALL fixes to verify no regressions

## HIGH Priority Fixes (H1–H15)

### H1: Undefined classes break login & sign-out
**Files:** `src/podcast_transcriber/web/templates/login.html`, `src/podcast_transcriber/web/templates/base.html`, `src/podcast_transcriber/web/static/style.css`

1. **login.html:9** — `<p class="error">{{ error }}</p>` uses `.error` which doesn't exist. Change to `<p class="err" role="alert">{{ error }}</p>`.
2. **login.html:11** — `<form class="column">` — `.column` doesn't exist (only `.stack` and `.row` exist). Change to `<form class="stack">`.
3. **login.html:12** — `input[type="password"]` is not styled. Add `<label for="token">Access token</label>` above it (match the submit_area.html pattern), and add `input[type="password"]` to the input selector in style.css:123.
4. **base.html:39** — `.btn-small` referenced in `<button class="btn btn-ghost btn-small">Sign out</button>` but never defined in CSS. Define in style.css near `.btn-ghost`: `.btn-small { padding: 6px 12px; font-size: 0.85rem; border-radius: 8px; min-height: 36px; }` and add `@media (max-width: 560px) { .footer .btn { width: auto; } }`

### H2: Home page hierarchy inversion
**File:** `src/podcast_transcriber/web/templates/fragments/submit_area.html`
**Line 1:** `<section id="submit-area">` — add `class="card"` so the primary "Transcribe" action gets equal visual weight as the secondary search card:
```html
<section id="submit-area" class="card">
```

### H3: Wrong thing is the link in both lists
**File 1:** `src/podcast_transcriber/web/templates/jobs_list.html`
- Line 19: Change `<td><a href="/jobs/{{ job.id }}">#{{ job.id }}</a></td>` to `<td class="muted">#{{ job.id }}</td>`
- Line 21: Change `<td>{{ episode.title if episode else "—" }}</td>` to `<td><a href="/jobs/{{ job.id }}">{{ episode.title if episode else "—" }}</a></td>` (wrap title in link, ID becomes plain)

**File 2:** `src/podcast_transcriber/web/templates/fragments/episode_results.html`
- Line 6: Wrap the title in a link when a job exists:
```html
<div>
  {% if ep_jobs.get(ep.id) %}
  <a href="/jobs/{{ ep_jobs[ep.id] }}"><strong>{{ ep.title or "Untitled episode" }}</strong></a>
  {% else %}
  <strong>{{ ep.title or "Untitled episode" }}</strong>
  {% endif %}
</div>
```

**CSS (style.css, near table section):** Add `td a { display: inline-block; min-height: 24px; }`

### H4: Internal jargon as user-facing copy
**File:** `src/podcast_transcriber/web/app.py` — add a Jinja filter for human-friendly status labels. Find where `ts` and `dt` filters are registered (around line 226-228) and add:
```python
_STATUS_LABELS = {
    "PENDING": "Waiting", "QUEUED": "Queued", "RUNNING": "Transcribing",
    "COMPLETE": "Complete", "FAILED": "Failed",
    "VERIFIED": "Verified", "REVIEW_REQUIRED": "Needs review",
    "UNAVAILABLE": "Unavailable",
}
templates.env.filters["label"] = lambda s: _STATUS_LABELS.get(s, s)
```

**Template changes (use `|label` filter on status display):**
- `jobs_list.html:20`: `{{ job.status|label }}`
- `fragments/status.html:4`: `{{ job.status|label }}`
- `fragments/episode_results.html:9`: `{{ ep.state|label }}`
- `job_detail.html:13`: `{{ episode.state|label if episode else "—" }}`

**Copy changes in status.html:**
- Line 13: `{{ view.chunks_done }} / {{ view.chunks_total }} chunks done` → `{{ view.progress_pct }}% done ({{ view.chunks_done }} of {{ view.chunks_total }} parts)`
- Line 17: `Waiting for the worker to pick this up…` → `Waiting to start…`
- Line 15: `Waiting — another job is running. This one will start automatically when it finishes.` → `Queued behind the current job — yours will start automatically.`

### H5: Job detail page — swap h1/h2 and move status up
**File:** `src/podcast_transcriber/web/templates/job_detail.html`
- Move `{% include "fragments/status.html" %}` from line 27 to BEFORE the episode `<article>` card (after `<h1>`). The status card is what users came for.
- Line 5: Change `<h1>Job {{ job.id }}</h1>` to use the episode title as h1:
```html
<h1>{{ episode.title if episode and episode.title else "Untitled episode" }}</h1>
<p class="muted">Job {{ job.id }}</p>
```
- Line 8: Remove `<h2>` wrapping on the title text that was there.

### H6: No in-flight feedback on forms
**File 1:** `style.css` — add after `.btn-ghost:hover` (line 164):
```css
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
```

**File 2:** `submit_area.html:9` — add `hx-indicator="#submit-indicator"` and a status text element:
```html
<div id="submit-indicator" class="muted htmx-indicator" style="margin:4px 0 0" role="status">Resolving episode…</div>
```
Place it inside the form, below the `.row` div.

**File 3:** CSS for htmx indicators (near form styles):
```css
.htmx-indicator { display: none; }
.htmx-request .htmx-indicator { display: inline; }
```

**File 4:** `index.html:15-21` and `transcript.html:16-22` — add `hx-disabled-elt="button[type=submit]"` to both search forms.

### H7: Rate-limit errors destroy user's URL
**File:** `src/podcast_transcriber/web/app.py` — in the `too_many()` handler for HTMX requests to POST /jobs, render `submit_area` with the preserved URL and an inline error. Find the 429/409 handling (around lines 405-421) and for HTMX requests, return `submit_area(request, submitted_url=url, result={...})` instead of the generic error fragment. The alert should say: "Too many jobs — try again in a moment" with a message indicating the wait.

### H8: No cancel/retry on jobs
**File 1:** `fragments/status.html` — add cancel button for QUEUED/PENDING:
```html
{% elif job.status in ("QUEUED", "PENDING") %}
  ...existing copy...
  <form class="actions" hx-post="/jobs/{{ job.id }}/cancel" hx-target="#job-status" hx-swap="outerHTML">
    <button type="submit" class="btn btn-ghost btn-small">Cancel job</button>
  </form>
```

Add retry button for FAILED:
```html
{% elif job.status == "FAILED" %}
  <p class="err" role="alert">{{ job.error or "Job failed with no recorded error." }}</p>
  <div class="actions">
    <a class="btn" href="/">New transcription</a>
    <button class="btn btn-ghost" hx-post="/jobs/{{ job.id }}/retry" hx-swap="none">Try again</button>
  </div>
```

**File 2:** `app.py` — add `/jobs/{job_id}/cancel` and `/jobs/{job_id}/retry` POST routes. Cancel sets status to CANCELLED (add constant). Retry re-queues the same episode_id.

### H9: Polling improvements
**File:** `fragments/status.html:1-2`
- Change poll interval from `every 2s` to `every 5s`
- Add visibility guard: `hx-trigger="every 5s [document.visibilityState !== 'hidden']"`
- Guard the RUNNING block (progress bar + "chunks done") with `{% if view.chunks_total > 0 %}` so "0/0" never renders
- When chunks_total is 0, show: `<p class="muted">Downloading audio — progress appears once chunking starts…</p>`

**File:** `base.html` — add a visibilitychange listener to pause/resume polling:
```html
<script>
  document.addEventListener("visibilitychange", function () {
    var el = document.getElementById("job-status");
    if (!el) return;
    el.dispatchEvent(new Event(
      document.hidden ? "htmx:pausePolling" : "htmx:resumePolling"));
  });
</script>
```

### H10: Jobs table horizontal scroll on mobile
**File:** `style.css` — in the `@media (max-width: 560px)` consolidated block, add stacked-card styling for the jobs table rows:
```css
@media (max-width: 560px) {
  .table-card table, .table-card tbody, .table-card tr, .table-card td { display: block; width: 100%; }
  .table-card thead { position: absolute; left: -9999px; }
  .table-card tr { padding: 12px 14px; border-bottom: 1px solid var(--border); }
  .table-card td { padding: 6px 0; border: 0; }
  .table-card td:first-child { padding-left: 0; }
}
```

### H11: Keyboard focus invisible on buttons/links
**File:** `style.css` — change `input:focus` to `input:focus-visible` (line 137). Add global focus-visible:
```css
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
```

### H12: Screen reader gaps
**File 1:** `login.html:12` — add `<label for="token">Access token</label>` (from H1 fix)
**File 2:** `index.html:22` — `<div id="episode-results" aria-live="polite"></div>`
**File 3:** `transcript.html:24` — `<div id="search-results" aria-live="polite"></div>`
**File 4:** `fragments/status.html:9` — add `aria-label="Transcription progress"` to the progressbar div
**File 5:** `fragments/status.html:19` — add `role="status"` to the COMPLETE message `<p>`
**File 6:** `fragments/status.html:25` — the FAILED message `<p class="err">` should have `role="alert"`
**File 7:** `jobs_list.html:8-14` — add `scope="col"` to each `<th>` and `aria-label="Transcription jobs"` to the `<table>`

### H13: Component boundaries fail WCAG
**File:** `style.css` — brighten the border of inputs and ghost buttons:
```css
input[type="url"], input[type="search"], input[type="text"], input[type="password"], .btn-ghost {
  border-color: color-mix(in srgb, var(--text) 30%, var(--border));
}
```
Fallback (older browsers): keep `border: 1px solid var(--border)` as the fallback, with the color-mix override after.

Add placeholder styling:
```css
::placeholder { color: var(--muted); opacity: 1; }
```

### H14: Search results — dead ends & duplicates
**File 1:** `fragments/episode_results.html` — when ep has no job, add "Transcribe this episode" link:
```html
{% else %}
  <strong>{{ ep.title or "Untitled episode" }}</strong>
  <a class="btn btn-ghost btn-small" href="/?url={{ (ep.url or '')|urlencode }}">Transcribe this</a>
```
(And in app.py's index route, accept a `url` query param and pass it as `submitted_url` to prefill the form.)

**File 2:** `transcript.html` — give segments fragment ids and add search result anchors:
- Line 29: `<div class="seg" id="seg-{{ loop.index0 }}">`
- In `search_results.html`, the timestamp becomes a jump link: `<a class="ts" href="#seg-{{ m.idx }}">{{ m.start_time|ts }}</a>`
- The `app.py` transcript search route should pass `idx` in the match dict (use `enumerate`)

**File 3:** `search_results.html` — add a "clear" link and wrap transcript region:
```html
{% if matches %}
<p class="muted">{{ matches|length }} matching segments for "{{ q }}"
   · <a href="/jobs/{{ job_id }}/transcript">clear</a></p>
```

**File 4:** `style.css` — add scroll-margin and target highlight:
```css
.seg { scroll-margin-top: 70px; }
.seg:target { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 8px; }
```

### H15: Active nav tab nearly invisible
**File:** `style.css:74-77` — replace the `.topnav a[aria-current="page"]` block:
```css
.topnav a[aria-current="page"] {
  color: var(--accent);
  background: rgba(139, 124, 246, 0.14);
}
```

---

## MEDIUM Priority Fixes (M1–M19)

### M1: Confidence precision
**Files:** `job_detail.html:16`, `fragments/submit_area.html:25`
- `job_detail.html:16`: `{{ "%.3f"|format(episode.confidence) }}` → `{{ (episode.confidence * 100)|round(0)|int }}%`
- `submit_area.html:25`: `{{ "%.2f"|format(c.confidence) }}` → `{{ (c.confidence * 100)|round(0)|int }}%`

### M2: The "(s)" epidemic
**File:** `app.py` — add a `pluralize` filter alongside the existing `ts`/`dt` filters:
```python
templates.env.filters["pluralize"] = lambda n, singular, plural="": f"{singular}{'' if n == 1 else (plural or singular + 's')}"
```
**Templates** (use `|pluralize`):
- `status.html:19`: `{{ view.segments_count }} segment{{ '' if view.segments_count == 1 else 's' }}.` → `{{ view.segments_count }} {{ view.segments_count|pluralize('segment') }}.`
- `search_results.html:4`: `{{ matches|length }} matching segment(s)` → `{{ matches|length }} matching {{ matches|length|pluralize('segment') }}`
- `episode_results.html:1`: `{{ episodes|length }} episode(s)` → `{{ episodes|length }} {{ episodes|length|pluralize('episode') }}`

### M3: Login page shows nav that circles back
**File:** `base.html`
- Wrap the nav in `{% if request and request.url.path != "/login" %}` (gate it off login path)
- Move Sign out from footer into the topbar, right-aligned. Remove from footer.
```html
<header class="topbar">
  <a class="brand" href="/">podcast-transcriber</a>
  {% if request and not request.url.path.startswith("/login") %}
  <nav class="topnav">...</nav>
  {% endif %}
  {% if auth_enabled %}<form method="post" action="/logout">
    <button class="btn btn-ghost btn-small">Sign out</button>
  </form>{% endif %}
</header>
```

### M4: autofocus hostile on mobile
**File:** `submit_area.html:12` — remove `autofocus` attribute from the URL input.

### M5: Touch targets collapse at 561–768px
**File:** `style.css` — move min-height 44px rules from the `≤560px` media query to the base rules:
```css
.topnav a, .btn { min-height: 44px; display: inline-flex; align-items: center; }
.btn { justify-content: center; }
```
Remove duplicates from the mobile block. Also add to `.back` links:
```css
.back { display: inline-flex; align-items: center; min-height: 44px; padding: 4px 10px; }
```

### M6: Type scale drift
**File:** `style.css` — consolidate the scattered font sizes into custom properties at `:root`, then remap:
```css
--text-display: 1.6rem;  /* h1 only */
--text-section: 1.15rem; /* h2, .brand */
--text-body: 1rem;       /* inputs, buttons, dd, .seg, body */
--text-caption: 0.85rem; /* nav, labels, .muted, .back, .footer, th, .meta dt, .ts, badges */
```
- h1 → var(--text-display), h2/.brand → var(--text-section), body/inputs/buttons/.seg → var(--text-body), nav/labels/th/.meta dt/.back/.footer/.badge/.ts → var(--text-caption).
- Delete `.transcript-header h1 { font-size: 1.35rem; }` (line 265) — transcript gets the standard h1.
- Normalize `.btn` font-weight from 650 to 600, `.btn-ghost` from 550 to 600.

### M7: Spacing tokens
**File:** `style.css` — add spacing tokens at `:root`:
```css
--sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px; --sp-5: 24px;
```
Apply consistently:
- `.card` margin: `--sp-4` (16px)
- `.progress`, `.actions`, `.search-inline`, `.meta`, `.episode-list` margins: `--sp-3` (12px)
- `.stack` gap: `--sp-3`, `.row` gap: `--sp-3`, `.actions` gap: `--sp-3`
- `.topnav` gap: `--sp-2`, `.meta` gap: `--sp-2`, `.status-row` gap: `--sp-2`
- `.row.small` gap: `--sp-2`, mobile gap overrides: `--sp-1` where appropriate

### M8: CSS consolidation — resolve duplicate rules
**File:** `style.css`
- Line 268 (`.table-card { padding: 0; overflow: hidden; }`) combined with line 316 (`overflow-x: auto`) → single rule: `.table-card { padding: 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }`
- Merge the two `@media (max-width: 560px)` blocks (lines 292-304 and 318-334) into one.
- Merge the duplicate `body { font-size: 16px; }` (line 308) into the base body rule (line 27-35).

### M9: Badge color consolidation
**File:** `style.css` — group identical badge variants:
```css
.badge-complete, .badge-verified { color: var(--ok); border-color: var(--ok); background: rgba(74, 222, 128, 0.08); }
.badge-queued, .badge-review_required { color: var(--warn); border-color: var(--warn); background: rgba(251, 191, 36, 0.08); }
.badge-failed, .badge-unavailable { color: var(--err); border-color: var(--err); background: rgba(248, 113, 113, 0.08); }
```
Remove `--queued` from :root (use `--warn` instead).

### M10: Transcript search → GET
**File:** `transcript.html:17` — change `hx-post` to `hx-get`.
**File:** `app.py` — change the route to accept GET, or use `@app.api_route(..., methods=["GET", "POST"])`.

### M11: Silent truncation disclosure
**File:** `jobs_list.html` — after the table, when rows|length equals 100:
```html
{% if rows|length == 100 %}<p class="muted">Showing the 100 most recent jobs.</p>{% endif %}
```

### M12: Empty search states
**File:** `index.html:22` — replace empty `<div id="episode-results"></div>` with hint:
```html
<div id="episode-results">
  <p class="muted">Type a title, show, or URL above to search stored episodes.</p>
</div>
```
**File:** `episode_results.html` — add a fallback when `q` is empty/whitespace:
```html
{% if not q or q|trim == '' %}
<p class="muted">Search stored episodes by title, show, or URL.</p>
{% elif episodes %}
...existing...
{% endif %}
```

### M13: Double material on cards
**File:** `style.css:20,100` — remove `box-shadow: var(--shadow);` from `.card` (line 100). Keep the border. Also change progress fill from gradient to solid:
```css
.progress-fill { background: var(--accent); }
```

### M14: Footer privacy claim conditional
**File:** `base.html` — derive footer text from auth state:
```html
{% if not auth_enabled and request and not request.url.path.startswith("/login") %}
<span class="muted">local · private · runs entirely on this machine</span>
{% elif auth_enabled and request and not request.url.path.startswith("/login") %}
<span class="muted">runs entirely on this machine</span>
{% endif %}
```

### M15: `role="status"` under-announces errors
**File:** `fragments/submit_area.html:19` — dynamic role:
```html
<div class="alert alert-{{ result.kind }}" role="{{ 'alert' if result.kind == 'error' else 'status' }}">
```
**File:** `index.html:5` — change the no-auth warning to `role="alert"`.

### M16: Jobs list frozen snapshot
**File:** `jobs_list.html` — add polling while any job is active. In the route (`app.py`), pass `active` flag. Then:
```html
<div class="card table-card" {% if active %}hx-get="/jobs" hx-trigger="every 10s" hx-select=".table-card" hx-swap="outerHTML"{% endif %}>
```

### M17: Error pages diverge
**File:** `error.html` — add the 500 guidance text and back button from the fragment:
```html
{% block title %}{{ status_code }}{% endblock %}
{% block content %}
<h1>{{ status_code }}</h1>
<p class="muted">{{ detail }}</p>
{% if status_code == 500 %}<p class="muted">Something went wrong on the server. Try again in a moment.</p>{% endif %}
<p><a class="btn" href="/">Back home</a></p>
{% endblock %}
```

### M18: No skip link
**File:** `base.html` — first element in `<body>`:
```html
<a class="skip-link" href="#main">Skip to content</a>
```
And change `<main class="container">` to `<main id="main" class="container">`.
CSS:
```css
.skip-link { position: absolute; left: -9999px; top: 0; background: var(--accent); color: var(--accent-ink); padding: 10px 16px; border-radius: 0 0 10px 0; font-weight: 600; z-index: 100; }
.skip-link:focus { left: 0; }
```

### M19: Candidate fallback improvements
**File:** `submit_area.html:23-26` — clean up candidate list:
- Line 25: Change `{{ c.title or c.audio_url or "?" }}` → `{{ c.title or c.audio_url or "Untitled episode" }}`
- Confidence: `{{ "%.2f"|format(c.confidence) }}` → `{{ (c.confidence * 100)|round(0)|int }}%`
- Add a guidance line after the candidates list (inside the alert, before closing `</ul>` or after):
```html
<p class="muted">If one of these looks right, paste the correct episode URL from Spotify.</p>
```

---

## Implementation Notes
- Read each file before editing; verify line references match the actual code (the codebase may have shifted).
- Make changes following existing code patterns.
- After all changes, run: `python -m pytest tests/ -x -q` from the repo root `/Users/forex/Spotty` to verify no regressions.
- Commit with message: "UX review: apply all high + medium impact fixes (H1-H15, M1-M19)"
