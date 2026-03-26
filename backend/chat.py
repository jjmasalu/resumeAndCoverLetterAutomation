import asyncio
import json
import io
import logging
import re
from typing import AsyncGenerator
from docx import Document as WordDocument
from google import genai
from google.genai import types
from sse_starlette.sse import ServerSentEvent
from config import settings
from db import supabase
import tools

logger = logging.getLogger(__name__)

gemini_client = genai.Client(api_key=settings.gemini_api_key)

MODEL = "gemini-2.5-flash"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
STREAM_FLUSH_PADDING = " " * 8192

# Gemini function declarations
SEARCH_JOBS_DECLARATION = types.FunctionDeclaration(
    name="search_jobs",
    description="Search the web for direct job postings matching a query. Results include canonical_candidate, platform, and url_kind. Prefer results where canonical_candidate=true and avoid scraping listing_page or aggregator_listing URLs.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "query": types.Schema(type=types.Type.STRING, description="Job search query, e.g. 'Senior Python Developer'"),
            "location": types.Schema(type=types.Type.STRING, description="Job location, e.g. 'New York' or 'remote'"),
        },
        required=["query"],
    ),
)

SCRAPE_JOB_DECLARATION = types.FunctionDeclaration(
    name="scrape_job",
    description="Extract the full job description from a specific job-posting URL. If the URL is a listing page, aggregator page, or blocked page, the tool will explain the blocker. Prefer canonical ATS or company-career job URLs.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "url": types.Schema(type=types.Type.STRING, description="URL of the job posting"),
        },
        required=["url"],
    ),
)

GENERATE_DOCUMENT_DECLARATION = types.FunctionDeclaration(
    name="generate_document",
    description="Generate a resume or cover letter as a .docx file. Use only after you have gathered enough information about the user and the job. The backend applies a deterministic document engine with approved themes.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "doc_type": types.Schema(type=types.Type.STRING, description="'resume' or 'cover_letter'"),
            "sections": types.Schema(
                type=types.Type.OBJECT,
                description="Structured content for the document. Resume: {name, title, summary, experiences: [{company, role, dates, bullets}], skills, education}. Cover letter: {name, date, company, hiring_manager, role, paragraphs: [str]}. Optional design inputs: theme_id in {'classic_professional','technical_compact','executive_clean','ats_minimal','modern_minimal'} and layout_strategy in {'ats_safe','balanced','executive','compact','creative_safe'}.",
            ),
        },
        required=["doc_type", "sections"],
    ),
)

SAVE_USER_CONTEXT_DECLARATION = types.FunctionDeclaration(
    name="save_user_context",
    description="Save information you've learned about the user for future conversations. Use when the user shares their work experience, skills, education, or other profile info.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "category": types.Schema(type=types.Type.STRING, description="Category: 'work_experience', 'skills', 'education', 'certifications', 'personal_info', or 'preferences'"),
            "content": types.Schema(type=types.Type.OBJECT, description="Structured data about this category"),
        },
        required=["category", "content"],
    ),
)

PRESENT_JOB_RESULTS_DECLARATION = types.FunctionDeclaration(
    name="present_job_results",
    description="Present job search results to the user as structured cards. Call this AFTER you have searched for jobs, scraped promising results, and assessed match scores.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "results": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "title": types.Schema(type=types.Type.STRING, description="Job title"),
                        "url": types.Schema(type=types.Type.STRING, description="Job posting URL"),
                        "snippet": types.Schema(type=types.Type.STRING, description="Brief description of the role"),
                        "match_score": types.Schema(type=types.Type.INTEGER, description="0-100 match percentage based on user profile"),
                        "company": types.Schema(type=types.Type.STRING, description="Company name"),
                        "location": types.Schema(type=types.Type.STRING, description="Location or remote status"),
                    },
                    required=["title", "url", "snippet", "match_score"],
                ),
            ),
        },
        required=["results"],
    ),
)

TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        SEARCH_JOBS_DECLARATION,
        SCRAPE_JOB_DECLARATION,
        GENERATE_DOCUMENT_DECLARATION,
        SAVE_USER_CONTEXT_DECLARATION,
        PRESENT_JOB_RESULTS_DECLARATION,
    ]
)
SAVE_CONTEXT_ONLY_TOOL = types.Tool(function_declarations=[SAVE_USER_CONTEXT_DECLARATION])

