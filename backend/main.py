import logging
import tempfile
import os
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from config import settings
from auth import get_current_user
from db import supabase
from models import (
    CreateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    UploadFileResponse,
    UpdateProfileRequest,
    UpdateUserContextRequest,
    BulkDeleteConversationsRequest,
)
from chat import stream_chat, gemini_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("api")
app = FastAPI(title="Resume & Cover Letter AI", version="0.1.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Profile ──────────────────────────────────────────────────────────


@app.get("/profile")
async def get_profile(user_id: str = Depends(get_current_user)):
    # Profile row
    profile = (
        supabase.table("profiles")
        .select("*")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    # User context rows
    user_context = (
        supabase.table("user_context")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )

    # Uploaded files
    files = (
        supabase.table("conversation_files")
        .select("id, conversation_id, filename, storage_path, mime_type, file_size, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    files_with_urls = []
    for f in files.data:
        try:
            signed = supabase.storage.from_("uploads").create_signed_url(
                f["storage_path"], 3600
            )
            f["download_url"] = signed.get("signedURL", "")
        except Exception:
            f["download_url"] = ""
        files_with_urls.append(f)

    # Generated documents
    docs = (
        supabase.table("generated_documents")
        .select("id, job_id, doc_type, file_url, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    docs_with_urls = []
    for d in docs.data:
        try:
            signed = supabase.storage.from_("documents").create_signed_url(
                d["file_url"], 3600
            )
            d["download_url"] = signed.get("signedURL", "")
        except Exception:
            d["download_url"] = ""
        docs_with_urls.append(d)

    return {
        "profile": profile.data,
        "user_context": user_context.data,
        "uploaded_files": files_with_urls,
        "generated_documents": docs_with_urls,
    }


@app.patch("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    user_id: str = Depends(get_current_user),
):
    result = (
        supabase.table("profiles")
        .update({"full_name": body.full_name})
        .eq("id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return result.data[0]


# ── User Context ─────────────────────────────────────────────────────


@app.put("/user-context/{context_id}")
async def update_user_context(
    context_id: str,
    body: UpdateUserContextRequest,
    user_id: str = Depends(get_current_user),
):
    # Verify ownership
    existing = (
        supabase.table("user_context")
        .select("id")
        .eq("id", context_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="User context not found")

    result = (
        supabase.table("user_context")
        .update({"content": body.content})
        .eq("id", context_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update user context")
    return result.data[0]


@app.delete("/user-context/{context_id}")
async def delete_user_context(
    context_id: str,
    user_id: str = Depends(get_current_user),
):
    # Verify ownership
    existing = (
        supabase.table("user_context")
        .select("id")
        .eq("id", context_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="User context not found")

    supabase.table("user_context").delete().eq("id", context_id).execute()
    return {"status": "deleted"}


# ── Conversations ────────────────────────────────────────────────────


@app.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    body: CreateConversationRequest,
    user_id: str = Depends(get_current_user),
):
    result = supabase.table("conversations").insert({
        "user_id": user_id,
        "mode": body.mode,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create conversation")

    row = result.data[0]
    return ConversationResponse(
        id=row["id"],
        mode=row["mode"],
        title=row["title"],
        status=row["status"],
        created_at=row["created_at"],
    )


@app.get("/conversations")
async def list_conversations(user_id: str = Depends(get_current_user)):
    result = (
        supabase.table("conversations")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@app.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    conv = (
        supabase.table("conversations")
        .select("*")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not conv or not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )

    # Load generated documents for this conversation's jobs
    jobs = (
        supabase.table("jobs")
        .select("id")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    docs = []
    if jobs.data:
        job_ids = [j["id"] for j in jobs.data]
        for job_id in job_ids:
            doc_results = (
                supabase.table("generated_documents")
                .select("id, doc_type, file_url")
                .eq("job_id", job_id)
                .execute()
            )
            for doc in doc_results.data:
                signed = supabase.storage.from_("documents").create_signed_url(
                    doc["file_url"], 3600
                )
                docs.append({
                    "document_id": doc["id"],
                    "doc_type": doc["doc_type"],
                    "download_url": signed.get("signedURL", ""),
                })

    return {**conv.data, "messages": messages.data, "documents": docs}


def _delete_conversation_storage(conversation_id: str):
    """Remove storage bucket files tied to a conversation before DB cascade delete."""
    # Remove uploaded files from "uploads" bucket
    uploads = (
        supabase.table("conversation_files")
        .select("storage_path")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    if uploads.data:
        paths = [f["storage_path"] for f in uploads.data]
        try:
            supabase.storage.from_("uploads").remove(paths)
        except Exception as e:
            logger.warning("Failed to remove upload files for conv %s: %s", conversation_id[:8], e)

    # Remove generated documents from "documents" bucket
    jobs = (
        supabase.table("jobs")
        .select("id")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    if jobs.data:
        job_ids = [j["id"] for j in jobs.data]
        for job_id in job_ids:
            docs = (
                supabase.table("generated_documents")
                .select("file_url")
                .eq("job_id", job_id)
                .execute()
            )
            if docs.data:
                doc_paths = [d["file_url"] for d in docs.data]
                try:
                    supabase.storage.from_("documents").remove(doc_paths)
                except Exception as e:
                    logger.warning("Failed to remove doc files for conv %s: %s", conversation_id[:8], e)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    # Verify ownership
    conv = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _delete_conversation_storage(conversation_id)
    supabase.table("conversations").delete().eq("id", conversation_id).execute()
    return {"status": "deleted"}


@app.post("/conversations/bulk-delete")
async def bulk_delete_conversations(
    body: BulkDeleteConversationsRequest,
    user_id: str = Depends(get_current_user),
):
    if not body.conversation_ids:
        return {"deleted": 0}

    # Verify all conversations belong to user
    convs = (
        supabase.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .in_("id", body.conversation_ids)
        .execute()
    )
    found_ids = {c["id"] for c in convs.data}

    deleted = 0
    for cid in body.conversation_ids:
        if cid not in found_ids:
            continue
        _delete_conversation_storage(cid)
        supabase.table("conversations").delete().eq("id", cid).execute()
        deleted += 1

    return {"deleted_count": deleted}


@app.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    user_id: str = Depends(get_current_user),
):
    # Verify conversation belongs to user
    conv = (
        supabase.table("conversations")
        .select("mode")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    async def event_generator():
        async for event in stream_chat(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=body.content,
            mode=conv.data["mode"],
        ):
            yield event

    return EventSourceResponse(event_generator())


@app.post("/conversations/{conversation_id}/upload", response_model=UploadFileResponse)
async def upload_file(
    conversation_id: str,
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
):
    # Verify conversation belongs to user
    conv = supabase.table("conversations").select("id").eq("id", conversation_id).eq("user_id", user_id).execute()
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    logger.info("upload conv=%s file=%s type=%s", conversation_id[:8], file.filename, file.content_type)

    # Validate file type
    if not file.content_type or file.content_type not in ALLOWED_MIME_TYPES:
        logger.warning("upload rejected: unsupported type %s", file.content_type)
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}. Supported: PDF, DOCX, PNG, JPG")

    # Read file bytes
    file_bytes = await file.read()

    # Validate file size
    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning("upload rejected: file too large (%d bytes)", len(file_bytes))
        raise HTTPException(status_code=400, detail="File must be under 10MB")

    logger.info("upload size=%d bytes, uploading to storage...", len(file_bytes))

    # Upload to Supabase Storage
    storage_path = f"{user_id}/{conversation_id}/{file.filename}"
    try:
        supabase.storage.from_("uploads").upload(
            storage_path,
            file_bytes,
            {"content-type": file.content_type},
        )
    except Exception as e:
        logger.error("storage upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(e)}")

    # Upload to Gemini Files API
    logger.info("upload uploading to Gemini Files API...")
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        gemini_file = gemini_client.files.upload(file=tmp_path)
        logger.info("upload gemini_uri=%s", gemini_file.uri)
    except Exception as e:
        logger.error("gemini upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Gemini Files API upload failed: {str(e)}")
    finally:
        if "tmp_path" in locals():
            os.unlink(tmp_path)

    # Store metadata
    result = supabase.table("conversation_files").insert({
        "conversation_id": conversation_id,
        "user_id": user_id,
        "filename": file.filename,
        "storage_path": storage_path,
        "gemini_file_uri": gemini_file.uri,
        "mime_type": file.content_type,
        "file_size": len(file_bytes),
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to save file metadata")

    row = result.data[0]
    return UploadFileResponse(
        file_id=row["id"],
        filename=row["filename"],
        gemini_file_uri=row["gemini_file_uri"],
    )


@app.get("/documents/{document_id}/download")
async def download_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
):
    doc = (
        supabase.table("generated_documents")
        .select("*")
        .eq("id", document_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")

    signed = supabase.storage.from_("documents").create_signed_url(
        doc.data["file_url"], 3600
    )
    return {"download_url": signed.get("signedURL", "")}


# ── Individual File & Document Deletes ───────────────────────────────


@app.delete("/conversation-files/{file_id}")
async def delete_conversation_file(
    file_id: str,
    user_id: str = Depends(get_current_user),
):
    # Verify ownership
    file_row = (
        supabase.table("conversation_files")
        .select("id, storage_path")
        .eq("id", file_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not file_row.data:
        raise HTTPException(status_code=404, detail="File not found")

    # Remove from storage
    try:
        supabase.storage.from_("uploads").remove([file_row.data["storage_path"]])
    except Exception as e:
        logger.warning("Failed to remove upload file %s: %s", file_id[:8], e)

    # Delete DB row
    supabase.table("conversation_files").delete().eq("id", file_id).execute()
    return {"status": "deleted"}


@app.delete("/generated-documents/{document_id}")
async def delete_generated_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
):
    # Verify ownership
    doc = (
        supabase.table("generated_documents")
        .select("id, file_url")
        .eq("id", document_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from storage
    try:
        supabase.storage.from_("documents").remove([doc.data["file_url"]])
    except Exception as e:
        logger.warning("Failed to remove document file %s: %s", document_id[:8], e)

    # Delete DB row
    supabase.table("generated_documents").delete().eq("id", document_id).execute()
    return {"status": "deleted"}


# ── Delete All Data ──────────────────────────────────────────────────


@app.delete("/profile/all-data")
async def delete_all_data(user_id: str = Depends(get_current_user)):
    """Delete all user data: storage files, conversations (cascade), context, and profile."""
    # Get all conversations for storage cleanup
    convs = (
        supabase.table("conversations")
        .select("id")
        .eq("user_id", user_id)
        .execute()
    )
    for c in convs.data:
        _delete_conversation_storage(c["id"])

    # Delete conversations (DB cascade handles messages, jobs, docs, files)
    supabase.table("conversations").delete().eq("user_id", user_id).execute()

    # Delete user context
    supabase.table("user_context").delete().eq("user_id", user_id).execute()

    # Note: profiles row is preserved so user can still sign in
    logger.info("Deleted all data for user %s", user_id[:8])
    return {"status": "deleted"}
