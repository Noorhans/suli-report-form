# -*- coding: utf-8 -*-
"""
FastAPI app: serves the Kurdish report form and stores submissions in SQLite.

Run with:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Then open http://localhost:8000 in a browser.
"""

import os
import uuid
from typing import Optional

from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import db
import geocode
import storage
from config import (
    CATEGORIES, DATA_DIR, PHOTOS_DIR, AUDIO_DIR, MAX_UPLOAD_BYTES, BASE_DIR,
    USE_SUPABASE_STORAGE,
)

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(title="Report a Problem API")

# Wide open for the hackathon demo — the form is meant to be shared widely.
# Tighten this (specific origins) before any real production use.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    os.makedirs(PHOTOS_DIR, exist_ok=True)
    os.makedirs(AUDIO_DIR, exist_ok=True)
    db.init_db()


@app.get("/api/config")
def get_config():
    return {"categories": CATEGORIES}


@app.get("/api/health")
def health():
    return {"status": "ok", "reports": db.count_reports()}


async def _read_capped(upload: UploadFile) -> bytes:
    """Reads an UploadFile fully into memory, enforcing MAX_UPLOAD_BYTES."""
    chunks = []
    size = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _store_upload(upload: UploadFile, subdir: str, local_dir: str) -> str:
    """Saves an uploaded file to Supabase Storage when configured (preferred -
    it persists across restarts/redeploys), otherwise falls back to local
    disk for local/dev use without a Supabase project set up. Returns what
    gets stored in photo_path/audio_path: a full public URL for Supabase
    Storage, or a path relative to DATA_DIR for local disk."""
    data = await _read_capped(upload)

    if USE_SUPABASE_STORAGE:
        try:
            return await storage.upload_bytes(data, upload.filename, subdir)
        except Exception as e:
            raise HTTPException(502, "Could not save the uploaded file. Please try again.") from e

    ext = os.path.splitext(upload.filename or "")[1][:10]
    fname = f"{uuid.uuid4().hex}{ext}"
    dest = os.path.join(local_dir, fname)
    with open(dest, "wb") as out:
        out.write(data)
    return os.path.relpath(dest, DATA_DIR)


@app.post("/api/reports")
async def create_report(
    category: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    lat: Optional[float] = Form(None),
    lng: Optional[float] = Form(None),
    accuracy: Optional[float] = Form(None),
    location_label: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
):
    # Category is no longer chosen by the citizen in the form — it's left
    # unset here and is meant to be filled in later (e.g. by an AI
    # classification step reading the description/photo/audio), or by
    # someone triaging reports. If a caller does pass one (e.g. a future
    # admin tool), it's still validated against the known list.
    category = (category or "").strip() or None
    if category is not None and category not in CATEGORIES:
        raise HTTPException(400, f"Unknown category '{category}'")

    description = (description or "").strip() or None
    location_label = (location_label or "").strip() or None

    # A photo, a coordinate (manually copied by the citizen from Google
    # Maps - never read automatically from the device's GPS), and a
    # street/neighborhood name are all always required, plus either a
    # written description or a voice recording (or both). Enforced here
    # too, not just in the frontend, since the frontend check can be
    # bypassed.
    has_photo = bool(photo and photo.filename)
    has_audio = bool(audio and audio.filename)
    if not has_photo:
        raise HTTPException(400, "A photo is required for every report.")
    if lat is None or lng is None:
        raise HTTPException(400, "A coordinate copied from Google Maps is required for every report.")
    if not location_label:
        raise HTTPException(400, "A street or neighborhood name is required for every report.")
    if not description and not has_audio:
        raise HTTPException(
            400,
            "Along with the photo, either a written description or a voice recording is required.",
        )

    photo_path = await _store_upload(photo, "photos", PHOTOS_DIR) if photo and photo.filename else None
    audio_path = await _store_upload(audio, "audio", AUDIO_DIR) if audio and audio.filename else None

    report_id, created_at = db.insert_report(
        category, description, lat, lng, accuracy, location_label, photo_path, audio_path
    )

    return JSONResponse(
        {
            "id": report_id,
            "created_at": created_at,
            "category": category,
            "category_label": CATEGORIES.get(category, "پۆلێنی نەکراو"),
            "description": description,
            "lat": lat,
            "lng": lng,
            "location_label": location_label,
            "photo_path": photo_path,
            "audio_path": audio_path,
        },
        status_code=201,
    )


@app.get("/api/geocode")
async def get_geocode(lat: float, lng: float):
    """Reverse-geocode a point into a human-readable place name, used to
    pre-fill (but never lock) the location field in the report form."""
    label, source = await geocode.reverse_geocode(lat, lng)
    return {"label": label, "source": source}


@app.patch("/api/reports/{report_id}/media")
async def update_report_media(
    report_id: int,
    photo: Optional[UploadFile] = File(None),
    audio: Optional[UploadFile] = File(None),
):
    """Admin recovery endpoint: re-attaches a photo and/or audio recording to
    an existing report. Exists for cases like a report whose photo was lost
    when it was still being saved to Render's non-persistent local disk
    (before Supabase Storage was wired in) - the original submitter's photo
    can be re-uploaded here and it'll be saved to Supabase Storage and
    linked back onto that same report id, with everything else about the
    report (description, location, timestamp) left untouched."""
    if not (photo and photo.filename) and not (audio and audio.filename):
        raise HTTPException(400, "Provide a photo and/or an audio file to attach.")

    photo_path = await _store_upload(photo, "photos", PHOTOS_DIR) if photo and photo.filename else None
    audio_path = await _store_upload(audio, "audio", AUDIO_DIR) if audio and audio.filename else None

    updated = db.update_report_media(report_id, photo_path=photo_path, audio_path=audio_path)
    if not updated:
        raise HTTPException(404, f"No report with id {report_id}")

    return {"id": report_id, "photo_path": photo_path, "audio_path": audio_path}


@app.get("/api/reports")
def get_reports(limit: int = 200, offset: int = 0):
    return {"total": db.count_reports(), "reports": db.list_reports(limit, offset)}


@app.get("/api/reports/stats")
def get_stats():
    return db.stats()


@app.get("/api/reports/export.csv")
def export_csv():
    return PlainTextResponse(db.export_csv(), media_type="text/csv")


@app.get("/media/{kind}/{filename}")
def get_media(kind: str, filename: str):
    if kind not in ("photos", "audio"):
        raise HTTPException(404)
    path = os.path.join(DATA_DIR, "uploads", kind, filename)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)


# Serve the Kurdish frontend (index.html + any static assets) at "/".
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
