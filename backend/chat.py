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
    description="Search the web for job postings matching a query. Use when the user describes a role they want or asks to find jobs.",
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
    description="Extract the full job description from a URL. Use after finding a job URL or when the user provides one.",
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
                description="Structured content for the document. Resume: {name, title, summary, experiences: [{company, role, dates, bullets}], skills, education}. Cover letter: {name, date, company, hiring_manager, role, paragraphs: [str]}. Optional design input: theme_id in {'classic_professional','technical_compact'}.",
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
3. Analyze the job requirements
4. Ask the user targeted questions about their relevant experience, skills, and education — one or two questions at a time, not everything at once
5. When you learn something important about the user, use save_user_context to remember it
6. Once you have enough info, use generate_document to create the resume and cover letter

Be conversational and helpful. Ask specific questions based on what the job requires. Don't ask for information you already have from the user's context.

Cover letters must fit on one page. When preparing sections for generate_document, keep the cover letter to three concise body paragraphs plus a brief closing paragraph, avoid repeating resume bullets verbatim, and keep the total body around 220-300 words.

If you choose a design direction, do it by selecting an approved `theme_id` inside `sections`. Available themes:
- `classic_professional` for balanced, conservative presentation
- `technical_compact` for denser technical resumes and tighter page budgets

Do not invent custom themes or arbitrary formatting instructions. Pick from the approved theme ids only when it adds value.

IMPORTANT: When you generate a document, do NOT paste the download URL in your response. The UI will automatically show a download card. Just tell the user the document is ready and offer to make adjustments or generate additional documents."""

FIND_JOBS_WITH_FILE_PROMPT = """You are a career assistant helping the user find jobs that match their profile.

The user has uploaded their resume. Analyze it thoroughly — extract work experience,
skills, education, certifications, and any other relevant details. Respond with a
concise summary of what you found and ask if anything needs correction.

Use save_user_context to persist each category you extract (work_experience, skills,
education, certifications, personal_info).

Once the user confirms their profile, ask what kind of roles they're looking for
(or suggest based on their profile). Then use search_jobs to find matching positions.

For each promising result, use scrape_job to get the full description, then assess
how well it matches the user's profile (0-100%). Once you have assessed the results,
use present_job_results to show them to the user as structured cards.

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card.

When generating a cover letter, keep it to one page: three concise body paragraphs plus a brief closing paragraph, and avoid repeating the resume verbatim.

If a theme choice would help, set `theme_id` in `sections` to either `classic_professional` or `technical_compact`. Do not invent other theme names."""

FIND_JOBS_PROMPT = """You are a career assistant helping the user find jobs that match their profile.

Your workflow:
1. Review the user's existing context to understand their background
2. Ask focused questions to understand their experience, skills, education, and what they're looking for
3. Use save_user_context as you learn things about the user
4. Once you have enough context, ask what roles they want and use search_jobs to find matching positions
5. For each promising result, use scrape_job to get the full description, then assess how well it matches the user's profile (0-100%)
6. Use present_job_results to show results as structured cards
7. For selected jobs, generate tailored documents using generate_document

Be proactive in suggesting roles based on the user's skills and experience.

When generating a cover letter, keep it to one page: three concise body paragraphs plus a brief closing paragraph, and avoid repeating the resume verbatim.

If a theme choice would help, set `theme_id` in `sections` to either `classic_professional` or `technical_compact`. Do not invent other theme names.

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
        plan = result.get("document_plan") or {}
        repair_history = plan.get("repair_history") or []
        if repair_history:
            detail = f"Adjusted layout to fit {result.get('page_budget', 1)} page."
            meta["repair_actions"] = [item.get("action") for item in repair_history]
        else:
            detail = f"{label.replace('Generating ', '').capitalize()} ready."
        if result.get("theme_id"):
            meta["theme_id"] = result["theme_id"]
        if result.get("page_budget") is not None:
            meta["page_budget"] = result["page_budget"]
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
            detail = f"Found {len(result)} potential job posting{'s' if len(result) != 1 else ''}."
            meta = {"result_count": len(result)}
        elif name == "scrape_job" and isinstance(result, dict) and "error" not in result:
            detail = "Captured the job description."
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


async def _execute_tool(
    function_call: types.FunctionCall,
    user_id: str,
    conversation_id: str,
    job_id: str | None,
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
                "title": args.get("url", ""),
                "url": args.get("url", ""),
                "description_md": result.get("description_md", ""),
            }).execute()
            if job_data.data:
                job_id = job_data.data[0]["id"]
                logger.info("tool_result scrape_job saved job_id=%s", job_id[:8])
        else:
            logger.warning("tool_result scrape_job error=%s", result["error"])
    elif name == "generate_document":
        if not job_id:
            result = {"error": "No job has been scraped yet in this conversation."}
            logger.warning("tool_result generate_document no job_id")
        else:
            result = await tools.generate_document(
                doc_type=args.get("doc_type", "resume"),
                sections=args.get("sections", {}),
                user_id=user_id,
                job_id=job_id,
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

    yield ServerSentEvent(
        data=json.dumps(
            _status_payload(
                step_id="understanding_request",
                phase="understanding_request",
                label="Understanding request",
                state="running",
            )
        ),
        event="status",
    )
    await asyncio.sleep(0)
    router = await asyncio.to_thread(
        _analyze_turn,
        user_message=user_message,
        mode=mode,
        context_prompt=context_prompt,
        history=history,
    )

    yield ServerSentEvent(
        data=json.dumps(_router_status_payload(router, "done")),
        event="status",
    )
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

                    yield ServerSentEvent(
                        data=json.dumps(
                            _tool_status_payload(
                                name=fc.name,
                                args=dict(fc.args) if fc.args else {},
                                state="running",
                            )
                        ),
                        event="status",
                    )
                    await asyncio.sleep(0)

                    result, job_id = await _execute_tool(fc, user_id, conversation_id, job_id)
                    tool_state = "failed" if isinstance(result, dict) and "error" in result else "done"

                    yield ServerSentEvent(
                        data=json.dumps(
                            _tool_status_payload(
                                name=fc.name,
                                args=dict(fc.args) if fc.args else {},
                                state=tool_state,
                                result=result,
                            )
                        ),
                        event="status",
                    )
                    await asyncio.sleep(0)

                    if fc.name == "generate_document" and "document_id" in result:
                        yield ServerSentEvent(
                            data=json.dumps(result),
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

    # Save assistant response
    if full_response:
        logger.info("stream done conv=%s response=%d chars", conversation_id[:8], len(full_response))
        supabase.table("messages").insert({
            "conversation_id": conversation_id,
            "role": "assistant",
            "content": full_response,
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
