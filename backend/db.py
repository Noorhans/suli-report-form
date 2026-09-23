# -*- coding: utf-8 -*-
"""
Storage layer for reports.

Works against SQLite (zero-setup local/demo use — the default) or a real
Postgres server (set the DATABASE_URL env var, e.g. to a free Supabase
project) with the same code, via SQLAlchemy Core. This matters once the
form is deployed publicly: most free app-hosting tiers (Render, Railway,
etc.) wipe local disk on every restart/redeploy, so SQLite on those hosts
silently loses data — pointing DATABASE_URL at a real Postgres server
avoids that.
"""

import csv
import io
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from config import DB_PATH, CATEGORIES

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Render/Heroku-style URLs sometimes use the old "postgres://" scheme;
    # SQLAlchemy's psycopg2 driver wants "postgresql://".
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    ENGINE_URL = DATABASE_URL
    IS_POSTGRES = True
else:
    ENGINE_URL = f"sqlite:///{DB_PATH}"
    IS_POSTGRES = False

engine = create_engine(ENGINE_URL, future=True)

if IS_POSTGRES:
    ID_COLUMN = "id SERIAL PRIMARY KEY"
else:
    ID_COLUMN = "id INTEGER PRIMARY KEY AUTOINCREMENT"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS reports (
    {ID_COLUMN},
    created_at      TEXT NOT NULL,
    category        TEXT,
    description     TEXT,
    lat             DOUBLE PRECISION,
    lng             DOUBLE PRECISION,
    location_accuracy DOUBLE PRECISION,
    location_label  TEXT,
    photo_path      TEXT,
    audio_path      TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    CHECK (description IS NOT NULL OR photo_path IS NOT NULL OR audio_path IS NOT NULL)
);
""" if IS_POSTGRES else """
CREATE TABLE IF NOT EXISTS reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    category        TEXT,
    description     TEXT,
    lat             REAL,
    lng             REAL,
    location_accuracy REAL,
    location_label  TEXT,
    photo_path      TEXT,
    audio_path      TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    CHECK (description IS NOT NULL OR photo_path IS NOT NULL OR audio_path IS NOT NULL)
);
"""


def init_db():
    with engine.begin() as conn:
        conn.execute(text(SCHEMA))
    # Best-effort migration for databases created before location_label existed.
    # Run in its own transaction so a "column already exists" error here can
    # never roll back the CREATE TABLE above.
    try:
        with engine.begin() as conn:
            if IS_POSTGRES:
                conn.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS location_label TEXT"))
            else:
                conn.execute(text("ALTER TABLE reports ADD COLUMN location_label TEXT"))
    except Exception:
        pass


def insert_report(category, description, lat, lng, accuracy, location_label, photo_path, audio_path):
    created_at = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO reports
                    (created_at, category, description, lat, lng, location_accuracy, location_label,
                     photo_path, audio_path, status)
                VALUES
                    (:created_at, :category, :description, :lat, :lng, :accuracy, :location_label,
                     :photo_path, :audio_path, 'new')
                RETURNING id
                """
            ),
            {
                "created_at": created_at, "category": category, "description": description,
                "lat": lat, "lng": lng, "accuracy": accuracy, "location_label": location_label,
                "photo_path": photo_path, "audio_path": audio_path,
            },
        ).fetchone()
        return row[0], created_at


def list_reports(limit=200, offset=0):
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, created_at, category, description, lat, lng, location_accuracy, location_label,
                       photo_path, audio_path, status
                FROM reports
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {"limit": limit, "offset": offset},
        ).mappings().all()
        return [dict(r) for r in rows]


def update_report_media(report_id, photo_path=None, audio_path=None):
    """Overwrites photo_path and/or audio_path on an existing report - used
    by the admin "re-attach media" endpoint to recover a report whose photo
    was lost before Supabase Storage was wired in (see storage.py). Only
    columns actually passed in are touched. Returns True if a row matched."""
    sets = []
    params = {"id": report_id}
    if photo_path is not None:
        sets.append("photo_path = :photo_path")
        params["photo_path"] = photo_path
    if audio_path is not None:
        sets.append("audio_path = :audio_path")
        params["audio_path"] = audio_path
    if not sets:
        return False
    with engine.begin() as conn:
        result = conn.execute(
            text(f"UPDATE reports SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        return result.rowcount > 0


def count_reports():
    with engine.begin() as conn:
        return conn.execute(text("SELECT COUNT(*) FROM reports")).scalar()


def stats():
    """Aggregate counts for the dashboard."""
    with engine.begin() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM reports")).scalar()
        with_photo = conn.execute(
            text("SELECT COUNT(*) FROM reports WHERE photo_path IS NOT NULL")
        ).scalar()
        with_audio = conn.execute(
            text("SELECT COUNT(*) FROM reports WHERE audio_path IS NOT NULL")
        ).scalar()
        with_location = conn.execute(
            text("SELECT COUNT(*) FROM reports WHERE lat IS NOT NULL")
        ).scalar()

        by_category_rows = conn.execute(
            text("SELECT category, COUNT(*) AS n FROM reports GROUP BY category ORDER BY n DESC")
        ).all()
        by_category = [
            {
                "category": r[0] or "unclassified",
                "label": CATEGORIES.get(r[0], "پۆلێنی نەکراو") if r[0] else "پۆلێنی نەکراو",
                "count": r[1],
            }
            for r in by_category_rows
        ]

        # last 14 days, oldest -> newest, using the date portion of the ISO created_at string
        date_expr = "substr(created_at, 1, 10)"
        by_day_rows = conn.execute(
            text(f"""
                SELECT {date_expr} AS day, COUNT(*) AS n
                FROM reports
                GROUP BY day
                ORDER BY day DESC
                LIMIT 14
            """)
        ).all()
        by_day = sorted([{"day": r[0], "count": r[1]} for r in by_day_rows], key=lambda x: x["day"])

    return {
        "total": total,
        "with_photo": with_photo,
        "with_audio": with_audio,
        "with_location": with_location,
        "by_category": by_category,
        "by_day": by_day,
    }


def export_csv():
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, created_at, category, description, lat, lng, location_accuracy, location_label,
                       photo_path, audio_path, status
                FROM reports
                ORDER BY id ASC
                """
            )
        ).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "created_at", "category", "category_label", "description",
         "lat", "lng", "location_accuracy", "location_label", "photo_path", "audio_path", "status"]
    )
    for r in rows:
        category_label = CATEGORIES.get(r[2], "پۆلێنی نەکراو") if r[2] else "پۆلێنی نەکراو"
        writer.writerow([
            r[0], r[1], r[2], category_label, r[3],
            r[4], r[5], r[6], r[7], r[8], r[9], r[10],
        ])
    return buf.getvalue()
