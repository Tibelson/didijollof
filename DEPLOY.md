# Deploying to Cloudflare

Live: **https://didi-jollof.elvistiburu17.workers.dev**

One Worker serves both the API and the PWA, so there is a single deploy and a
single origin — no CORS, and the session cookie is first-party.

```
Browser (PWA)  ──►  Cloudflare Worker  ──►  Hyperdrive  ──►  Neon Postgres
  web/, static        FastAPI /api/*          (asyncpg)        (project
                                                               autumn-thunder-09698203)
```

## Deploying a change

```bash
make deploy       # cd api && uvx --from workers-py pywrangler deploy
```

**It must be `pywrangler`, not `wrangler`.** Plain `wrangler deploy` builds and
uploads successfully, then fails at startup with `No module named 'workers'`:
only pywrangler vendors the `workers-py` SDK into the bundle.

## Current setup

Already done, recorded here so it can be rebuilt:

| | |
|---|---|
| Neon project | `autumn-thunder-09698203`, branch `production`, database `neondb` |
| Hyperdrive | `97cdce5b976f4916abc6275c65b1a2e0` → Neon's **direct** (unpooled) host |
| Secret | `SESSION_SECRET`, 48 random bytes, set via `wrangler secret put` |
| Schema | `migrations/0001_init.sql` + `0002_seed.sql`, applied with `neon psql` |

The directory is linked to the Neon project (`.neon`), and `neon link` wrote
`.env.local` with `DATABASE_URL` / `DATABASE_URL_UNPOOLED`. **Both files are
gitignored** — `.env.local` holds the database password.

Use the **direct** Neon string for Hyperdrive, never the `-pooler` one.
Hyperdrive pools for you, and stacking two poolers breaks prepared statements.

## Rebuilding from scratch

```bash
neon link --project-id <id> --branch production -y   # writes .env.local
neon psql -- -v ON_ERROR_STOP=1 -f migrations/0001_init.sql
neon psql -- -v ON_ERROR_STOP=1 -f migrations/0002_seed.sql

cd api
set -a; . ../.env.local; set +a
npx wrangler hyperdrive create didi-postgres --connection-string="$DATABASE_URL_UNPOOLED"
# paste the returned id into wrangler.jsonc

openssl rand -base64 48 | npx wrangler secret put SESSION_SECRET
uvx --from workers-py pywrangler deploy
```

## Two things that bit during the first deploy

**1. No `hashlib.pbkdf2_hmac` on Pyodide.** Python Workers run on Pyodide, whose
`hashlib` ships `sha256`, `hmac` and friends but *not* `pbkdf2_hmac` — it is
OpenSSL-backed and absent from the Wasm build. `verify_password` caught the
`AttributeError` and returned `False`, so every login returned an entirely
ordinary 401 and the cause was invisible.

`security.py` now dispatches: native `pbkdf2_hmac` where it exists (CPython,
local and tests), the runtime's Web Crypto `crypto.subtle` on Workers. Both are
checked against the RFC 6070 vector in `tests/test_security.py`, so a hash
written by one verifies under the other.

Web Crypto is also *much* faster — **100,000 iterations in ~1 ms** on the Worker
versus ~40 ms in CPython, because it is native rather than interpreted.

**2. No randomness during startup.** Workers snapshot startup state and replay it
across instances, so entropy at import time would produce the same "random"
value everywhere. A module-level `hash_password(...)` call fails outright with
`OSError: Randomness is not allowed while a Worker is starting`. Anything needing
`secrets` or `os.urandom` must run inside a request.

## stock.didijollof.com — blocked, and why

The domain is registered and already on Cloudflare nameservers, but **the zone
lives on a different Cloudflare account** from the one this Worker is deployed
to. Attaching the route fails with:

```
The zone "didijollof.com" does not exist on your account. [code: 10083]
```

The apex currently serves an unrelated site (Auda Foods), which is consistent
with the zone belonging to that project's account.

Two ways forward:

1. **Move the zone** into `elvistiburu17@gmail.com`'s account (Cloudflare →
   Add a Site, then re-point the Namecheap nameservers if they change). This
   moves the whole domain, including whatever serves the apex.
2. **Deploy the Worker into the account that already holds the zone** —
   `wrangler login` as that account, then deploy. The Hyperdrive config and the
   `SESSION_SECRET` would need recreating there.

Either way, uncomment the `routes` block in `api/wrangler.jsonc` afterwards.

> **Careful:** adding `routes` turns the `workers.dev` URL *off* unless
> `"workers_dev": true` is also set. That took the app offline during this
> change; the flag is now pinned on in the config so it cannot happen silently
> again.

## Before real users

- **Rotate the demo passwords.** `0002_seed.sql` creates three accounts all using
  `didi1234`, and they are live right now. Change them, or drop the seed users
  and create real ones.
- **Consider raising `DEFAULT_ITERATIONS`** in `api/src/security.py` from 100,000
  toward OWASP's 600,000. At ~1 ms per 100k on Workers that is roughly 6 ms —
  affordable. Existing hashes keep working because the cost is read from each
  stored hash, and `needs_rehash` upgrades them on next login. Regenerate
  `_DUMMY_HASH` to match; `test_dummy_hash_cost_matches_real_hashes` enforces it.
- **Map real users to branches.** `user_branches` is the security boundary; a
  user with no row there can reach nothing, which is the correct default.

## Local development

```bash
make setup      # once
make db-reset   # Docker Postgres + schema + seed
make dev        # http://localhost:8787
make test       # 61 tests
```

To run on the real Workers runtime against the Docker database:

```bash
cd api && uvx --from workers-py pywrangler dev
```
