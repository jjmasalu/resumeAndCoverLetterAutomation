import logging
import os
import uuid
import io
import json
import re
from datetime import datetime, timezone
from tavily import TavilyClient
from firecrawl import Firecrawl
from docxtpl import DocxTemplate
from config import settings
from db import supabase

logger = logging.getLogger(__name__)

tavily_client = TavilyClient(api_key=settings.tavily_api_key)
firecrawl_client = Firecrawl(api_key=settings.firecrawl_api_key)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
COVER_LETTER_MAX_PARAGRAPHS = 4
COVER_LETTER_TARGET_TOTAL_CHARS = 1100
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _canonicalize_for_merge(value):
    if isinstance(value, dict):
        return {
            key: _canonicalize_for_merge(val)
            for key, val in sorted(value.items())
        }
    if isinstance(value, list):
        return [_canonicalize_for_merge(item) for item in value]
    return value


def _merge_context_content(existing, incoming):
    """Merge progressively learned user context instead of overwriting it."""
    if existing in (None, {}, [], ""):
        return incoming
    if incoming in (None, {}, [], ""):
        return existing

    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _merge_context_content(merged[key], value)
            else:
                merged[key] = value
        return merged

    if isinstance(existing, list) and isinstance(incoming, list):
        merged = list(existing)
        seen = {
            json.dumps(_canonicalize_for_merge(item), sort_keys=True, default=str)
            for item in existing
        }
        for item in incoming:
            key = json.dumps(_canonicalize_for_merge(item), sort_keys=True, default=str)
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
        return merged

    return incoming


def _list_to_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if value in (None, ""):
        return ""
    return str(value).strip()


def _format_resume_skills(skills) -> str:
    if isinstance(skills, str):
        return skills
    if isinstance(skills, list):
        return _list_to_text(skills)
    if isinstance(skills, dict):
        groups = []
        for label, value in skills.items():
            value_text = _list_to_text(value)
            if value_text:
                groups.append(f"{label}: {value_text}")
        return "; ".join(groups)
    return _list_to_text(skills)


def _format_education_entries(education) -> str:
    if isinstance(education, str):
        return education
    if isinstance(education, dict):
        education = [education]
    if isinstance(education, list):
        entries = []
        for item in education:
            if isinstance(item, dict):
                main_parts = [
                    item.get("degree"),
                    item.get("institution"),
                ]
                main_text = ", ".join(str(part).strip() for part in main_parts if part)
                detail_parts = [
                    item.get("location"),
                    item.get("dates"),
                    f"GPA {item['gpa']}" if item.get("gpa") else None,
                    f"Average {item['average']}" if item.get("average") else None,
                ]
                details = " | ".join(str(part).strip() for part in detail_parts if part)
                awards = item.get("awards")
                awards_text = _list_to_text(awards)
                if awards_text:
                    details = f"{details} | Awards: {awards_text}" if details else f"Awards: {awards_text}"
                if details:
                    entries.append(f"{main_text} ({details})" if main_text else details)
                elif main_text:
                    entries.append(main_text)
            else:
                item_text = str(item).strip()
                if item_text:
                    entries.append(item_text)
        return "; ".join(entries)
    return _list_to_text(education)


def _normalize_resume_experiences(experiences) -> list[dict]:
    if not isinstance(experiences, list):
        return []

    normalized = []
    for item in experiences:
        if not isinstance(item, dict):
            continue

        bullets = item.get("bullets", [])
        if isinstance(bullets, str):
            bullet_list = [bullets]
        elif isinstance(bullets, list):
            bullet_list = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
        else:
            bullet_text = str(bullets).strip()
            bullet_list = [bullet_text] if bullet_text else []

        normalized.append({
            "company": str(item.get("company", "")).strip(),
            "role": str(item.get("role", "")).strip(),
            "dates": str(item.get("dates", "")).strip(),
            "bullets": bullet_list,
        })

    return normalized


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _compact_cover_letter_paragraph(text: str, *, max_sentences: int, max_chars: int) -> str:
    cleaned = _clean_whitespace(text)
    if not cleaned:
        return ""

    sentences = SENTENCE_BOUNDARY_RE.split(cleaned)
    if len(sentences) > max_sentences:
        cleaned = " ".join(sentences[:max_sentences]).strip()

    if len(cleaned) <= max_chars:
        return cleaned

    shortened = cleaned[:max_chars].rstrip()
    sentence_end = max(shortened.rfind(". "), shortened.rfind("! "), shortened.rfind("? "))
    if sentence_end > max_chars // 2:
        return shortened[:sentence_end + 1].strip()

    shortened = shortened.rsplit(" ", 1)[0].rstrip(",;: ")
    if shortened and shortened[-1] not in ".!?":
        shortened += "."
    return shortened


