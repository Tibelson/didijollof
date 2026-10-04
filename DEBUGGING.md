# When something goes wrong

## The short version

Every response carries a reference — `X-Request-Id`, repeated in the body of any
error. When a chef says "it failed", the useful question is:

> **What did the red message say underneath?**

That is a 12-character reference. With it:

```bash
make logs            # live
# then search the output for the reference
```

Without it, you are looking for a needle in a day of logs.

## Watching logs live

```bash
make logs                    # everything
make logs-errors             # errors only
```

Both wrap `wrangler tail`. It streams from the moment you start it — it cannot
show you the past. For history, use the Workers dashboard:
**Workers & Pages → didi-jollof → Logs**, which retains recent requests and lets
you filter on the fields below.

## What the logs look like

One JSON object per line, so the dashboard can filter on real fields rather than
you grepping prose:

```json
{"ts":1791118024.76,"level":"error","event":"request.failed",
 "request_id":"e5cfea8e9381","method":"POST",
 "path":"/api/branches/1/requests","duration_ms":812.4,
 "error_type":"UniqueViolationError","error":"duplicate key …",
 "traceback":"…"}
```

Events you will see:

| event | meaning |
|---|---|
| `request.failed` | unhandled exception — this is a bug, traceback included |
| `request.error` | the route returned 5xx deliberately |
| `request.rejected` | 4xx: wrong password, wrong branch, bad payload. Usually not a bug |
| `request.invalid` | malformed body; lists which fields, never their values |
| `request.slow` | over 1.5s |
| `client.error` | a JavaScript error on someone's phone |
| `config.missing` | a secret or binding is not set — the deployment is wrong |
| `health.db_unreachable` | the Worker is up but Postgres is not answering |

Successful fast requests are **not** logged. A line per healthy request buries
the failures.

Nothing logs passwords, session cookies or request bodies.

## Errors on a phone

Browser failures used to be invisible — nothing reaches the server and nobody is
opening a developer console mid-service. `web/js/app.js` now catches `error` and
`unhandledrejection` and beacons them to `/api/client-error`, where they appear
as `client.error` with the screen and stack.

Reported once per unique message per session, capped at ten, so a render loop
cannot flood the log.

## Triage

**"The app won't load at all"**

```bash
curl -s https://didi-jollof.elvistiburu17.workers.dev/api/health
```

- `{"status":"ok"}` → the Worker is fine; the problem is the browser or the
  network. Ask them to force-close and reopen the installed app (the service
  worker caches the shell, and a stale one survives a normal refresh).
- `error code: 1101` → the Python Worker threw at startup. `make logs` will show
  it. **A redeploy clears a transient Pyodide init failure** — this has happened
  once, unrelated to any code change.
- Anything else → check the Cloudflare status page before digging.

**"It says the server is not configured"**

A secret or binding is missing. `event = config.missing` names which one.

```bash
cd api && npx wrangler secret list
```

**"Nothing loads but the app opens"**

```bash
curl -s https://didi-jollof.elvistiburu17.workers.dev/api/health/db
```

`503` means Hyperdrive cannot reach Neon. Check Neon is not suspended, then that
the Hyperdrive config still points at the **direct** (non-pooler) host:

```bash
cd api && npx wrangler hyperdrive get 97cdce5b976f4916abc6275c65b1a2e0
```

**"A chef sent a list and it vanished"**

Requests are never partially written — creation is one transaction. Check it
exists and which branch it is on:

```bash
neon psql -- -c "SELECT id, branch_id, user_id, status, created_at
                   FROM orders ORDER BY created_at DESC LIMIT 10;"
```

If it is on a branch they did not expect, look at `user_branches`: that mapping
is what decides which kitchen a chef reports for.

## Rolling back

Cloudflare keeps every version.

```bash
cd api
npx wrangler versions list
npx wrangler rollback --message "why"
```

**Code rolls back; the database does not.** If the bad deploy ran a migration,
rolling the Worker back leaves the new schema in place. Write a forward
migration rather than trying to reverse one.

## Migrations

```bash
python3 scripts/migrate.py --check     # what is pending
python3 scripts/migrate.py             # apply it
```

Each file runs in its own transaction and is recorded with a checksum, so a
migration cannot run twice and cannot be edited after the fact without the
runner noticing. To change something already applied, write a new file.

## The one that bit us

The test suite runs `DROP SCHEMA public CASCADE` before **every** test. It was
once pointed at the production Neon database by an ambient `DATABASE_URL` and
wiped it.

`api/tests/conftest.py` now reads `DIDI_TEST_DATABASE_URL` — not `DATABASE_URL`
— and refuses to run unless the host is local. If you ever genuinely need to
override that, `DIDI_ALLOW_DESTRUCTIVE_TESTS=1` exists, and you should be sure.
