# Search-first web map

## What it is

A FastAPI server (`office serve`) that hosts a vanilla-JS
single-page app rendering the floor SVGs and the seat assignments
on top. Search is the primary interaction — type a name / seat ID
/ cluster letter and the matching seats highlight on the map. URLs
are deep-linkable: `/offices/<office>/floors/<floor>?seat=5-T-01`
takes you straight to the highlighted seat.

The frontend is **no-build**. Plain HTML + ES module + CSS, served
as-is by the FastAPI `StaticFiles` mount. Fuse.js (vendored) does
the fuzzy search.

## Why

Slack `/whereis` covers the 95% case (one-off lookup), but humans
also want to skim the map — "who sits in cluster T?", "is that
window seat free?". The web map is a secondary surface tuned for
that browsing flow. Search-first means it never replaces the Sheet
or the Slack command — they each own their UX niche.

The no-build choice is deliberate (Stage 5): it keeps the repo
free of npm tooling and means the frontend is auditable as plain
text. Trade-off: no TypeScript, no module bundler. At the size of
this app (~500 LOC of JS) the trade-off pays off.

## Install

```bash
pip install office-cli[web]
```

The package imports without `fastapi` / `uvicorn`; only `office
serve` lazy-imports them. Optional `[sso]` extras layer on top —
see [Roles](./roles.md).

## Configure

The web layer reads through the same `data/offices.yaml` as the
CLI; no extra config required for the basic map. SSO is
opt-in via env (see [Roles](./roles.md)).

```bash
office serve                                       # localhost:8000
office serve --host 0.0.0.0 --port 8080 --data-dir data
office serve --port 0                              # OS-picked port (handy for tests)
```

Behind a reverse proxy with TLS termination on the proxy side, set
`OIDC_COOKIE_SECURE=false` so the session cookie isn't dropped on
the HTTP backplane.

## Use

```bash
office serve --port 8000 &
open http://127.0.0.1:8000/                         # redirects to first floor
open http://127.0.0.1:8000/offices/tlv/floors/tlv-floor-5
open "http://127.0.0.1:8000/offices/tlv/floors/tlv-floor-5?seat=5-T-01"
open "http://127.0.0.1:8000/offices/tlv/floors/tlv-floor-5?asOf=2026-07-15"
```

Search box accepts seat IDs, emails, cluster letters, floor IDs,
or fragments. Click a result → the SVG highlights it + the URL
updates. Keyboard: `Enter` / `Space` on a focused result selects
it; `popstate` (browser back/forward) syncs.

## How it works

### Module layout

| File                                      | Role                                                          |
| ----------------------------------------- | ------------------------------------------------------------- |
| `office_cli/cli/_commands/serve.py`       | `office serve` verb; lazy fastapi import; uvicorn.run.        |
| `office_cli/server/__init__.py`           | Re-exports `build_app`, `run_server`.                         |
| `office_cli/server/_app.py`               | `build_app(service, *, data_dir, oidc, roles)`.               |
| `office_cli/server/_routes.py`            | API + SPA shell + redirect routes.                            |
| `office_cli/server/_auth.py`              | OIDC + SessionMiddleware (Stage 7 — see [Roles](./roles.md)). |
| `office_cli/server/_serve.py`             | `run_server(app, host, port)` — lazy uvicorn.run.             |
| `office_cli/server/static/index.html`     | SPA shell (`<header>` / `<main>` / `<aside>`).                |
| `office_cli/server/static/app.js`         | Vanilla ES module: fetch + render + search + URL state.       |
| `office_cli/server/static/app.css`        | Map + sidebar + responsive layout.                            |
| `office_cli/server/static/vendor/fuse.js` | Vendored Fuse.js for fuzzy search.                            |

### Endpoints

| Endpoint                            | Returns                                                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `GET /api/offices`                  | All offices + floors with `id` + `status`.                                                                    |
| `GET /api/floors/{id}?as_of=&asOf=` | Merged seat list (auto-vacated, redacted, date-filtered) + `svg_url` + `user`.                                |
| `GET /svgs/{name}.svg`              | Static-mount of the operator-traced floor SVG.                                                                |
| `GET /static/...`                   | Static-mount of `office_cli/server/static/`.                                                                  |
| `GET /`                             | 302 to the first office's first floor.                                                                        |
| `GET /floors/{id}?seat=...`         | 307 to `/offices/<office>/floors/<id>?seat=…` (Slack deep-link entry).                                        |
| `GET /offices/{office}/floors/{id}` | SPA shell (HTML). Validates office+floor pair, redirects to `/auth/login` if SSO enabled and unauthenticated. |

### Hidden-seat redaction

Stage 7 moved the redaction policy into the **service layer** —
when called with `role="viewer"`, `SeatService` clears
`employee_email` and `notes` on `hidden=TRUE` rows and sets
`redacted=True` on the `Assignment`. The web's `_redact()` helper
maps the view-time state to the JSON shape:

| Service state               | API JSON                                                      |
| --------------------------- | ------------------------------------------------------------- |
| `redacted=True`             | `employee_email: "(private)"`, `notes: ""`, `redacted: true`. |
| `hidden=True`, not redacted | Pass-through (editor / planning view).                        |
| `hidden=False`              | Pass-through.                                                 |

The frontend uses the `redacted` flag (not `hidden`) to decide
whether to render `"(private)"` vs `"(vacant)"`.

### URL state

The SPA reads `globalThis.location` on load and on `popstate`. The
URL is **canonical state** — `app.js` syncs UI ↔ URL via
`history.pushState`. Three URL params:

- `?seat=<seat_id>` — highlight + scroll to seat. Round-trips
  through the SSO redirect path (the redirect URL-encodes the
  full `next`).
- `?asOf=<YYYY-MM-DD>` — render the map as of that date. Also
  accepted server-side as `?as_of=` for direct API callers.
- (Path) `/offices/<id>/floors/<id>` — the active floor.

### XSS posture

API-derived strings land in the DOM via `createElement` +
`textContent`. The SVG (operator-supplied) is parsed via
`DOMParser` and **sanitized** before insertion: `<script>` and
`<foreignObject>` elements are stripped, `on*` attributes
removed, `href="javascript:…"` cleared. Path-tainted fetches use
per-endpoint helpers with hardcoded URL prefixes + regex-validated
tokens; URLs are never built from a generic `path` string.

### Search

Fuse.js indexes `seat_id`, `employee_email`, `cluster`, `floor`.
Threshold 0.35, ignoreLocation. Debounced 150 ms. Query → top 50
results in the sidebar.

## Limits + roadmap

- **No editor in the SPA.** Sheets / DynamoDB are the editors; the
  web is read-only. Editor mode could land later but isn't a v1
  goal.
- **No native mobile app.** The CSS is responsive (sidebar
  collapses below 800 px); a native app is out of scope.
- **Hot-desk / desk booking UI is out of v1.**
- **No multi-floor view.** One floor per page; switch via the
  picker. The deep-link button on Slack lands you on the right
  floor automatically.
- **No real-time updates.** Reads are TTL-cached on the backend;
  the SPA refetches on floor switch / asOf change. WebSocket-driven
  live updates would land Stage-9+ if the use case shows up.

## Related

- [Architecture stages — Stage 5](../architecture.md) — PR-by-PR
  record.
- [SSO + roles](./roles.md) — how the SPA shell decides whether to
  redirect anonymous browsers.
- [Effective-date windows](./effective-dates.md) — `?asOf=` URL
  semantics.
- [Slack `/whereis`](./slack.md) — source of the deep-link
  button that lands on this map.
