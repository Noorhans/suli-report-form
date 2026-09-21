# ڕاپۆرتکردنی کێشە — Report a Problem (step 1: form + SQL storage)

فۆرمێکی کوردی (سۆرانی) بۆ ڕاپۆرتکردنی کێشەکانی شار (چاڵ، خڵتەدان، لافاو، هتد)
بە وێنە و/یان دەنگ و شوێنی GPS، پاشەکەوتکراو لە بنکەدراوەیەکی SQL.

A Kurdish (Sorani) form for citizens to report city problems (potholes,
overflowing garbage, flooding, etc.) with an optional photo and/or a voice
recording, plus automatic GPS location. Every submission is stored as a row
in a SQL database. This is deliberately just the data collection step — no
AI analysis is wired in yet.

Built for the AI Hackathon by Foundation Hub — **October 8–9, 2026**.

## How a report works

- The citizen does **not** pick a category — there's no dropdown on the
  form. Every report is stored as unclassified (`category = NULL`); the
  `backend/config.py` category list still exists and is used by the
  dashboard, but it's meant for a later step (an AI classification pass
  over the description/photo/audio, or manual triage) rather than asking
  the reporter to self-classify.
- Location (GPS lat/lng) is captured automatically from the browser on
  page load; the form still submits if the user denies/lacks location.
- At least one of: typed description, photo, or voice recording is
  required (enforced by the API and by a `CHECK` constraint in the DB).
- Voice notes are recorded in-browser (`MediaRecorder`) and uploaded as a
  real audio file — nothing is simulated. There is no speech-to-text yet;
  that's a follow-up step once this collection pipeline is proven out.

## Project layout

```
backend/
  main.py     FastAPI app: API routes + serves the frontend
  db.py       DB schema + queries (SQLite locally, Postgres in production)
  config.py   Category list (single source of truth) + storage paths
frontend/
  index.html      The public Kurdish report form
  dashboard.html  Your private view of submitted data (see below)
data/         Created automatically: reports.db + uploads/photos, uploads/audio
Procfile, render.yaml   Deployment config for Render (see "Publish it" below)
```

## Run it locally

Requires Python 3.9+.

```bash
./run.sh
```

(This creates a virtualenv, installs dependencies, and starts the server
at http://localhost:8000 — open that in a browser. Data goes to
`data/reports.db`, a local SQLite file, unless you set `DATABASE_URL`.)

Or manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Your dashboard

Open **`/dashboard.html`** (e.g. `http://localhost:8000/dashboard.html`,
or `https://your-deployed-url/dashboard.html` once published) — a private
page (not linked from the public form) showing: total reports, how many
have a photo/voice note/GPS location, a bar chart of reports by category,
a 14-day submissions sparkline, and a full table of every report with
playable audio, viewable photos, and a Google Maps link for each location.
There's also a "Download CSV" button there (same as `/api/reports/export.csv`).

It has no password — anyone with the exact URL can view it. That's fine
for a hackathon, but don't post the `/dashboard.html` link in the same
place you post the public form link.

## Publish it (a real public URL)

To let other people actually submit reports from their own phones, the
app needs to run somewhere public — not just on your laptop. Two tiers:

**Quick test (minutes, temporary):** run `./run.sh` and expose it with a
tunnel (`ngrok http 8000`, or `cloudflared tunnel --url http://localhost:8000`
for a no-signup option). Good for testing with a few people right now;
the link dies the moment you close your laptop or stop the tunnel — not
suitable for a multi-week data collection push.

**Actually shareable (stays up, ~15 min setup):** deploy to a free host
with a real database behind it. Recommended combo, using pieces that are
already wired up in this project:

1. **Database — Supabase (free, doesn't expire):**
   Create a free project at supabase.com → Project Settings → Database →
   copy the "Connection string" (URI, "Transaction pooler" mode). That's
   your `DATABASE_URL`.
   *(Render also offers a free Postgres, but it auto-deletes after 30
   days — fine if you only need it through the hackathon, but Supabase's
   free tier just doesn't expire, so it's the safer default.)*

2. **App hosting — Render (free web service):**
   Push this project to a GitHub repo → on render.com choose **New →
   Blueprint**, point it at the repo (it will pick up `render.yaml`
   automatically) → when prompted, set the `DATABASE_URL` env var to the
   Supabase connection string from step 1 → deploy. Render gives you a
   public `https://your-app.onrender.com` URL — that's what you share.

   Free-tier caveats worth knowing: the service spins down after 15
   minutes with no traffic and takes about a minute to wake back up on
   the next visit (a normal free-tier trade-off, not a bug), and its
   local disk is wiped on every restart/redeploy — which is exactly why
   step 1 (a real Postgres via `DATABASE_URL`) matters: without it,
   submitted reports would vanish whenever the service goes idle.

Once `DATABASE_URL` is set, `backend/db.py` automatically uses Postgres
instead of the local SQLite file — no other code changes needed.

## API

- `GET  /api/config` — category list (key → Kurdish label). Not used by
  the public form (no category field there); the dashboard uses it to
  show readable labels if/when reports get classified.
- `POST /api/reports` — multipart form: `description`, `lat`, `lng`,
  `accuracy`, `photo` (file), `audio` (file) — all optional, but at least
  one of description/photo/audio is required. `category` is also accepted
  (optional, for a future admin/classification tool) but the public form
  never sends it. Returns the created report as JSON.
- `GET  /api/reports` — list stored reports (most recent first). Powers
  the dashboard table.
- `GET  /api/reports/stats` — aggregate counts (total, by category, by
  day, with photo/audio/location). Powers the dashboard charts.
- `GET  /api/reports/export.csv` — flat CSV export of everything stored.
- `GET  /media/{photos|audio}/{filename}` — serves an uploaded file.
- `GET  /api/health` — `{"status": "ok", "reports": <count>}`.

## Database

One `reports` table — SQLite locally by default, or Postgres when
`DATABASE_URL` is set (see "Publish it" above):

| column             | type    | notes                                     |
|--------------------|---------|--------------------------------------------|
| id                 | INTEGER | primary key                                |
| created_at         | TEXT    | ISO 8601 UTC                               |
| category           | TEXT    | nullable — unset until a future classification step |
| description        | TEXT    | nullable                                   |
| lat, lng           | REAL    | nullable (GPS may be denied/unavailable)   |
| location_accuracy  | REAL    | meters, from the browser Geolocation API   |
| photo_path         | TEXT    | relative path under `data/`, nullable      |
| audio_path         | TEXT    | relative path under `data/`, nullable      |
| status             | TEXT    | defaults to `new`                          |

Inspect the local SQLite file directly any time:

```bash
sqlite3 data/reports.db "select id, created_at, category, lat, lng from reports;"
```

## Known limits / next steps

- No AI triage/transcription yet — this step is only "collect the report
  and store it reliably." Wiring Kurdish speech-to-text + an LLM
  extraction step onto the stored audio is the natural next step.
- No auth, no spam/duplicate detection. The dashboard has no password —
  see "Your dashboard" above.
- CORS is wide open (`*`) since the form is meant to be shared broadly for
  a demo; tighten this before any real production use.
- Category and location values only ever need to change in
  `backend/config.py`.
