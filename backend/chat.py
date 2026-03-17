import json
import logging
from typing import AsyncGenerator
from google import genai
from google.genai import types
from sse_starlette.sse import ServerSentEvent
from config import settings
from db import supabase
import tools

logger = logging.getLogger(__name__)

gemini_client = genai.Client(api_key=settings.gemini_api_key)

MODEL = "gemini-2.5-flash"

# Gemini function declarations
TOOL_DECLARATIONS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
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
        ),
        types.FunctionDeclaration(
            name="scrape_job",
            description="Extract the full job description from a URL. Use after finding a job URL or when the user provides one.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "url": types.Schema(type=types.Type.STRING, description="URL of the job posting"),
                },
                required=["url"],
            ),
        ),
        types.FunctionDeclaration(
            name="generate_document",
            description="Generate a resume or cover letter as a .docx file. Use only after you have gathered enough information about the user and the job.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "doc_type": types.Schema(type=types.Type.STRING, description="'resume' or 'cover_letter'"),
                    "sections": types.Schema(
                        type=types.Type.OBJECT,
                        description="Template variables. Resume: {name, title, summary, experiences: [{company, role, dates, bullets}], skills, education}. Cover letter: {name, date, company, hiring_manager, role, paragraphs: [str]}",
                    ),
                },
                required=["doc_type", "sections"],
            ),
        ),
        types.FunctionDeclaration(
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
        ),
        types.FunctionDeclaration(
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
        ),
    ]
)

JOB_TO_RESUME_PROMPT = """You are a career assistant helping the user create a tailored resume and cover letter for a specific job.

Your workflow:
1. Ask the user what position they're interested in, or accept a job URL
2. Use search_jobs to find the posting, or scrape_job if they give a URL
3. Analyze the job requirements
4. Ask the user targeted questions about their relevant experience, skills, and education — one or two questions at a time, not everything at once
5. When you learn something important about the user, use save_user_context to remember it
6. Once you have enough info, use generate_document to create the resume and cover letter

Be conversational and helpful. Ask specific questions based on what the job requires. Don't ask for information you already have from the user's context.

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
response. The UI will automatically show a download card."""

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

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card."""


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


def _get_conversation_file(conversation_id: str) -> dict | None:
    """Get the uploaded file for a conversation. Returns the file record or None."""
    result = supabase.table("conversation_files").select("*").eq("conversation_id", conversation_id).limit(1).execute()
    return result.data[0] if result.data else None


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
) -> AsyncGenerator[ServerSentEvent, None]:
    """Stream a chat response with function calling via SSE."""
    logger.info("stream conv=%s mode=%s msg=%s", conversation_id[:8], mode, user_message[:60])

    # Save user message
    supabase.table("messages").insert({
        "conversation_id": conversation_id,
        "role": "user",
        "content": user_message,
    }).execute()

    # Check for uploaded file (used for both prompt selection and content building)
    file_record = _get_conversation_file(conversation_id)

    # Build history (includes the just-saved user message)
    history = _build_history(conversation_id)
    logger.info("stream history=%d messages, file=%s", len(history), bool(file_record))

    # Build system prompt based on mode
    if mode == "job_to_resume":
        system_prompt = JOB_TO_RESUME_PROMPT
    elif mode == "find_jobs":
        # history has 1 entry = this is the first exchange
        if file_record and len(history) <= 1:
            system_prompt = FIND_JOBS_WITH_FILE_PROMPT
            logger.info("stream using FIND_JOBS_WITH_FILE prompt")
        else:
            system_prompt = FIND_JOBS_PROMPT
    else:
        system_prompt = JOB_TO_RESUME_PROMPT

    context_prompt = _build_context_prompt(user_id)
    full_system = f"{system_prompt}\n\n{context_prompt}"

    # If file exists and this is the first exchange, replace the user message
    # in history with a version that includes the file attachment
    if file_record and len(history) <= 1 and history:
        history.pop()
        user_parts = [
            types.Part.from_uri(
                file_uri=file_record["gemini_file_uri"],
                mime_type=file_record["mime_type"],
            ),
            types.Part.from_text(text=user_message),
        ]
        history.append(types.Content(role="user", parts=user_parts))
        logger.info("stream attached file uri=%s", file_record["gemini_file_uri"])

    # Track job_id for document generation
    existing_jobs = supabase.table("jobs").select("id").eq("conversation_id", conversation_id).order("created_at", desc=True).limit(1).execute()
    job_id = existing_jobs.data[0]["id"] if existing_jobs.data else None

    contents = history
    full_response = ""
    max_tool_rounds = 5

    for tool_round in range(max_tool_rounds):
        has_function_call = False
        function_call_content = None

        logger.info("stream round=%d calling Gemini...", tool_round + 1)
        try:
            response_stream = gemini_client.models.generate_content_stream(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=full_system,
                    tools=[TOOL_DECLARATIONS],
                    temperature=0.7,
                ),
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
                        data=json.dumps({"tool": fc.name, "state": "running"}),
                        event="status",
                    )

                    result, job_id = await _execute_tool(fc, user_id, conversation_id, job_id)

                    yield ServerSentEvent(
                        data=json.dumps({"tool": fc.name, "state": "done"}),
                        event="status",
                    )

                    if fc.name == "generate_document" and "document_id" in result:
                        yield ServerSentEvent(
                            data=json.dumps(result),
                            event="document",
                        )

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
