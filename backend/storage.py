# -*- coding: utf-8 -*-
"""
Uploads a file's bytes to Supabase Storage and returns its public URL.

Used instead of saving to local disk when SUPABASE_URL/SUPABASE_SERVICE_KEY
are configured (see config.py) - local disk on free hosting tiers like
Render gets wiped on every restart/redeploy, silently losing every photo
and voice recording citizens submitted before that point.
"""

import logging
import mimetypes
import uuid

import httpx

from config import SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_STORAGE_BUCKET

logger = logging.getLogger("storage")

_HTTP_TIMEOUT = 20.0


async def upload_bytes(data: bytes, original_filename: str, subdir: str) -> str:
    """Uploads `data` to Supabase Storage under `<subdir>/<random-name>` and
    returns the public URL. Raises on failure (caller should turn that into
    an HTTP error - we never want to silently "succeed" and lose the file)."""
    ext = ""
    if original_filename and "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()[:10]
    object_name = f"{subdir}/{uuid.uuid4().hex}{ext}"

    content_type = mimetypes.guess_type(original_filename or "")[0] or "application/octet-stream"

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_STORAGE_BUCKET}/{object_name}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        res = await client.post(upload_url, headers=headers, content=data)

    if res.status_code not in (200, 201):
        logger.error("Supabase Storage upload failed (%s): %s", res.status_code, res.text)
        raise RuntimeError(f"Supabase Storage upload failed: {res.status_code} {res.text}")

    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_STORAGE_BUCKET}/{object_name}"
