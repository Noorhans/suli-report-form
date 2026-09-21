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
