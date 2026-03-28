from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Iterable


INVALID_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9]+")
VERSION_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)(?:-v(?P<version>\d+))?$", re.IGNORECASE)


def _filename_segment(value: str | None, *, fallback: str = "") -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return fallback
    cleaned = cleaned.replace("&", " and ")
    cleaned = cleaned.replace("’", "").replace("'", "")
    cleaned = INVALID_FILENAME_CHARS_RE.sub("-", cleaned).strip("-._ ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned[:48].strip("-._ ")


def default_generated_document_filename(doc_type: str, created_at: datetime | None = None) -> str:
    timestamp = created_at or datetime.now(timezone.utc)
    date_part = timestamp.strftime("%Y-%m-%d")
    stem = {
        "resume": "resume",
        "cover_letter": "cover-letter",
    }.get(doc_type, "document")
    return f"{stem}-{date_part}.docx"


def _variant_filename_segment(variant_key: str | None) -> str:
    return {
        "ats_safe": "ATS",
        "creative_safe": "Creative",
    }.get(str(variant_key or "").strip().lower(), "")


def semantic_generated_document_filename(
    doc_type: str,
    sections: dict,
    *,
    variant_key: str | None = None,
) -> str:
    name_segment = _filename_segment(sections.get("name"))
    role_segment = _filename_segment(sections.get("role") or sections.get("title"))
    company_segment = _filename_segment(sections.get("company"))
    doc_segment = "Cover-Letter" if doc_type == "cover_letter" else "Resume"
    variant_segment = _variant_filename_segment(variant_key)

    parts = [
        segment
        for segment in (name_segment, role_segment, company_segment, doc_segment, variant_segment)
        if segment
    ]
    if len(parts) <= 1:
        return default_generated_document_filename(doc_type)

    filename = "-".join(parts)
    return f"{filename[:140].rstrip('-._ ')}.docx"


def next_versioned_filename(base_filename: str, existing_filenames: Iterable[str]) -> str:
    stem, ext = os.path.splitext(base_filename)
    max_version = 0
    for existing in existing_filenames:
        existing_stem, existing_ext = os.path.splitext(str(existing or ""))
        if existing_ext.lower() != ext.lower():
            continue
        match = VERSION_SUFFIX_RE.match(existing_stem)
        if not match:
            continue
        if match.group("stem").lower() != stem.lower():
            continue
        version = int(match.group("version") or "1")
        max_version = max(max_version, version)

    if max_version <= 0:
        return base_filename
    return f"{stem}-v{max_version + 1}{ext}"
