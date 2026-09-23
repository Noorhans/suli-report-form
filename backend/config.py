# -*- coding: utf-8 -*-
"""
Central configuration for the problem-report form.

Keep enums here (not duplicated in the frontend or the DB layer) so the
category list only ever needs to change in one place. Internal keys are
plain ASCII (stored in the database); CATEGORIES maps them to the Kurdish
Sorani label shown to users.
"""

import os

# Internal key -> Kurdish (Sorani) label shown in the UI.
CATEGORIES = {
    "garbage": "پڕبوونی خڵتەدان",          # garbage bin overflow
    "pothole": "چاڵ لە شەقام",              # pothole
    "accident": "ڕووداوی هاتووچۆ",          # traffic accident
    "flooding": "لافاو / ئاوی وەستاو",       # flooding / standing water
    "power_line": "کێشەی کارەبا",           # downed power line / broken streetlight
    "blocked_road": "داخستنی ڕێگا",         # blocked road
    "other": "هیتر",                        # other
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "reports.db")
PHOTOS_DIR = os.path.join(DATA_DIR, "uploads", "photos")
AUDIO_DIR = os.path.join(DATA_DIR, "uploads", "audio")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB per file, generous for a phone photo/voice note

# Supabase Storage (optional). When set, uploaded photos/audio are stored
# there instead of the local disk - important on hosts like Render's free
# tier, whose local disk is wiped on every restart/redeploy (see db.py's
# note about the same problem for SQLite). Falls back to local disk when
# these aren't configured, so local/dev use with no Supabase project still
# works out of the box.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "media").strip()
USE_SUPABASE_STORAGE = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)