def _normalize_cover_letter_paragraphs(paragraphs) -> list[str]:
    if isinstance(paragraphs, str):
        items = [paragraphs]
    elif isinstance(paragraphs, list):
        items = [str(paragraph) for paragraph in paragraphs]
    else:
        paragraph_text = _list_to_text(paragraphs)
        items = [paragraph_text] if paragraph_text else []

    compacted = [
        _clean_whitespace(paragraph)
        for paragraph in items
        if _clean_whitespace(paragraph)
    ][:COVER_LETTER_MAX_PARAGRAPHS]

    if not compacted:
        return []

    normalized = []
    for index, paragraph in enumerate(compacted):
        is_closing_paragraph = index == len(compacted) - 1 and any(
            token in paragraph.lower()
            for token in ("thank", "appreciate", "welcome the opportunity", "look forward")
        )
        normalized.append(
            _compact_cover_letter_paragraph(
                paragraph,
                max_sentences=2 if is_closing_paragraph else 3,
                max_chars=220 if is_closing_paragraph else 360,
            )
        )

    total_chars = sum(len(paragraph) for paragraph in normalized)
    while total_chars > COVER_LETTER_TARGET_TOTAL_CHARS:
        longest_index = max(range(len(normalized)), key=lambda idx: len(normalized[idx]))
        current = normalized[longest_index]
        tighter_limit = max(180, len(current) - 80)
        updated = _compact_cover_letter_paragraph(
            current,
            max_sentences=2,
            max_chars=tighter_limit,
        )
        if updated == current:
            break
        normalized[longest_index] = updated
        total_chars = sum(len(paragraph) for paragraph in normalized)

    return [paragraph for paragraph in normalized if paragraph]


def _normalize_document_sections(doc_type: str, sections: dict) -> dict:
    normalized = dict(sections or {})

    if doc_type == "resume":
        normalized["summary"] = _list_to_text(normalized.get("summary"))
        normalized["skills"] = _format_resume_skills(normalized.get("skills"))
        normalized["education"] = _format_education_entries(normalized.get("education"))
        normalized["experiences"] = _normalize_resume_experiences(normalized.get("experiences"))
        return normalized

    if doc_type == "cover_letter":
        normalized["date"] = datetime.now().strftime("%B %d, %Y").replace(" 0", " ")
        normalized["hiring_manager"] = _list_to_text(normalized.get("hiring_manager")) or "Hiring Manager"
        normalized["company"] = _list_to_text(normalized.get("company"))
        normalized["role"] = _list_to_text(normalized.get("role"))
        normalized["paragraphs"] = _normalize_cover_letter_paragraphs(normalized.get("paragraphs"))
        return normalized

    return normalized


async def search_jobs(query: str, location: str | None = None) -> list[dict]:
    """Search for job postings using Tavily."""
    search_query = f"{query} job posting"
    if location:
        search_query += f" {location}"
    logger.info("search_jobs query=%s", search_query)
    try:
        results = tavily_client.search(
            query=search_query,
            max_results=5,
            search_depth="basic",
        )
        items = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:200],
            }
            for r in results.get("results", [])
        ]
        logger.info("search_jobs found %d results", len(items))
        return items
    except Exception as e:
        logger.error("search_jobs failed: %s", e)
        return [{"error": f"Search failed: {str(e)}"}]


async def scrape_job(url: str) -> dict:
    """Scrape a job posting URL using Firecrawl."""
    logger.info("scrape_job url=%s", url)
    try:
        result = firecrawl_client.scrape(url, formats=["markdown"])
        markdown = result.markdown or ""
        logger.info("scrape_job success md_len=%d", len(markdown))
        return {
            "description_md": markdown,
            "url": url,
        }
    except Exception as e:
        logger.error("scrape_job failed: %s", e)
        return {"error": f"Scraping failed: {str(e)}"}


async def generate_document(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
) -> dict:
    """Generate a .docx document from template and upload to Supabase Storage."""
    logger.info("generate_document type=%s job_id=%s", doc_type, job_id[:8])
    template_path = os.path.join(TEMPLATE_DIR, f"{doc_type}.docx")
    try:
        normalized_sections = _normalize_document_sections(doc_type, sections)
        doc = DocxTemplate(template_path)
        doc.render(normalized_sections)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        doc_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{doc_id}.docx"

        supabase.storage.from_("documents").upload(
            path=storage_path,
            file=buffer.getvalue(),
            file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

        signed_url = supabase.storage.from_("documents").create_signed_url(
            storage_path, 3600
        )

        # Save document record
        supabase.table("generated_documents").insert({
            "id": doc_id,
            "job_id": job_id,
            "user_id": user_id,
            "doc_type": doc_type,
            "file_url": storage_path,
        }).execute()

        logger.info("generate_document success doc_id=%s", doc_id[:8])
        return {
            "document_id": doc_id,
            "doc_type": doc_type,
            "download_url": signed_url.get("signedURL", ""),
        }
    except Exception as e:
        logger.error("generate_document failed: %s", e)
        return {"error": f"Document generation failed: {str(e)}"}


async def save_user_context(
    user_id: str,
    category: str,
    content: dict,
    conversation_id: str | None = None,
) -> dict:
    """Save or update user context in Supabase."""
    logger.info("save_user_context category=%s", category)
    try:
        existing = (
            supabase.table("user_context")
            .select("id, content")
            .eq("user_id", user_id)
            .eq("category", category)
            .execute()
        )

        if existing.data:
            merged_content = _merge_context_content(
                existing.data[0].get("content"),
                content,
            )
            supabase.table("user_context").update({
                "content": merged_content,
                "source_conversation_id": conversation_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("user_context").insert({
                "user_id": user_id,
                "category": category,
                "content": content,
                "source_conversation_id": conversation_id,
            }).execute()

        logger.info("save_user_context saved category=%s", category)
        return {"status": "saved", "category": category}
    except Exception as e:
        logger.error("save_user_context failed: %s", e)
        return {"error": f"Context save failed: {str(e)}"}