JOB_TO_RESUME_PROMPT = """You are a career assistant helping the user create a tailored resume and cover letter for a specific job.

Your workflow:
1. Ask the user what position they're interested in, or accept a job URL
2. Use search_jobs to find the posting, or scrape_job if they give a URL
3. Prefer direct ATS/company job pages where `canonical_candidate=true`. Avoid scraping `listing_page` or `aggregator_listing` results.
4. Analyze the job requirements
5. Ask the user targeted questions about their relevant experience, skills, and education — one or two questions at a time, not everything at once
6. When you learn something important about the user, use save_user_context to remember it
7. Once you have enough info, use generate_document to create the resume and cover letter

Be conversational and helpful. Ask specific questions based on what the job requires. Don't ask for information you already have from the user's context.

Cover letters must fit on one page. When preparing sections for generate_document, keep the cover letter to three concise body paragraphs plus a brief closing paragraph, avoid repeating resume bullets verbatim, and keep the total body around 220-300 words.

If you choose a design direction, do it by selecting an approved `theme_id` inside `sections`. Available themes:
- `ats_minimal` for strict ATS-safe simplicity with minimal styling
- `classic_professional` for balanced, conservative presentation
- `technical_compact` for denser technical resumes and tighter page budgets
- `executive_clean` for leadership-oriented applications with a more formal, editorial hierarchy
- `modern_minimal` for design-adjacent or portfolio-aware applications while staying ATS-safe

For design-forward resume roles, if you choose `modern_minimal` or `creative_safe`, the backend may automatically produce both a Creative-safe and ATS-safe resume variant from the same content.

You may also set `layout_strategy` in `sections` to one of:
- `ats_safe`
- `balanced`
- `executive`
- `compact`
- `creative_safe`

Use `layout_strategy` when you want the engine to choose the exact theme deterministically within that direction. Do not invent custom themes or arbitrary formatting instructions.

IMPORTANT: When you generate a document, do NOT paste the download URL in your response. The UI will automatically show a download card. Just tell the user the document is ready and offer to make adjustments or generate additional documents."""

FIND_JOBS_WITH_FILE_PROMPT = """You are a career assistant helping the user find jobs that match their profile.

The user has uploaded their resume. Analyze it thoroughly — extract work experience,
skills, education, certifications, and any other relevant details. Respond with a
concise summary of what you found and ask if anything needs correction.

Use save_user_context to persist each category you extract (work_experience, skills,
education, certifications, personal_info).

Once the user confirms their profile, ask what kind of roles they're looking for
(or suggest based on their profile). Then use search_jobs to find matching positions.

For each promising result, use scrape_job to get the full description, but prefer results where `canonical_candidate=true` and avoid `listing_page` or `aggregator_listing` URLs. If scraping reports a blocker, explain it to the user instead of pretending the job was read.
Once you have a usable scrape, assess
how well it matches the user's profile (0-100%). Once you have assessed the results,
use present_job_results to show them to the user as structured cards.

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card.

When generating a cover letter, keep it to one page: three concise body paragraphs plus a brief closing paragraph, and avoid repeating the resume verbatim.

If a theme choice would help, set `theme_id` in `sections` to one of `ats_minimal`, `classic_professional`, `technical_compact`, `executive_clean`, or `modern_minimal`, or set `layout_strategy` to one of `ats_safe`, `balanced`, `executive`, `compact`, or `creative_safe`. Do not invent other theme names or strategies."""

FIND_JOBS_PROMPT = """You are a career assistant helping the user find jobs that match their profile.

Your workflow:
1. Review the user's existing context to understand their background
2. Ask focused questions to understand their experience, skills, education, and what they're looking for
3. Use save_user_context as you learn things about the user
4. Once you have enough context, ask what roles they want and use search_jobs to find matching positions
5. For each promising result, use scrape_job to get the full description, but prefer results where `canonical_candidate=true` and avoid `listing_page` or `aggregator_listing` URLs. If scraping reports a blocker, tell the user what was blocked and move on to another result.
6. Assess how well each successfully scraped result matches the user's profile (0-100%)
7. Use present_job_results to show results as structured cards
8. For selected jobs, generate tailored documents using generate_document

Be proactive in suggesting roles based on the user's skills and experience.

When generating a cover letter, keep it to one page: three concise body paragraphs plus a brief closing paragraph, and avoid repeating the resume verbatim.

If a theme choice would help, set `theme_id` in `sections` to one of `ats_minimal`, `classic_professional`, `technical_compact`, `executive_clean`, or `modern_minimal`, or set `layout_strategy` to one of `ats_safe`, `balanced`, `executive`, `compact`, or `creative_safe`. Do not invent other theme names or strategies.

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card."""

TURN_ROUTER_PROMPT = """You are a turn router for a resume and job-search assistant.

Classify the current user turn before the main assistant responds.
Return JSON only with this shape:
{
  "intent": "small_talk|clarification|profile_update|search_jobs|analyze_job_url|job_selection|generate_documents|revise_documents|general_guidance",
  "allow_tools": true,
  "response_mode": "direct_answer|ask_clarifying_question|tool_driven",
  "reason": "short explanation"
}

Rules:
- Use allow_tools=false for greetings, thanks, small talk, direct clarifying questions, or general advice that does not require search/scraping/document generation.
- Use allow_tools=true when the user wants job search, job URL analysis, job matching, or document generation.
- If the user shares new background information about themselves, prefer profile_update and set allow_tools=true so the assistant can save structured memory.
- If the user includes a likely URL for a job posting, prefer analyze_job_url with allow_tools=true.
- If the user asks to generate or tailor a resume and/or cover letter, prefer generate_documents with allow_tools=true.
- Be conservative about tool use. If a focused conversational response is enough for this turn, set allow_tools=false.
"""

