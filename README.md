# Didi Jollof — Stock & Replenishment

Kitchen inventory for a multi-branch restaurant. A chef counts what is left,
builds tonight's list, and sends it to the owner for approval before the 8:00 PM
supplier cutoff.

Installable PWA on a FastAPI backend, deployed as a single Cloudflare Worker with
Postgres behind Hyperdrive.

**Live:** https://didi-jollof.elvistiburu17.workers.dev — sign in as
`chef@didijollof.com` / `didi1234`.

## Run it

```bash
make setup      # once — Python environment
make db-reset   # Docker Postgres + schema + demo data
make dev        # http://localhost:8787
make test       # backend suite, including branch isolation
```

Sign in as `chef@didijollof.com` / `didi1234` (Legon Outlet), or
`owner@didijollof.com` for an account mapped to all three branches.

Deployment: see [DEPLOY.md](DEPLOY.md). When something breaks:
[DEBUGGING.md](DEBUGGING.md).

## CI/CD

`.github/workflows/ci.yml` runs on every push and pull request:

1. **Tests** — against a disposable Postgres container. Migrations must apply
   cleanly from scratch *and* be a no-op on a second run, then the 74 tests run,
   then the Worker must build.
2. **Deploy** — only from `main`, and only after a human approves it in the
   `production` environment. Migrations are applied to Neon first, then the
   Worker, then a smoke test checks health, database reachability and the PWA
   shell. A failed smoke test prints the rollback command.

Repository secrets required: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
`NEON_DATABASE_URL` (the direct, non-pooler string).

## Migrations

```bash
make migrate-check    # what is pending
make migrate          # apply it
```

Each file runs in its own transaction and is recorded with a checksum, so a
migration cannot run twice and cannot be quietly edited after it has run. To
change something already applied, write a new file.

Migration files must not contain `BEGIN`/`COMMIT` — the runner owns the
transaction, and a `COMMIT` inside the file would end it early and defeat the
rollback-on-failure the runner exists to provide.

## Layout

| | |
|---|---|
| `api/` | FastAPI app and the Cloudflare Worker entrypoint |
| `migrations/` | `0001_init.sql` schema, `0002_seed.sql` demo data |
| `web/` | the PWA — no build step, served as static assets |
| `web/js/levels.js` | how "how much is left" becomes a number to buy |
| `scripts/dev.py` | local server putting the API and PWA on one origin |
| `prototype/` | the original design prototype this was built from |

## The chef's job, in one screen

The kitchen's question is narrow: **what do you need, and how much?** So that is
all the screen asks.

**Categories are collapsed sections, not a list.** A chef is standing at the meat
fridge, not reading a catalogue. Five category headers fit on one screen with no
scrolling at all; seventeen open rows do not. Open the section you are at, tap
what is low, close it.

**Tap a row to flag it; a quantity appears, prefilled.** It is a real number
field — typing `25` is instant when you know the number, and the big −/+ are
there when you are nudging. The suggestion is `par − last known stock`, so the
common case is no typing, but the amount is the chef's call and always visible.

**"None left" is a separate tap.** Being on the list means running low; being
completely out is different information and the owner needs to see it, so it is
one extra optional tap rather than a number to interpret.

**No prices anywhere on the chef's side.** The kitchen says what it needs; what
it costs is the owner's and logistics' business. The server still snapshots
`unit_price` on every line, so the owner side has it — it is simply not shown to
the chef. If a chef ever does know a price worth recording, that is a field to
add later, not a reason to show them all of them now.

**The outlet is never more than a glance away** — in the header, on the review
screen before sending, and on the confirmation. A chef maps to exactly one
branch, so the app does not ask where they are; it tells them, and there is no
branch switcher to send a list to the wrong kitchen. Owners, mapped to several
branches, still get one.

## How it is put together

**Branches are a security boundary, not a filter.** `user_branches` maps each
user to the branches they may act on. Every branch-scoped route runs through
`assert_branch_access` in `api/src/deps.py`, and `branch_id` is always a path
parameter — never inferred from a request body — so a route either authorises
the branch it touches or has no way to name one. Denial returns 404 rather than
403, so a chef cannot discover which other branches exist. There are tests for
this in both directions, read and write.

**Prices are snapshotted.** `order_items.unit_price` records what an item cost
when the request was submitted. Without it, a supplier price change would
silently rewrite what every past request cost and the history totals would
drift. Totals are always computed server-side; the client never sends an amount.

**Stock levels live per branch.** `branch_items` holds `current_stock`,
`min_level` and `par_level` for each item at each branch, because Legon and Osu
carry different amounts and different par levels. Status is derived, never
stored: `0` is out, below `min_level` is critical, below `par_level` is low.

**Submitting a request is also a stock count.** The chef has just told us what is
on the shelf, so `existing_stock` is written back to `branch_items` rather than
making them count twice.

