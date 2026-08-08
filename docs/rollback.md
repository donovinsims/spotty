# Rollback Guide

How to take the running launchd service back to a previous commit if a
deployment breaks mid-demo or in production.

The rollback is: **stop the service → checkout the previous commit → reinstall
the venv → restart → verify**. The SQLite database is never touched by a
rollback, so no transcription data is lost; migrations are forward-only and
backward-compatible by design (schema migrations apply on open, and older code
tolerates newer columns).

---

## Step-by-step

### 1. Stop the service

```bash
scripts/stop.sh
scripts/status.sh        # confirm "running: no"
```

`stop.sh` keeps the plist loaded, so launchd will not auto-start the old code
while we work.

### 2. Identify the previous commit

```bash
git log --oneline -5
# previous release commit is the one right below HEAD
```

### 3. Check out the previous commit

```bash
git stash                 # if you have uncommitted work you want to keep
git checkout <previous-hash>
```

If you need to keep the current code too (e.g. to inspect it), use a branch:

```bash
git branch deploy-backup   # mark the current state
git checkout <previous-hash>
```

### 4. Reinstall the venv (code changed → console script must match)

```bash
.venv/bin/pip install -e .
```

### 5. Restart and verify

```bash
scripts/restart.sh
scripts/status.sh
curl -fsS http://127.0.0.1:8765/healthz
# {"status":"ok","version":"0.1.0","db":"ok"}
```

### 6. Smoke-test the web UI

Open `http://127.0.0.1:8765` and:

- run one resolve of a known episode URL (or `pt jobs` in the terminal),
- confirm an existing COMPLETE job still shows its transcript,
- check `logs/serve.err.log` for tracebacks.

---

## If the DB was migrated forward and you must go back

Schema migrations are applied on startup (`schema_version` table in
`store.py`). Rolling back to a commit whose migration set is a strict subset is
safe — `CREATE TABLE IF NOT EXISTS` / additive columns ignore the extra tables.
If you ever need to roll the schema itself back, restore the whole `data/`
directory from a backup **while the service is stopped**:

```bash
scripts/stop.sh
cp -r data data.bak-<date>              # snapshot current state first
# restore the backup instead:
rm -rf data && cp -r <backup> data
scripts/start.sh
```

## Reverting a bad deploy that never started

If the service fails immediately after an upgrade (crash loop), you do not even
need to stop it manually:

```bash
scripts/uninstall.sh            # stop + unload + remove plist
git checkout <previous-hash>
.venv/bin/pip install -e .
scripts/install.sh              # reinstall the launchd service
scripts/status.sh
```

## Escalation

If the service is up but behaves incorrectly (wrong transcripts, weird
downloads), roll back as above and keep the failing commit's logs
(`logs/serve.err.log`) plus a `data/` snapshot for diagnosis. File issues with
the exact `git rev-parse HEAD` and the healthz output.
