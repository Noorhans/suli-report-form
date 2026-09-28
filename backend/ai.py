# -*- coding: utf-8 -*-
"""
AI triage: sends a report's photo + description/location to Claude
(Anthropic API, multimodal) and gets back a structured triage verdict -
category, a 1-5 severity/priority score, a plain-English summary, and the
city department it should be routed to. This is what turns "a form that
saves rows to a database" into an actual AI platform: every report gets an
instant, structured assessment the moment it's submitted (see main.py's
create_report), and existing reports can be triaged retroactively via
POST /api/reports/{id}/triage or in bulk via POST /api/reports/triage-all
- useful for backfilling reports collected before this feature existed.

Uses plain httpx against the Messages API directly (same pattern as
geocode.py) rather than the anthropic SDK, to avoid an extra dependency.

Degrades gracefully everywhere: with no ANTHROPIC_API_KEY set (e.g. local
dev, or before it's configured on Render), or if the API call fails/times
out/returns something unparseable, this returns a "not run" result rather
than raising - a citizen's report must always save successfully even when
AI triage can't complete.
"""

import base64
import json
import logging
import os
import re

import httpx

from config import CATEGORIES, DATA_DIR

logger = logging.getLogger("ai")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929").strip()
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_HTTP_TIMEOUT = 30.0

# City departments a report can be routed to - kept here (not config.py)
# since this is specifically the AI routing vocabulary, not a citizen-facing
# category.
DEPARTMENTS = [
    "Roads & Maintenance", "Sanitation", "Electricity Board",
    "Traffic Police", "Water & Drainage", "General/Other",
]

_SYSTEM_PROMPT = (
    "You are a municipal triage assistant for Sulaymaniyah, Iraq. You are shown a "
    "citizen-submitted photo of a street problem, an optional written description "
    "(may be in Kurdish, Arabic, or English), and the neighborhood name. "
    "Reply with ONLY a single JSON object (no other text, no markdown fences) with "
    "exactly these keys:\n"
    f'  "category": one of {list(CATEGORIES.keys())}\n'
    '  "severity": integer 1-5 (5 = most urgent/dangerous, 1 = minor/cosmetic)\n'
    '  "summary": one plain-English sentence (max 25 words) a city official could '
    "skim on a dashboard\n"
    f'  "department": one of {DEPARTMENTS} - whichever is best equipped to fix this\n'
)

_EMPTY_RESULT = {"status": "unavailable", "category": None, "severity": None,
                  "summary": None, "department": None}


async def _load_image(photo_path):
    """Returns (media_type, base64_data) for a report's photo, or None if it
    can't be read. photo_path is either a full https:// URL (Supabase
    Storage, the normal case for every report since that migration) or a
    path relative to DATA_DIR (older reports saved to local disk before
    Supabase Storage was wired in - may 404 on hosts like Render whose
    local disk gets wiped on restart)."""
    if not photo_path:
        return None
    try:
        if photo_path.startswith("http://") or photo_path.startswith("https://"):
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                res = await client.get(photo_path)
            if res.status_code != 200:
                return None
            data = res.content
            media_type = res.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        else:
            full = os.path.join(DATA_DIR, photo_path)
            if not os.path.isfile(full):
                return None
            with open(full, "rb") as f:
                data = f.read()
            ext = os.path.splitext(full)[1].lower().lstrip(".")
            media_type = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "gif": "image/gif",
            }.get(ext, "image/jpeg")
        if not media_type.startswith("image/"):
            media_type = "image/jpeg"
        return media_type, base64.b64encode(data).decode()
    except Exception as e:
        logger.warning("could not load photo for AI triage: %r", e)
        return None


def _extract_json(text):
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON object in AI response")
    return json.loads(match.group(0))


async def analyze_report(description, location_label, photo_path):
    """Returns a dict: {status, category, severity, summary, department}.
    status is "done" on success, "unavailable" when no API key is
    configured, or "failed" if the call errored/timed out/came back
    unparseable - callers should still keep the report either way, this
    never raises."""
    if not ANTHROPIC_API_KEY:
        return dict(_EMPTY_RESULT)

    content = []
    image = await _load_image(photo_path)
    if image:
        media_type, b64 = image
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })

    content.append({
        "type": "text",
        "text": "Neighborhood: {}\nDescription: {}".format(
            location_label or "(not given)",
            description or "(no written description - see photo/audio)",
        ),
    })

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 300,
        "system": _SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            res = await client.post(_ANTHROPIC_URL, headers=headers, json=payload)
        if res.status_code != 200:
            logger.warning("Anthropic API error %s: %s", res.status_code, res.text[:300])
            return {**_EMPTY_RESULT, "status": "failed"}

        data = res.json()
        raw_text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )
        parsed = _extract_json(raw_text)

        category = parsed.get("category")
        if category not in CATEGORIES:
            category = None

        severity = parsed.get("severity")
        try:
            severity = int(severity)
            if not (1 <= severity <= 5):
                severity = None
        except (TypeError, ValueError):
            severity = None

        department = (parsed.get("department") or "").strip()[:100] or None
        summary = (parsed.get("summary") or "").strip()[:500] or None

        return {
            "status": "done",
            "category": category,
            "severity": severity,
            "summary": summary,
            "department": department,
        }
    except Exception as e:
        logger.warning("AI triage failed: %r", e)
        return {**_EMPTY_RESULT, "status": "failed"}