**Auth avoids native dependencies, and dispatches per runtime.** `bcrypt`,
`passlib` and `PyJWT` are C-extension packages and unreliable on Pyodide, which
is what Python Workers run on. Session cookies are HMAC-SHA256 from `hmac` and
`hashlib`, which Pyodide does provide.

Password hashing needed more care: Pyodide has **no** `hashlib.pbkdf2_hmac`, so
the first deployment accepted no logins at all. `security.py` now uses the native
function where it exists and the runtime's Web Crypto on Workers, with both
pinned to the RFC 6070 vector so hashes stay portable between them.

**The layout contract — read this before touching `web/app.css`.** `#app` is
exactly `height: 100dvh` and never scrolls; all scrolling happens inside
`.scroll`. The bottom nav and the docked CTA are absolutely positioned against
`#app`, so they stay put. This was originally `min-height`, which let content
push the container taller than the screen and dragged the "fixed" nav hundreds
of pixels below the fold. Sizes are in `rem` so the layout grows with the
reader's text-size setting, and `env(safe-area-inset-*)` keeps the chrome clear
of the notch and home indicator. Verified at seven viewport sizes including
landscape and tablet.

**The app works offline.** The service worker caches the shell and the last
inventory response, so it opens and browses with no signal — verified with the
server stopped, not just with the browser's offline toggle. Submitting still
requires a connection and fails loudly; queued offline submits need conflict
handling that has not been designed yet.

## Still open

- **"Same as last time."** The old flow had a shortcut to reuse the previous
  request. It does not map cleanly onto reported levels, so it is gone from the
  UI; the API route and the query behind it still exist.
- **The owner side.** The schema, roles and approval columns are in place
  (`orders.reviewed_by`, `reviewed_at`, `review_note`, and an `approved` status),
  but there are no owner screens yet — that is the next piece.
- **Demo passwords.** All three seeded accounts use `didi1234` and are live on
  the deployed app now. Rotate them.
- **Fonts.** The Figma mock uses six typefaces including Segoe Script, a Windows
  system font. The build consolidates onto Gabarito and Geist, both already
  self-hosted here, so there is no CDN dependency on a kitchen phone.

---

## The brand system

_The sections below document `prototype/didi-jollof.html`, the design
artefact the app was built from. The palette and type decisions carry
over into `web/app.css`._

Sampled from the @didijollof grid, not invented.

| role | value | note |
|---|---|---|
| Poster ground | `#A82713` | one step deeper than their posted red — see below |
| Brand red | `#E8452B` | as posted |
| Yellow | `#F9C53C` | primary actions only |
| Cream | `#FFF3E2` | type on red |
| Ink | `#1C0F09` | type on yellow and on cards |
| Ground | `#F2F1EE` / `#000000` | neutral grouped surface, light / dark |
| Card | `#FFFFFF` / `#1A1A1C` | no borders |

**The one deliberate change.** Their signature yellow-on-red is **2.46:1**, which
works on Instagram because it is always poster-scale and fails immediately at UI
sizes. Dropping the hero ground to `#A82713` takes it to **4.41:1**, so the pairing
survives at every size. Every other text pair clears AA; ink-on-yellow is the
strongest at 11.66:1, which is why yellow became the action colour and nothing else is.

**Type.** Gabarito Black for poster headers (uppercase, −4% tracking, 88% leading),
Geist for everything operable. Both inlined as woff2 — no font CDN.

**Motion.** Two springs from Apple's damping/response model, identical in Figma and
on the web: `ζ 1.0 · 0.4s` for navigation, `ζ 0.8 · 0.3s` for the order sheet.

## Photography

`photos/` holds the four dish crops, taken from the Instagram grid screenshots.
Source resolution was ~575 px, served at 300 px — sharp at the 44–62 px the tiles
render at, but **re-export from the original camera files for production**.

To replace them: drop new `jollof.jpg` / `fried.jpg` / `waakye.jpg` / `chicken.jpg`
into `photos/` (square crops), then

```
cd src && python3 build.py --rebuild-photos
```

That re-encodes and rebuilds `prototype/didi-jollof.html`. In Figma the tiles are
named `Photo · Jollof` etc. — select one and paste an image to replace the fill.

## Rebuilding the prototype

```
cd src && python3 build.py
```

`didi.template.html` is the editable source; the build inlines the fonts and photos
so the output stays a single self-contained file. It verifies no placeholder and no
external URL survives, and fails loudly if either does.

## Prototype — still open

- **The logo is a redraw.** `Didi mark` in Figma is rebuilt from the posts, not the
  official file. It's a component, so dropping in the real SVG updates every instance.
- **Source screenshots** stay where you put them, `~/Documents/didi_pics/`.
- `Dish · jollof` etc. in Figma are the flat vector dish marks used before the
  photography landed. Unused now, kept as the fallback for any dish without a photo.
