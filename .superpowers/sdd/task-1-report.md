# Task 1 Report: High + Medium UX Fixes

## Status: DONE_WITH_CONCERNS

## What was done

Applied all 34 findings (H1-H15, M1-M19) across 16 files:

**Python (`app.py`, `store.py`):**
- Added `label` and `pluralize` Jinja filters + `_STATUS_LABELS` map (H4, M2)
- Index route accepts `?url=` to prefill the submit form (H14)
- H7: HTMX rate-limit (429) and queue-cap (409) now return `submit_area` fragment with the user's URL preserved + inline alert + `Retry-After` header
- H8: added `POST /jobs/{id}/cancel` and `POST /jobs/{id}/retry` routes; added `CANCELLED` constant to store.py
- M16: jobs list route passes `active` flag
- M10: transcript search now accepts GET (via `@app.api_route` GET+POST)

**Templates (all 12):**
- `base.html`: skip link (M18), sign-out moved to topbar and nav gated off /login (M3), visibilitychange polling pause/resume (H9), auth-aware footer claim (M14)
- `login.html`: fixed broken `.error`/`.column`/`.btn-small` classes, added label for password (H1, H12)
- `index.html`: hx-indicator + hx-disabled-elt (H6), aria-live (H12), empty-search hint (M12), role=alert on no-auth banner (M15)
- `jobs_list.html`: title is now the link, ID is muted text (H3), `|label` statuses (H4), `scope="col"` + table aria-label (H12), 100-row disclosure (M11), 10s polling while active (M16)
- `job_detail.html`: h1 = episode title + "Job N" muted subtitle, status moved above the episode card (H5), `|label` (H4), % confidence (M1)
- `transcript.html`: hx-get search + hx-disabled-elt (M10/H6), segment ids `seg-{idx}` + search-results aria-live (H14/H12)
- `error.html`: 500 guidance + back button (M17)
- `fragments/status.html`: cancel button for QUEUED/PENDING, retry + back for FAILED (H8), 5s poll + visibility guard + 0/0 progress guard (H9), `|label` (H4), pluralize (M2), aria roles (H12)
- `fragments/submit_area.html`: card class (H2), hx-indicator (H6), no autofocus (M4), dynamic role on alert (M15), % confidence + "Untitled episode" fallback + guidance line (M19/M1)
- `fragments/episode_results.html`: title links to job (H3), `|label` (H4), pluralize (M2), "Transcribe this" for jobless episodes (H14), empty-q fallback (M12)
- `fragments/search_results.html`: timestamp links jump to segment (H14), pluralize (M2), matches count + clear link (H14)

**CSS (`style.css`):**
- `.btn-small`, `.btn:disabled`, `.htmx-indicator`, `.skip-link`, `:focus-visible`, `::placeholder`, brightened input/ghost borders via color-mix (H1/H6/H11/H13/H18)
- Stacked table cards ≤560px + merged duplicate media blocks (H10/M8)
- Nav active state uses accent tint (H15)
- 44px touch targets moved to base rules, `.back` sizing (M5)
- Type scale + spacing custom properties (M6/M7)
- Badge color consolidation, removed `--queued` (M9)
- Removed `.card` box-shadow + gradient progress fill → solid accent (M13)
- `.seg` scroll-margin + `:target` highlight (H14)

## Test results

`PT_AUTH_TOKEN= python3 -m pytest tests/ -q -k "not test_transcribe_resume"` → **130 passed, 1 deselected**

## Concerns

1. **Pre-existing auth-in-tests issue**: `.env` sets `PT_AUTH_TOKEN=Hononegah1!`, which the Config reads, so the full suite fails with 401s unless the env var is unset. Confirmed pre-existing by stashing our changes and re-running — the original code fails the same way. The task's "run pytest" step only passes with `PT_AUTH_TOKEN=` prefix (or with the var unset). This is worth fixing in conftest (pin `auth_token` to empty in the `make_app` fixture) but I left it out of scope.
2. **Pre-existing scipy environment failure**: `tests/test_transcribe_resume.py` fails with `dlopen` error on `_spropack.cpython-313-darwin.so` (zero-fill section type) — an environment/library issue, unrelated to UX changes. Deselected.
3. **H7 behavior change**: rate-limited HTMX requests now return **200** with the preserved-URL fragment (instead of 429 with the generic error fragment). `tests/test_ratelimit.py::test_rate_limit_htmx_gets_fragment` was updated to assert the new behavior. The `Retry-After` header is still set. The API/JSON path still returns 429.
4. **Polling interval change** (2s → 5s) was intentional per H9 but makes the jobs table / status updates slightly less immediate — a deliberate trade for lower request churn.

## Commit

`UX review: apply all high + medium impact fixes (H1-H15, M1-M19)` — (pending commit at report time)