TOOL_PHASE_LABELS = {
    "search_jobs": ("search_jobs", "Searching for jobs"),
    "scrape_job": ("read_job_posting", "Reading job posting"),
    "save_user_context": ("save_user_context", "Saving your info"),
    "present_job_results": ("prepare_job_matches", "Preparing job matches"),
}

DOCUMENT_PROGRESS_PHASE_LABELS = {
    "plan": "Planning",
    "repair": "Adjusting",
    "verify": "Verifying",
    "render": "Rendering",
    "save": "Saving",
}


def _build_context_prompt(user_id: str) -> str:
    """Load user context from Supabase and format as a prompt section."""
    result = supabase.table("user_context").select("category, content").eq("user_id", user_id).execute()
    if not result.data:
        return "No prior information about this user."
    parts = ["Here is what you already know about this user:"]
    for ctx in result.data:
        parts.append(f"\n**{ctx['category']}:** {json.dumps(ctx['content'])}")
    return "\n".join(parts)


def _build_history(conversation_id: str) -> list[types.Content]:
    """Load conversation history from Supabase and format for Gemini."""
    result = (
        supabase.table("messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    contents = []
    for msg in result.data:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))
    return contents


def _get_conversation_files(
    conversation_id: str,
    file_ids: list[str] | None = None,
) -> list[dict]:
    """Get uploaded files for a conversation, optionally scoped to specific ids."""
    query = (
        supabase.table("conversation_files")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
    )
    if file_ids:
        query = query.in_("id", file_ids)
    result = query.execute()
    return result.data or []


def _build_user_message_content(
    user_message: str,
    file_records: list[dict],
) -> types.Content:
    parts = []
    for file_record in file_records:
        if file_record["mime_type"] == DOCX_MIME_TYPE:
            extracted_text = _extract_docx_text(file_record)
            if extracted_text:
                parts.append(types.Part.from_text(
                    text=f"Attached document ({file_record['filename']}):\n{extracted_text}"
                ))
            else:
                parts.append(types.Part.from_text(
                    text=f"The user attached {file_record['filename']}, but the document text could not be extracted."
                ))
            continue

        parts.append(types.Part.from_uri(
            file_uri=file_record["gemini_file_uri"],
            mime_type=file_record["mime_type"],
        ))
    parts.append(types.Part.from_text(text=user_message))
    return types.Content(role="user", parts=parts)


def _extract_docx_text(file_record: dict) -> str:
    try:
        payload = supabase.storage.from_("uploads").download(file_record["storage_path"])
        file_bytes = payload.read() if hasattr(payload, "read") else payload
        document = WordDocument(io.BytesIO(file_bytes))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        return "\n".join(paragraphs)
    except Exception as error:
        logger.warning("failed to extract docx text for %s: %s", file_record.get("filename"), error)
        return ""


def _response_text(response) -> str:
    text = getattr(response, "text", None)
    if text:
        return text

    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return ""

    candidate = candidates[0]
    content = getattr(candidate, "content", None)
    parts = getattr(content, "parts", None) or []
    texts = [part.text for part in parts if getattr(part, "text", None)]
    return "".join(texts)


def _recent_history_for_router(history: list[types.Content], limit: int = 6) -> str:
    snippets: list[str] = []
    for content in history[-limit:]:
        role = getattr(content, "role", "user")
        text_parts = []
        for part in content.parts:
            if getattr(part, "text", None):
                text_parts.append(part.text)
            elif getattr(part, "file_uri", None):
                text_parts.append(f"[file:{part.file_uri}]")
        if text_parts:
            snippets.append(f"{role}: {' '.join(text_parts)}")
    return "\n".join(snippets) if snippets else "No previous messages."


def _heuristic_turn_router(user_message: str) -> dict | None:
    lower = user_message.strip().lower()
    if not lower:
        return {
            "intent": "clarification",
            "allow_tools": False,
            "response_mode": "ask_clarifying_question",
            "reason": "The user message is empty.",
        }

    if re.search(r"https?://", user_message):
        return {
            "intent": "analyze_job_url",
            "allow_tools": True,
            "response_mode": "tool_driven",
            "reason": "The message contains a URL that likely needs scraping.",
        }

    if lower in {"hi", "hello", "hey", "thanks", "thank you", "good morning", "good afternoon"}:
        return {
            "intent": "small_talk",
            "allow_tools": False,
            "response_mode": "direct_answer",
            "reason": "This is a short greeting or acknowledgment.",
        }

    return None


