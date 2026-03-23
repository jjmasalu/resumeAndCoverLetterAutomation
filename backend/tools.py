import asyncio
import logging
import uuid
import json
from datetime import datetime, timezone
from typing import Callable
from tavily import TavilyClient
from firecrawl import Firecrawl
from config import settings
from db import supabase
from document_engine import (
    build_document_plan,
    normalize_document_sections as _normalize_document_sections,
    render_document,
    serialize_document_plan,
)
from document_filenames import (
    default_generated_document_filename,
    next_versioned_filename,
    semantic_generated_document_filename,
)

logger = logging.getLogger(__name__)

tavily_client = TavilyClient(api_key=settings.tavily_api_key)
firecrawl_client = Firecrawl(api_key=settings.firecrawl_api_key)

DocumentProgressCallback = Callable[[dict], None]

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


def _search_jobs_sync(query: str, location: str | None = None) -> list[dict]:
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


async def search_jobs(query: str, location: str | None = None) -> list[dict]:
    return await asyncio.to_thread(_search_jobs_sync, query, location)


def _scrape_job_sync(url: str) -> dict:
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


async def scrape_job(url: str) -> dict:
    return await asyncio.to_thread(_scrape_job_sync, url)


def _emit_document_progress(
    progress_callback: DocumentProgressCallback | None,
    *,
    phase: str,
    state: str,
    detail: str | None = None,
    meta: dict | None = None,
) -> None:
    if not progress_callback:
        return
    payload = {
        "phase": phase,
        "state": state,
    }
    if detail:
        payload["detail"] = detail
    if meta:
        payload["meta"] = meta
    try:
        progress_callback(payload)
    except Exception as error:
        logger.warning("document progress callback failed for %s/%s: %s", phase, state, error)


def _summarize_repair_actions(repair_history: list[dict]) -> str:
    labels = {
        "switch_theme": "switched to a denser theme",
        "tighten_text_budgets": "tightened summary and skills budgets",
        "reduce_bullets": "reduced experience bullets",
        "drop_low_priority_experience": "trimmed lower-priority experience",
        "tighten_cover_letter_budgets": "tightened paragraph budgets",
        "reduce_cover_letter_paragraphs": "reduced paragraph count",
        "tighten_cover_letter_text": "tightened cover letter text",
    }
    actions = [
        labels.get(str(item.get("action")), str(item.get("action", "")).replace("_", " "))
        for item in repair_history
        if item.get("action")
    ]
    if not actions:
        return ""
    if len(actions) == 1:
        return actions[0].capitalize() + "."
    if len(actions) == 2:
        return f"{actions[0].capitalize()} and {actions[1]}."
    return f"{actions[0].capitalize()}, {actions[1]}, and more."


def _resolve_generated_document_filename(
    *,
    doc_type: str,
    sections: dict,
    user_id: str,
) -> str:
    base_filename = semantic_generated_document_filename(doc_type, sections)
    try:
        existing = (
            supabase.table("generated_documents")
            .select("filename")
            .eq("user_id", user_id)
            .execute()
        )
        existing_filenames = [
            row.get("filename")
            for row in (existing.data or [])
            if row.get("filename")
        ]
    except Exception as error:
        logger.warning("failed to load existing generated filenames: %s", error)
        existing_filenames = []

    return next_versioned_filename(base_filename, existing_filenames)


def _generate_document_sync(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
    progress_callback: DocumentProgressCallback | None = None,
) -> dict:
    """Generate a .docx document from template and upload to Supabase Storage."""
    logger.info("generate_document type=%s job_id=%s", doc_type, job_id[:8])
    active_phase = "plan"
    generated_at = datetime.now(timezone.utc)
    filename = _resolve_generated_document_filename(
        doc_type=doc_type,
        sections=sections,
        user_id=user_id,
    )
    try:
        _emit_document_progress(
            progress_callback,
            phase="plan",
            state="running",
        )
        plan = build_document_plan(doc_type, sections)
        _emit_document_progress(
            progress_callback,
            phase="plan",
            state="done",
            detail=f"Selected {plan.theme_id.replace('_', ' ')} theme.",
            meta={
                "theme_id": plan.theme_id,
                "density": plan.density,
                "attempt_count": plan.attempt_count,
            },
        )
        if plan.repair_history:
            _emit_document_progress(
                progress_callback,
                phase="repair",
                state="done",
                detail=_summarize_repair_actions(plan.repair_history),
                meta={
                    "repair_actions": [item.get("action") for item in plan.repair_history],
                    "attempt_count": plan.attempt_count,
                },
            )
        verification = plan.verification or {}
        verification_status = verification.get("status", "passed")
        verification_issues = verification.get("issues") or []
        verification_detail = (
            f"Fits the {plan.page_budget}-page budget."
            if verification_status == "passed"
            else (verification_issues[0].get("message") if verification_issues else "Layout verification failed.")
        )
        _emit_document_progress(
            progress_callback,
            phase="verify",
            state="done" if verification_status == "passed" else "failed",
            detail=verification_detail,
            meta={
                "verification_status": verification_status,
                "page_budget": plan.page_budget,
            },
        )

        _emit_document_progress(
            progress_callback,
            phase="render",
            state="running",
        )
        active_phase = "render"
        document_bytes = render_document(plan)
        _emit_document_progress(
            progress_callback,
            phase="render",
            state="done",
            detail="Built the DOCX document.",
        )

        doc_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{doc_id}.docx"

        _emit_document_progress(
            progress_callback,
            phase="save",
            state="running",
        )
        active_phase = "save"
        supabase.storage.from_("documents").upload(
            path=storage_path,
            file=document_bytes,
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
            "filename": filename,
            "file_url": storage_path,
        }).execute()
        _emit_document_progress(
            progress_callback,
            phase="save",
            state="done",
            detail="Stored the document and generated a download link.",
        )

        logger.info("generate_document success doc_id=%s", doc_id[:8])
        return {
            "document_id": doc_id,
            "doc_type": doc_type,
            "filename": filename or default_generated_document_filename(doc_type, generated_at),
            "download_url": signed_url.get("signedURL", ""),
            "theme_id": plan.theme_id,
            "page_budget": plan.page_budget,
            "document_plan": serialize_document_plan(plan),
        }
    except Exception as e:
        logger.error("generate_document failed: %s", e)
        _emit_document_progress(
            progress_callback,
            phase=active_phase,
            state="failed",
            detail=f"{str(e)}",
        )
        return {"error": f"Document generation failed: {str(e)}"}


async def generate_document(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
    progress_callback: DocumentProgressCallback | None = None,
) -> dict:
    return await asyncio.to_thread(
        _generate_document_sync,
        doc_type,
        sections,
        user_id,
        job_id,
        progress_callback,
    )


def _save_user_context_sync(
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


async def save_user_context(
    user_id: str,
    category: str,
    content: dict,
    conversation_id: str | None = None,
) -> dict:
    return await asyncio.to_thread(
        _save_user_context_sync,
        user_id,
        category,
        content,
        conversation_id,
    )