def _analyze_turn(
    *,
    user_message: str,
    mode: str,
    context_prompt: str,
    history: list[types.Content],
) -> dict:
    heuristic = _heuristic_turn_router(user_message)
    if heuristic:
        return heuristic

    router_contents = f"""{TURN_ROUTER_PROMPT}

Conversation mode: {mode}

Known user context:
{context_prompt}

Recent history:
{_recent_history_for_router(history)}

Current user message:
{user_message}
"""

    try:
        response = gemini_client.models.generate_content(
            model=MODEL,
            contents=router_contents,
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        router = json.loads(_response_text(response))
        if not isinstance(router, dict):
            raise ValueError("Router response is not an object")
        if "allow_tools" not in router:
            router["allow_tools"] = True
        if "intent" not in router:
            router["intent"] = "general_guidance"
        if "response_mode" not in router:
            router["response_mode"] = "tool_driven" if router["allow_tools"] else "direct_answer"
        if "reason" not in router:
            router["reason"] = "Router did not provide a reason."
        return router
    except Exception as error:
        logger.warning("turn router failed, defaulting to tool-enabled flow: %s", error)
        return {
            "intent": "general_guidance",
            "allow_tools": True,
            "response_mode": "tool_driven",
            "reason": "Router fallback after analysis failure.",
        }


def _tools_for_router(router: dict) -> list[types.Tool]:
    if not router.get("allow_tools", True):
        return []
    if router.get("intent") == "profile_update":
        return [SAVE_CONTEXT_ONLY_TOOL]
    return [TOOL_DECLARATIONS]


def _status_payload(
    *,
    step_id: str,
    phase: str,
    label: str,
    state: str,
    tool: str | None = None,
    detail: str | None = None,
    meta: dict | None = None,
) -> dict:
    payload = {
        "id": step_id,
        "phase": phase,
        "label": label,
        "state": state,
    }
    # Cloud Run can coalesce very small SSE frames. Padding live status events
    # makes the first in-progress update visible before the tool finishes.
    if state == "running":
        payload["_stream_padding"] = STREAM_FLUSH_PADDING
    if tool:
        payload["tool"] = tool
    if detail:
        payload["detail"] = detail
    if meta:
        payload["meta"] = meta
    return payload


def _persisted_activity_step(payload: dict) -> dict:
    persisted = dict(payload)
    persisted.pop("_stream_padding", None)
    return persisted


def _upsert_activity_trace(trace: list[dict], payload: dict) -> None:
    persisted = _persisted_activity_step(payload)
    for index, existing in enumerate(trace):
        if existing.get("id") == persisted.get("id"):
            trace[index] = persisted
            return
    trace.append(persisted)


def _router_status_payload(router: dict, state: str) -> dict:
    detail = None
    if state == "done":
        detail = router.get("reason")
    return _status_payload(
        step_id="understanding_request",
        phase="understanding_request",
        label="Understanding request",
        state=state,
        detail=detail,
        meta={
            "intent": router.get("intent"),
            "response_mode": router.get("response_mode"),
            "allow_tools": router.get("allow_tools"),
        } if state == "done" else None,
    )


def _generate_document_status_metadata(args: dict, result: dict | None, state: str) -> dict:
    doc_type = args.get("doc_type", "document")
    label = {
        "resume": "Generating resume",
        "cover_letter": "Generating cover letter",
    }.get(doc_type, "Generating document")
    detail = None
    meta = {"doc_type": doc_type}

    if state == "done" and result:
        documents = _result_documents(result)
        primary_result = documents[0] if documents else result
        plan = primary_result.get("document_plan") or result.get("document_plan") or {}
        repair_history = plan.get("repair_history") or []
        variant_labels = [
            str(document.get("variant_label"))
            for document in documents
            if document.get("variant_label")
        ]
        if len(documents) > 1:
            if len(variant_labels) >= 2:
                detail = f"{' and '.join(variant_labels[:2])} variants ready."
            else:
                detail = "Document variants ready."
            meta["variant_count"] = len(documents)
            if variant_labels:
                meta["variant_labels"] = variant_labels
        elif repair_history:
            detail = f"Adjusted layout to fit {result.get('page_budget', 1)} page."
            meta["repair_actions"] = [item.get("action") for item in repair_history]
        else:
            detail = f"{label.replace('Generating ', '').capitalize()} ready."
        if primary_result.get("theme_id"):
            meta["theme_id"] = primary_result["theme_id"]
        if primary_result.get("page_budget") is not None:
            meta["page_budget"] = primary_result["page_budget"]
        verification = plan.get("verification") or {}
        if verification.get("status"):
            meta["verification_status"] = verification["status"]

    return {
        "step_id": f"generate_document:{doc_type}",
        "phase": f"generate_{doc_type}",
        "label": label,
        "detail": detail,
        "meta": meta,
    }


def _document_progress_status_payload(args: dict, progress_event: dict) -> dict:
    doc_type = str(args.get("doc_type", "document"))
    phase = str(progress_event.get("phase", "progress"))
    state = str(progress_event.get("state", "running"))
    doc_label = {
        "resume": "resume",
        "cover_letter": "cover letter",
    }.get(doc_type, "document")
    phase_label = DOCUMENT_PROGRESS_PHASE_LABELS.get(
        phase,
        phase.replace("_", " ").title(),
    )
    detail = progress_event.get("detail")
    meta = {"doc_type": doc_type}
    raw_meta = progress_event.get("meta")
    if isinstance(raw_meta, dict):
        meta.update(raw_meta)

    return _status_payload(
        step_id=f"generate_document:{doc_type}:{phase}",
        phase=f"generate_{doc_type}_{phase}",
        label=f"{phase_label} {doc_label}",
        state=state,
        tool="generate_document",
        detail=detail,
        meta=meta,
    )


def _tool_status_payload(
    *,
    name: str,
    args: dict,
    state: str,
    result: dict | list | None = None,
) -> dict:
    if name == "generate_document":
        metadata = _generate_document_status_metadata(
            args,
            result if isinstance(result, dict) else None,
            state,
        )
        return _status_payload(
            step_id=metadata["step_id"],
            phase=metadata["phase"],
            label=metadata["label"],
            state=state,
            tool=name,
            detail=metadata["detail"],
            meta=metadata["meta"],
        )

    phase, label = TOOL_PHASE_LABELS.get(name, (name, name.replace("_", " ").title()))
    detail = None
    meta = None

    if state == "done":
        if name == "search_jobs" and isinstance(result, list):
            canonical_count = sum(
                1
                for item in result
                if isinstance(item, dict) and item.get("canonical_candidate")
            )
            detail = f"Found {len(result)} potential job posting{'s' if len(result) != 1 else ''}."
            if canonical_count:
                detail += f" {canonical_count} look like direct postings."
            meta = {"result_count": len(result), "canonical_count": canonical_count}
        elif name == "scrape_job" and isinstance(result, dict) and "error" not in result:
            detail = "Captured the job description."
            if result.get("quality") == "medium":
                detail = "Captured the job description with lower confidence."
            blockers = result.get("blockers") or []
            if blockers:
                meta = {"blockers": blockers}
        elif name == "save_user_context":
            category = args.get("category")
            detail = f"Saved {str(category).replace('_', ' ')} to memory." if category else "Saved new profile details."
            meta = {"category": category}
        elif name == "present_job_results" and isinstance(result, dict):
            count = len(result.get("results", []))
            detail = f"Prepared {count} match card{'s' if count != 1 else ''}."
            meta = {"result_count": count}
    elif state == "failed":
        if isinstance(result, dict) and result.get("error"):
            detail = str(result["error"])

    return _status_payload(
        step_id=name,
        phase=phase,
        label=label,
        state=state,
        tool=name,
        detail=detail,
        meta=meta,
    )


def _result_documents(result: dict | None) -> list[dict]:
    if not isinstance(result, dict):
        return []
    documents = result.get("documents")
    if isinstance(documents, list):
        return [
            item for item in documents
            if isinstance(item, dict) and item.get("document_id")
        ]
    if result.get("document_id"):
        return [result]
    return []


def _tool_run_summary(executed_tools: list[dict]) -> str:
    lines: list[str] = []
    for item in executed_tools:
        name = item.get("name", "tool")
        state = item.get("state", "done")
        result = item.get("result")
        if name == "generate_document" and isinstance(result, dict):
            documents = _result_documents(result)
            filename = result.get("filename")
            doc_type = str(result.get("doc_type", "document")).replace("_", " ")
            if state == "failed":
                detail = result.get("error", "generation failed")
            elif len(documents) > 1:
                labels = [
                    str(document.get("variant_label"))
                    for document in documents
                    if document.get("variant_label")
                ]
                if labels:
                    detail = f"created {doc_type} variants {' and '.join(labels)}"
                else:
                    detail = f"created {len(documents)} {doc_type} variants"
            elif filename:
                detail = f"created {doc_type} file {filename}"
            else:
                detail = f"generated {doc_type}"
        elif name == "present_job_results" and isinstance(result, dict):
            count = len(result.get("results", []))
            detail = f"prepared {count} job match card{'s' if count != 1 else ''}"
        elif name == "search_jobs" and isinstance(result, list):
            count = len(result)
            detail = f"found {count} search result{'s' if count != 1 else ''}"
        elif name == "scrape_job" and isinstance(result, dict):
            detail = result.get("error", "scraped the job posting") if state == "failed" else "scraped the job posting"
        elif name == "save_user_context" and isinstance(result, dict):
            category = item.get("args", {}).get("category")
            detail = f"saved {str(category).replace('_', ' ')} to memory" if category else "saved user context"
        else:
            detail = "completed"
        lines.append(f"- {name}: {detail}")
    return "\n".join(lines)


def _deterministic_tool_only_fallback(executed_tools: list[dict]) -> str:
    successful_documents = [
        document
        for item in executed_tools
        if item.get("name") == "generate_document"
        and item.get("state") == "done"
        and isinstance(item.get("result"), dict)
        for document in _result_documents(item.get("result"))
    ]
    failed_documents = [
        item for item in executed_tools
        if item.get("name") == "generate_document"
        and item.get("state") == "failed"
    ]

    if successful_documents:
        resume_variants = [
            str(document.get("variant_label"))
            for document in successful_documents
            if document.get("doc_type") == "resume" and document.get("variant_label")
        ]
        doc_labels = [
            str(document.get("doc_type", "document")).replace("_", " ")
            for document in successful_documents
        ]
        has_cover_letter = "cover letter" in doc_labels
        has_resume = "resume" in doc_labels
        if len(resume_variants) >= 2 and has_cover_letter:
            return "Your ATS-safe and Creative-safe resumes plus your cover letter are ready. The download cards are below. If you want revisions, tell me what to change."
        if len(resume_variants) >= 2:
            return "Your ATS-safe and Creative-safe resumes are ready. The download cards are below. If you want revisions, tell me what to change."
        if has_cover_letter and has_resume:
            return "Your resume and cover letter are ready. The download cards are below. If you want any revisions, tell me what to change."
        if len(doc_labels) == 1:
            return f"Your {doc_labels[0]} is ready. The download card is below. If you want revisions, tell me what to change."
        return "Your documents are ready. The download cards are below. If you want revisions, tell me what to change."

    if failed_documents:
        error = failed_documents[-1].get("result", {}).get("error")
        if error:
            return f"I hit an issue while generating the document: {error}"
        return "I hit an issue while generating the document. Try again or tell me what to adjust."

    last_presented_jobs = next(
        (
            item for item in reversed(executed_tools)
            if item.get("name") == "present_job_results" and item.get("state") == "done"
        ),
        None,
    )
    if last_presented_jobs and isinstance(last_presented_jobs.get("result"), dict):
        count = len(last_presented_jobs["result"].get("results", []))
        return f"I found {count} matching job{'s' if count != 1 else ''} and displayed them below. Tell me which one you want to pursue."

    if any(item.get("name") == "scrape_job" and item.get("state") == "done" for item in executed_tools):
        return "I reviewed the job posting. If you want, I can tailor your resume and cover letter for it."

    if any(item.get("name") == "save_user_context" and item.get("state") == "done" for item in executed_tools):
        return "I saved that information to your profile memory so I can use it in future applications."

    return "I finished that step. Tell me if you want me to continue with the next part."


def _generate_tool_only_followup_text(
    *,
    full_system: str,
    contents: list[types.Content],
    executed_tools: list[dict],
) -> str:
    summary = _tool_run_summary(executed_tools)
    completion_prompt = types.Content(
        role="user",
        parts=[types.Part.from_text(text=f"""Tool execution for this turn is complete.

Write the final assistant reply to the user now.
- Do not call tools.
- Do not mention internal routing or hidden mechanics.
- Refer to files or job cards as already shown in the UI instead of pasting URLs.
- Keep it concise and action-oriented.

Tool summary:
{summary}
""")],
    )
    try:
        response = gemini_client.models.generate_content(
            model=MODEL,
            contents=[*contents, completion_prompt],
            config=types.GenerateContentConfig(
                system_instruction=full_system,
                temperature=0.3,
            ),
        )
        text = _response_text(response).strip()
        if text:
            return text
    except Exception as error:
        logger.warning("tool-only follow-up generation failed: %s", error)

    return _deterministic_tool_only_fallback(executed_tools)


def _document_sections_from_args(args: dict) -> dict:
    sections = args.get("sections")
    return sections if isinstance(sections, dict) else {}


def _ensure_document_job_record(
    *,
    user_id: str,
    conversation_id: str,
    args: dict,
) -> str | None:
    sections = _document_sections_from_args(args)
    role = str(sections.get("role") or sections.get("title") or "").strip()
    company = str(sections.get("company") or "").strip() or None
    doc_type = str(args.get("doc_type", "document")).replace("_", " ").strip()
    title = role or f"Direct {doc_type} generation"
    if company and company.lower() not in title.lower():
        title = f"{title} at {company}"

    summary = str(sections.get("summary") or "").strip()
    description_lines = [f"Direct {doc_type} generation request"]
    if role:
        description_lines.append(f"Role: {role}")
    if company:
        description_lines.append(f"Company: {company}")
    if summary:
        description_lines.append(f"Summary: {summary[:500]}")

    job_data = supabase.table("jobs").insert({
        "conversation_id": conversation_id,
        "user_id": user_id,
        "title": title,
        "company": company,
        "description_md": "\n".join(description_lines),
    }).execute()
    if job_data.data:
        return job_data.data[0]["id"]
    return None


async def _execute_tool(
    function_call: types.FunctionCall,
    user_id: str,
    conversation_id: str,
    job_id: str | None,
    progress_callback=None,
) -> tuple[dict, str | None]:
    """Execute a Gemini function call and return result + optional updated job_id."""
    name = function_call.name
    args = dict(function_call.args) if function_call.args else {}
    logger.info("tool_call name=%s args=%s", name, {k: str(v)[:80] for k, v in args.items()})

    if name == "search_jobs":
        result = await tools.search_jobs(**args)
        logger.info("tool_result search_jobs results=%d", len(result) if isinstance(result, list) else 0)
    elif name == "scrape_job":
        result = await tools.scrape_job(**args)
        if "error" not in result:
            md_len = len(result.get("description_md", ""))
            logger.info("tool_result scrape_job md_len=%d", md_len)
            job_data = supabase.table("jobs").insert({
                "conversation_id": conversation_id,
                "user_id": user_id,
                "title": result.get("title") or args.get("url", ""),
                "url": result.get("canonical_url") or result.get("url") or args.get("url", ""),
                "description_md": result.get("description_md", ""),
            }).execute()
            if job_data.data:
                job_id = job_data.data[0]["id"]
                logger.info("tool_result scrape_job saved job_id=%s", job_id[:8])
        else:
            logger.warning("tool_result scrape_job error=%s", result["error"])
    elif name == "generate_document":
        if not job_id:
            job_id = _ensure_document_job_record(
                user_id=user_id,
                conversation_id=conversation_id,
                args=args,
            )
            if job_id:
                logger.info("tool_result generate_document created synthetic job_id=%s", job_id[:8])
            else:
                logger.warning("tool_result generate_document no job_id")
                return {"error": "Unable to create a job record for this document request."}, job_id

        result = await tools.generate_document(
            doc_type=args.get("doc_type", "resume"),
            sections=_document_sections_from_args(args),
            user_id=user_id,
            job_id=job_id,
            progress_callback=progress_callback,
            conversation_id=conversation_id,
        )
        if "error" in result:
            logger.error("tool_result generate_document error=%s", result["error"])
        else:
            logger.info("tool_result generate_document doc_id=%s", result.get("document_id", "?")[:8])
    elif name == "save_user_context":
        result = await tools.save_user_context(
            user_id=user_id,
            category=args.get("category", ""),
            content=args.get("content", {}),
            conversation_id=conversation_id,
        )
        logger.info("tool_result save_user_context category=%s", args.get("category"))
    elif name == "present_job_results":
        count = len(args.get("results", []))
        logger.info("tool_result present_job_results count=%d", count)
        return {"results": args.get("results", [])}, job_id
    else:
        result = {"error": f"Unknown tool: {name}"}
        logger.warning("tool_result unknown tool=%s", name)

    return result, job_id


async def stream_chat(
    conversation_id: str,
    user_id: str,
    user_message: str,
    mode: str,
    attachment_file_ids: list[str] | None = None,
) -> AsyncGenerator[ServerSentEvent, None]:
    """Stream a chat response with function calling via SSE."""
    logger.info("stream conv=%s mode=%s msg=%s", conversation_id[:8], mode, user_message[:60])

    attachment_file_ids = attachment_file_ids or []
    history = _build_history(conversation_id)
    all_files = _get_conversation_files(conversation_id)
    is_first_exchange = len(history) == 0
    context_prompt = _build_context_prompt(user_id)

    activity_trace: list[dict] = []
    initial_status = _status_payload(
        step_id="understanding_request",
        phase="understanding_request",
        label="Understanding request",
        state="running",
    )
    _upsert_activity_trace(activity_trace, initial_status)
    yield ServerSentEvent(data=json.dumps(initial_status), event="status")
    await asyncio.sleep(0)
    router = await asyncio.to_thread(
        _analyze_turn,
        user_message=user_message,
        mode=mode,
        context_prompt=context_prompt,
        history=history,
    )

    router_done_status = _router_status_payload(router, "done")
    _upsert_activity_trace(activity_trace, router_done_status)
    yield ServerSentEvent(data=json.dumps(router_done_status), event="status")
    await asyncio.sleep(0)

    supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "role": "user",
        "content": user_message,
        "metadata": {
            "router": router,
            "attachment_file_ids": attachment_file_ids,
        },
    }).execute()

    logger.info(
        "stream history=%d messages, files=%d, router_intent=%s, tools_allowed=%s",
        len(history),
        len(all_files),
        router.get("intent"),
        router.get("allow_tools"),
    )

    # Build system prompt based on mode
    if mode == "job_to_resume":
        system_prompt = JOB_TO_RESUME_PROMPT
    elif mode == "find_jobs":
        if all_files and is_first_exchange:
            system_prompt = FIND_JOBS_WITH_FILE_PROMPT
            logger.info("stream using FIND_JOBS_WITH_FILE prompt")
        else:
            system_prompt = FIND_JOBS_PROMPT
    else:
        system_prompt = JOB_TO_RESUME_PROMPT

    full_system = f"""{system_prompt}

{context_prompt}

Turn routing guidance:
- intent: {router.get("intent")}
- response_mode: {router.get("response_mode")}
- tools_allowed: {router.get("allow_tools")}
- reason: {router.get("reason")}

If tools_allowed is false, do not call any tools on this turn. Answer directly or ask one focused follow-up question."""

    current_files = _get_conversation_files(conversation_id, attachment_file_ids) if attachment_file_ids else []
    if not current_files and all_files and is_first_exchange:
        current_files = all_files

    contents = list(history)
    contents.append(_build_user_message_content(user_message, current_files))
    if current_files:
        logger.info(
            "stream attached files=%s",
            [file_record["id"][:8] for file_record in current_files],
        )

    # Track job_id for document generation
    existing_jobs = supabase.table("jobs").select("id").eq("conversation_id", conversation_id).order("created_at", desc=True).limit(1).execute()
    job_id = existing_jobs.data[0]["id"] if existing_jobs.data else None

    full_response = ""
    executed_tools: list[dict] = []
    max_tool_rounds = 5

    for tool_round in range(max_tool_rounds):
        has_function_call = False
        function_call_content = None

        logger.info("stream round=%d calling Gemini...", tool_round + 1)
        try:
            config_kwargs = {
                "system_instruction": full_system,
                "temperature": 0.7,
            }
            tools_for_turn = _tools_for_router(router)
            if tools_for_turn:
                config_kwargs["tools"] = tools_for_turn
            response_stream = gemini_client.models.generate_content_stream(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as e:
            logger.error("gemini API error: %s", e)
            yield ServerSentEvent(
                data=json.dumps({"message": f"AI error: {str(e)}"}),
                event="error",
            )
            break

        for chunk in response_stream:
            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue

            for part in chunk.candidates[0].content.parts:
                if part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    function_call_content = chunk.candidates[0].content

                    running_status = _tool_status_payload(
                        name=fc.name,
                        args=dict(fc.args) if fc.args else {},
                        state="running",
                    )
                    _upsert_activity_trace(activity_trace, running_status)
                    yield ServerSentEvent(data=json.dumps(running_status), event="status")
                    await asyncio.sleep(0)

                    if fc.name == "generate_document":
                        progress_queue: asyncio.Queue[dict] = asyncio.Queue()
                        loop = asyncio.get_running_loop()

                        def progress_callback(event: dict) -> None:
                            loop.call_soon_threadsafe(progress_queue.put_nowait, event)

                        tool_task = asyncio.create_task(
                            _execute_tool(
                                fc,
                                user_id,
                                conversation_id,
                                job_id,
                                progress_callback=progress_callback,
                            )
                        )

                        while True:
                            if tool_task.done() and progress_queue.empty():
                                break
                            try:
                                progress_event = await asyncio.wait_for(
                                    progress_queue.get(),
                                    timeout=0.1,
                                )
                            except asyncio.TimeoutError:
                                continue

                            progress_status = _document_progress_status_payload(
                                dict(fc.args) if fc.args else {},
                                progress_event,
                            )
                            _upsert_activity_trace(activity_trace, progress_status)
                            yield ServerSentEvent(
                                data=json.dumps(progress_status),
                                event="status",
                            )
                            await asyncio.sleep(0)

                        result, job_id = await tool_task
                    else:
                        result, job_id = await _execute_tool(
                            fc,
                            user_id,
                            conversation_id,
                            job_id,
                        )
                    tool_state = "failed" if isinstance(result, dict) and "error" in result else "done"

                    completed_status = _tool_status_payload(
                        name=fc.name,
                        args=dict(fc.args) if fc.args else {},
                        state=tool_state,
                        result=result,
                    )
                    executed_tools.append({
                        "name": fc.name,
                        "args": dict(fc.args) if fc.args else {},
                        "state": tool_state,
                        "result": result,
                    })
                    _upsert_activity_trace(activity_trace, completed_status)
                    yield ServerSentEvent(data=json.dumps(completed_status), event="status")
                    await asyncio.sleep(0)

                    if fc.name == "generate_document":
                        for document in _result_documents(result if isinstance(result, dict) else None):
                            yield ServerSentEvent(
                                data=json.dumps(document),
                                event="document",
                            )
                            await asyncio.sleep(0)

                    # Emit job_result events for present_job_results
                    if fc.name == "present_job_results":
                        for job in result.get("results", []):
                            yield ServerSentEvent(data=json.dumps(job), event="job_result")
                        tool_response = {"status": "presented", "count": len(result.get("results", []))}
                    else:
                        # Gemini expects function responses as dicts
                        tool_response = result if isinstance(result, dict) else {"results": result}

                    contents.append(function_call_content)
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part.from_function_response(
                            name=fc.name,
                            response=tool_response,
                        )],
                    ))
                    break

                elif part.text:
                    full_response += part.text
                    yield ServerSentEvent(
                        data=json.dumps({"content": part.text}),
                        event="message",
                    )
                    await asyncio.sleep(0)

            if has_function_call:
                break

        if not has_function_call:
            break

    if not full_response.strip() and executed_tools:
        logger.warning(
            "stream conv=%s had %d tool-only round(s) with no assistant text; generating follow-up",
            conversation_id[:8],
            len(executed_tools),
        )
        followup_text = await asyncio.to_thread(
            _generate_tool_only_followup_text,
            full_system=full_system,
            contents=contents,
            executed_tools=executed_tools,
        )
        if followup_text:
            full_response = followup_text
            yield ServerSentEvent(
                data=json.dumps({"content": followup_text}),
                event="message",
            )
            await asyncio.sleep(0)

    # Save assistant response
    if full_response:
        logger.info("stream done conv=%s response=%d chars", conversation_id[:8], len(full_response))
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": full_response,
            "metadata": {
                "activity_trace": activity_trace,
            },
        }).execute()

        # Auto-title: update conversation title from first user message if still default
        conv = supabase.table("conversations").select("title").eq("id", conversation_id).maybe_single().execute()
        if conv.data and conv.data["title"] == "New conversation":
            title = user_message[:80].strip()
            if len(user_message) > 80:
                title = title.rsplit(" ", 1)[0] + "..."
            supabase.table("conversations").update({"title": title}).eq("id", conversation_id).execute()
    else:
        logger.warning("stream done conv=%s NO response text", conversation_id[:8])
