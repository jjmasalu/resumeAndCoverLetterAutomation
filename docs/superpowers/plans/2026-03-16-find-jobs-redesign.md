# Find Jobs Mode Redesign — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Find Jobs mode to accept resume uploads via Gemini's multimodal API, present structured job results as inline cards, and update the landing page with a tab switcher for both modes.

**Architecture:** File upload flows through a new `/conversations/{id}/upload` endpoint that stores files in Supabase Storage and registers them with Gemini's Files API. A new `present_job_results` Gemini tool lets the AI emit structured `job_result` SSE events after scoring matches. The frontend gets two new components (`FileUpload`, `JobCard`) and mode-aware chat pages.

**Tech Stack:** Next.js 16 / React 19 / Tailwind CSS v4, Python FastAPI, Gemini 2.5 Flash (`google.genai` SDK), Supabase (Postgres + Auth + Storage)

**Spec:** `docs/superpowers/specs/2026-03-16-find-jobs-redesign-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `supabase/migrations/002_conversation_files.sql` | Migration for `conversation_files` table + RLS |
| `frontend/src/components/FileUpload.tsx` | Drag/drop + click upload zone with error states |
| `frontend/src/components/JobCard.tsx` | Inline job result card with match score + action buttons |

### Modified Files
| File | Changes |
|------|---------|
| `backend/models.py` | Add `UploadFileResponse` model |
| `backend/main.py` | Add `POST /conversations/{id}/upload` endpoint |
| `backend/chat.py:18-71` | Add `present_job_results` tool declaration |
| `backend/chat.py:88-100` | Update Find Jobs system prompts |
| `backend/chat.py:131-175` | Add `present_job_results` to `_execute_tool()` |
| `backend/chat.py:178-300` | Add file-aware contents + `job_result` SSE emission in `stream_chat()` |
| `frontend/src/lib/api.ts` | Add `apiUpload()` function |
| `frontend/src/app/page.tsx` | Tab switcher landing page |
| `frontend/src/app/(app)/chat/page.tsx` | Mode-specific empty states with upload zone |
| `frontend/src/app/(app)/chat/[id]/page.tsx` | Attachment button, JobCard rendering, `job_result` SSE |

---

## Chunk 1: Database & Backend Foundation

### Task 1: Supabase Migration — `conversation_files` Table

**Files:**
- Create: `supabase/migrations/002_conversation_files.sql`

- [ ] **Step 1: Write the migration**

```sql
-- conversation_files: stores uploaded resume/document metadata
create table conversation_files (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  storage_path text not null,
  gemini_file_uri text not null,
  mime_type text not null,
  file_size bigint not null,
  created_at timestamptz not null default now()
);

create index idx_conversation_files_conversation on conversation_files(conversation_id);
create index idx_conversation_files_user on conversation_files(user_id);

alter table conversation_files enable row level security;

create policy "Users can read own files"
  on conversation_files for select
  using (user_id = auth.uid());

create policy "Users can insert own files"
  on conversation_files for insert
  with check (user_id = auth.uid());
```

- [ ] **Step 2: Apply the migration**

Use the Supabase MCP to apply this migration, or if running locally:
```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation
supabase db push
```

- [ ] **Step 3: Create a Supabase Storage bucket for uploads**

The existing `documents` bucket is for generated output files. Create a new `uploads` bucket for user-uploaded files:

Use the Supabase MCP or run SQL:
```sql
insert into storage.buckets (id, name, public)
values ('uploads', 'uploads', false);

create policy "Users can upload own files"
  on storage.objects for insert
  with check (bucket_id = 'uploads' and auth.uid()::text = (storage.foldername(name))[1]);

create policy "Users can read own uploads"
  on storage.objects for select
  using (bucket_id = 'uploads' and auth.uid()::text = (storage.foldername(name))[1]);
```

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/002_conversation_files.sql
git commit -m "Add conversation_files table and uploads storage bucket"
```

---

### Task 2: Backend Models for File Upload

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add the upload response model**

Add after the existing `DocumentResponse` class (after line 50):

```python
class UploadFileResponse(BaseModel):
    file_id: str
    filename: str
    gemini_file_uri: str
```

- [ ] **Step 2: Verify no import changes needed**

The existing imports (`BaseModel`, `str`, `Optional`) are sufficient. No new imports.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "Add UploadFileResponse model"
```

---

### Task 3: File Upload Endpoint

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add imports**

Add to the existing imports at the top of `main.py`:

```python
import tempfile
import os
from fastapi import UploadFile, File
```

Also import the Gemini client from `chat.py` (reuse the existing one instead of creating a second instance):
```python
from chat import stream_chat, gemini_client
```

Also import the new model:
```python
from models import CreateConversationRequest, SendMessageRequest, ConversationResponse, UploadFileResponse
```

- [ ] **Step 2: Define allowed MIME types**

Add after the CORS setup (after line 23):

```python
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "image/png",
    "image/jpeg",
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
```

- [ ] **Step 3: Add the upload endpoint**

Add after the `POST /conversations/{conversation_id}/messages` endpoint (after line 148):

```python
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

    # Validate file type
    if not file.content_type or file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}. Supported: PDF, DOCX, PNG, JPG")

    # Read file bytes
    file_bytes = await file.read()

    # Validate file size
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File must be under 10MB")

    # Upload to Supabase Storage
    storage_path = f"{user_id}/{conversation_id}/{file.filename}"
    try:
        supabase.storage.from_("uploads").upload(
            storage_path,
            file_bytes,
            {"content-type": file.content_type},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(e)}")

    # Upload to Gemini Files API
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        gemini_file = gemini_client.files.upload(file=tmp_path)
    except Exception as e:
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
```

- [ ] **Step 4: Test manually**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/backend
python -m uvicorn main:app --reload
```

Use the `/docs` Swagger UI to test the upload endpoint with a small PDF.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "Add file upload endpoint for conversation attachments"
```

---

### Task 4: `present_job_results` Tool Declaration & Execution

**Files:**
- Modify: `backend/chat.py:18-71` (tool declarations)
- Modify: `backend/chat.py:131-175` (`_execute_tool`)

- [ ] **Step 1: Add the tool declaration**

Add after the `save_user_context` declaration (after line 69, before the closing `]` of `TOOL_DECLARATIONS`):

```python
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
```

- [ ] **Step 2: Add handling in `_execute_tool()`**

In the `_execute_tool()` function (around line 131-175), add a new branch for `present_job_results` before the final `else` or at the end of the if/elif chain:

```python
    elif name == "present_job_results":
        # Return the results array so stream_chat() can emit job_result SSE events
        return args, None
```

This is a passthrough — `_execute_tool()` returns the args directly. `stream_chat()` will handle the SSE emission (Task 6).

- [ ] **Step 3: Commit**

```bash
git add backend/chat.py
git commit -m "Add present_job_results tool declaration and execution"
```

---

## Chunk 2: Backend AI Integration

### Task 5: Update Find Jobs System Prompts

**Files:**
- Modify: `backend/chat.py:88-100` (find_jobs system prompt)

- [ ] **Step 1: Delete the `SYSTEM_PROMPTS` dict and replace with standalone constants**

Delete the entire `SYSTEM_PROMPTS = { ... }` dict (lines 73-101) and replace with three standalone prompt constants:

```python
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
```

- [ ] **Step 2: Add a helper to check for uploaded files**

Add after `_build_history()` (after line 128):

```python
def _get_conversation_file(conversation_id: str) -> dict | None:
    """Get the uploaded file for a conversation. Returns the file record or None."""
    result = supabase.table("conversation_files").select("*").eq("conversation_id", conversation_id).limit(1).execute()
    return result.data[0] if result.data else None
```

- [ ] **Step 3: Update the prompt building in `stream_chat()`**

In `stream_chat()`, replace line 194 (`system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["job_to_resume"])`) with file-aware logic. **Important:** The file record lookup happens here once and is reused by Task 6 for the Gemini content building — do NOT query it again.

```python
    # Check for uploaded file (used for both prompt selection and content building)
    file_record = _get_conversation_file(conversation_id)

    # Build history (includes the just-saved user message)
    history = _build_history(conversation_id)

    # Build system prompt based on mode
    if mode == "job_to_resume":
        system_prompt = JOB_TO_RESUME_PROMPT
    elif mode == "find_jobs":
        # history has 1 entry = this is the first exchange
        if file_record and len(history) <= 1:
            system_prompt = FIND_JOBS_WITH_FILE_PROMPT
        else:
            system_prompt = FIND_JOBS_PROMPT
    else:
        system_prompt = JOB_TO_RESUME_PROMPT
```

Note: `len(history) <= 1` because `_build_history()` includes the just-saved user message. On the first exchange, history has exactly 1 message (the current user message).

- [ ] **Step 4: Commit**

```bash
git add backend/chat.py
git commit -m "Update Find Jobs system prompts for file upload and present_job_results"
```

---

### Task 6: File-Aware `stream_chat()` + `job_result` SSE Emission

**Files:**
- Modify: `backend/chat.py:178-300` (`stream_chat`)

- [ ] **Step 1: Add file content to Gemini request**

In `stream_chat()`, **after** the prompt selection from Task 5 Step 3 and **before** `contents = history` (line 205), add logic to replace the last history entry (the current user message) with a file-aware version when applicable.

**Why replacement instead of append:** `_build_history()` already includes the user message we just saved at line 187-191. If we append again, Gemini receives the user message twice. Instead, we pop the last entry and replace it with one that includes the file part.

```python
    # If file exists and this is the first exchange, replace the user message
    # in history with a version that includes the file attachment
    if file_record and len(history) <= 1 and history:
        # Pop the text-only user message that _build_history() loaded
        history.pop()
        # Re-add with file part included
        user_parts = [
            types.Part.from_uri(
                file_uri=file_record["gemini_file_uri"],
                mime_type=file_record["mime_type"],
            ),
            types.Part.from_text(user_message),
        ]
        history.append(types.Content(role="user", parts=user_parts))

    contents = history
```

This replaces the existing `contents = history` line (205). The rest of `stream_chat()` continues unchanged — `contents` is used in `generate_content_stream()`.

- [ ] **Step 2: Add `job_result` SSE emission for `present_job_results`**

In the tool-calling loop inside `stream_chat()`, after `_execute_tool()` returns (line 246: `result, job_id = await _execute_tool(fc, user_id, conversation_id, job_id)`), add handling for `present_job_results` alongside the existing `generate_document` handling.

Replace lines 253-260 (the `generate_document` check and `tool_response` assignment) with:

```python
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
```

Note: For `present_job_results`, `result` (from `_execute_tool()`) is the `args` dict containing `{"results": [...]}` since Task 4 passes it through. The `tool_response` sent back to Gemini is overridden to `{"status": "presented", "count": N}` so the AI knows the cards were shown.

- [ ] **Step 3: Verify integration**

The complete flow in the tool-call block (lines 236-270) should now be:
1. `fc = part.function_call` — get the function call
2. Yield `status: running` event
3. `result, job_id = await _execute_tool(...)` — execute the tool
4. Yield `status: done` event
5. If `generate_document` → yield `document` event
6. If `present_job_results` → yield `job_result` events + override `tool_response`
7. Else → standard `tool_response` assignment
8. Append function call + response to contents

- [ ] **Step 4: Commit**

```bash
git add backend/chat.py
git commit -m "Add file-aware streaming and job_result SSE emission"
```

---

## Chunk 3: Frontend Components

### Task 7: `apiUpload` Helper

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the upload function**

Add after the existing `apiJson` function:

```typescript
export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const { createClient } = await import("@/lib/supabase/client");
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${session?.access_token}` },
    body: form,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Upload failed: ${res.status}`);
  }
  return res.json();
}
```

Note: Does NOT set `Content-Type` — the browser auto-sets `multipart/form-data` with the boundary.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "Add apiUpload helper for multipart file uploads"
```

---

### Task 8: `FileUpload` Component

**Files:**
- Create: `frontend/src/components/FileUpload.tsx`

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState, useRef, useCallback } from "react";

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "image/png",
  "image/jpeg",
];
const ACCEPTED_EXTENSIONS = ".pdf,.docx,.png,.jpg,.jpeg";
const MAX_SIZE = 10 * 1024 * 1024; // 10MB

interface FileUploadProps {
  onFileSelect: (file: File) => void;
  uploading?: boolean;
  uploadedFilename?: string | null;
}

export default function FileUpload({ onFileSelect, uploading, uploadedFilename }: FileUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const validate = useCallback((file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return "Supported formats: PDF, DOCX, PNG, JPG";
    }
    if (file.size > MAX_SIZE) {
      return "File must be under 10MB";
    }
    return null;
  }, []);

  const handleFile = useCallback(
    (file: File) => {
      setError(null);
      const err = validate(file);
      if (err) {
        setError(err);
        return;
      }
      onFileSelect(file);
    },
    [validate, onFileSelect]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  // Uploaded state
  if (uploadedFilename) {
    return (
      <div className="w-full max-w-xs border border-border rounded-xl px-4 py-3 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-accent-muted flex items-center justify-center flex-shrink-0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-xs text-text-primary truncate">{uploadedFilename}</div>
          <div className="text-[10px] text-text-tertiary">Uploaded</div>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-xs">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl px-6 py-8 text-center cursor-pointer transition ${
          dragOver
            ? "border-accent bg-accent-muted"
            : error
              ? "border-danger/50"
              : "border-border hover:border-text-tertiary"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          onChange={handleChange}
          className="hidden"
        />

        {uploading ? (
          <>
            <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
            <div className="text-xs text-text-secondary">Uploading...</div>
          </>
        ) : (
          <>
            <div className="w-10 h-10 rounded-lg bg-accent-muted flex items-center justify-center mx-auto mb-3">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
              </svg>
            </div>
            <div className="text-sm font-medium text-text-primary mb-1">Upload your resume</div>
            <div className="text-xs text-text-tertiary mb-3">PDF, DOCX, or image &mdash; we&apos;ll extract everything</div>
            <div className="inline-block bg-accent text-white text-xs font-medium px-4 py-1.5 rounded-lg">
              Choose file
            </div>
          </>
        )}
      </div>

      {error && (
        <div className="mt-2 flex items-center gap-1.5 px-1">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-danger flex-shrink-0">
            <circle cx="12" cy="12" r="10" />
            <path d="M15 9l-6 6M9 9l6 6" />
          </svg>
          <span className="text-xs text-danger">{error}</span>
          <button onClick={() => setError(null)} className="text-xs text-text-tertiary hover:text-text-secondary ml-auto">
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify it builds**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

Expected: build succeeds (component is not imported anywhere yet, but should have no syntax errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FileUpload.tsx
git commit -m "Add FileUpload component with drag-drop and error states"
```

---

### Task 9: `JobCard` Component

**Files:**
- Create: `frontend/src/components/JobCard.tsx`

- [ ] **Step 1: Create the component**

```tsx
"use client";

interface JobCardProps {
  title: string;
  url: string;
  snippet: string;
  matchScore: number;
  company?: string;
  location?: string;
  onAction: (action: string) => void;
}

function scoreBadge(score: number) {
  if (score >= 80) return { bg: "bg-[rgba(34,197,94,0.1)]", text: "text-success" };
  if (score >= 60) return { bg: "bg-[rgba(245,158,11,0.1)]", text: "text-warning" };
  return { bg: "bg-[rgba(239,68,68,0.1)]", text: "text-danger" };
}

export default function JobCard({ title, url, snippet, matchScore, company, location, onAction }: JobCardProps) {
  const badge = scoreBadge(matchScore);

  return (
    <div className="ml-9 my-2 bg-bg-secondary border border-border border-l-2 border-l-accent rounded-xl p-3.5 max-w-md">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="text-sm font-medium text-text-primary">{title}</div>
        <span className={`${badge.bg} ${badge.text} text-[10px] font-medium px-2 py-0.5 rounded-full flex-shrink-0`}>
          {matchScore}% match
        </span>
      </div>

      {/* Meta */}
      {(company || location) && (
        <div className="text-xs text-text-tertiary mb-1.5">
          {company}{company && location ? " · " : ""}{location}
        </div>
      )}

      {/* Snippet */}
      <div className="text-xs text-text-secondary leading-relaxed mb-2.5 line-clamp-2">
        {snippet}
      </div>

      {/* URL */}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[11px] text-accent hover:underline truncate block mb-3"
        style={{ overflowWrap: "anywhere" }}
      >
        {url.length > 60 ? url.slice(0, 60) + "..." : url}
      </a>

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={() => onAction(`Generate a tailored resume for this job: ${title} at ${company || "this company"} (${url})`)}
          className="bg-accent text-white text-[11px] font-medium px-3 py-1 rounded-lg hover:bg-accent-hover transition"
        >
          Generate Resume
        </button>
        <button
          onClick={() => onAction(`Show me the full job description for: ${title} at ${company || "this company"} (${url})`)}
          className="bg-bg-tertiary text-text-secondary text-[11px] font-medium px-3 py-1 rounded-lg hover:text-text-primary transition"
        >
          View Details
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it builds**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/JobCard.tsx
git commit -m "Add JobCard component with match score and action buttons"
```

---

## Chunk 4: Frontend Pages

### Task 10: `/chat` Page — Mode-Specific Empty States

**Files:**
- Modify: `frontend/src/app/(app)/chat/page.tsx`

- [ ] **Step 1: Rewrite the chat index page**

Replace the entire file with mode-aware empty states. When "Find Jobs" is selected, show the upload zone. When "Job → Resume" is selected, show the current text-only input.

```tsx
"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiJson, apiUpload } from "@/lib/api";
import { useApp } from "@/components/AppContext";
import FileUpload from "@/components/FileUpload";

export default function ChatIndexPage() {
  const searchParams = useSearchParams();
  const modeParam = searchParams.get("mode");
  const [mode, setMode] = useState<"job_to_resume" | "find_jobs">(
    modeParam === "find_jobs" ? "find_jobs" : "job_to_resume"
  );
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [uploadedFilename, setUploadedFilename] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const router = useRouter();
  const { refreshConversations } = useApp();

  const adjustTextarea = useCallback(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 160) + "px";
    }
  }, []);

  useEffect(() => {
    adjustTextarea();
  }, [input, adjustTextarea]);

  const createAndRedirect = async (message: string, file?: File) => {
    setSending(true);
    try {
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode }),
      });

      if (file) {
        setUploading(true);
        await apiUpload(`/conversations/${conv.id}/upload`, file);
        setUploading(false);
      }

      await refreshConversations();
      router.push(`/chat/${conv.id}?initial=${encodeURIComponent(message)}`);
    } catch (err) {
      console.error("Failed to create conversation:", err);
      setSending(false);
      setUploading(false);
    }
  };

  const handleSend = () => {
    if (!input.trim() || sending) return;
    createAndRedirect(input.trim());
  };

  const handleFileSelect = (file: File) => {
    setUploadedFilename(file.name);
    // Auto-create conversation and redirect
    createAndRedirect(
      "I've uploaded my resume. Please analyze it and help me find matching jobs.",
      file
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Empty state */}
      <div className="flex-1 flex flex-col items-center justify-center px-6">
        {mode === "job_to_resume" ? (
          <>
            <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h2 className="text-base font-semibold text-text-primary mb-1.5">Start a conversation</h2>
            <p className="text-sm text-text-tertiary text-center max-w-xs mb-5">
              Paste a job posting URL or describe the role you&apos;re targeting.
            </p>
          </>
        ) : (
          <>
            <FileUpload
              onFileSelect={handleFileSelect}
              uploading={uploading}
              uploadedFilename={uploadedFilename}
            />

            {!uploadedFilename && !uploading && (
              <>
                <div className="flex items-center gap-3 w-full max-w-xs my-4">
                  <div className="flex-1 h-px bg-border" />
                  <span className="text-xs text-text-tertiary">or</span>
                  <div className="flex-1 h-px bg-border" />
                </div>
                <p className="text-xs text-text-tertiary">Type your experience in the chat below</p>
              </>
            )}
          </>
        )}

        {/* Mode pills */}
        <div className="flex gap-2 mt-5">
          <button
            onClick={() => setMode("job_to_resume")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs transition ${
              mode === "job_to_resume"
                ? "bg-accent text-white"
                : "bg-bg-secondary border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
            }`}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
            Job &rarr; Resume
          </button>
          <button
            onClick={() => setMode("find_jobs")}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs transition ${
              mode === "find_jobs"
                ? "bg-accent text-white"
                : "bg-bg-secondary border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary"
            }`}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="11" cy="11" r="8" />
              <path d="m21 21-4.35-4.35" />
            </svg>
            Find Jobs
          </button>
        </div>
      </div>

      {/* Input bar */}
      <div className="border-t border-border px-5 py-3">
        <div className="max-w-3xl mx-auto">
          <div
            className={`flex items-end gap-2 bg-bg-secondary border border-border rounded-xl px-3.5 py-3 transition ${
              sending ? "opacity-50" : ""
            }`}
          >
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                mode === "find_jobs"
                  ? "Describe your experience and what roles you're looking for..."
                  : "Message Resume AI..."
              }
              rows={1}
              disabled={sending}
              className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary resize-none outline-none max-h-40"
            />
            <button
              onClick={handleSend}
              disabled={sending || !input.trim()}
              className={`w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 transition ${
                input.trim() && !sending
                  ? "bg-accent text-white"
                  : "bg-bg-tertiary text-text-tertiary"
              }`}
              aria-label="Send message"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </button>
          </div>
          <div className="flex justify-between mt-1.5 text-[10px] text-text-tertiary px-1">
            <span>Enter to send &middot; Shift+Enter for newline</span>
            <span>Powered by Gemini</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify it builds**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/chat/page.tsx
git commit -m "Add mode-specific empty states with file upload for Find Jobs"
```

---

### Task 11: `/chat/[id]` Page — Attachment Button, JobCard, `job_result` SSE

**Files:**
- Modify: `frontend/src/app/(app)/chat/[id]/page.tsx`

This task modifies the existing chat page to:
1. Add a `jobResults` state array and render `JobCard` components
2. Handle the `job_result` SSE event type
3. Add an attachment button (📎) for Find Jobs mode conversations
4. Wire JobCard action buttons to send messages

- [ ] **Step 1: Add imports**

Add at the top of the file:

```tsx
import JobCard from "@/components/JobCard";
import { apiUpload } from "@/lib/api";
```

- [ ] **Step 2: Add `jobResults` state and `JobResultEvent` interface**

Add alongside the existing interfaces and state declarations:

```tsx
interface JobResultEvent {
  title: string;
  url: string;
  snippet: string;
  match_score: number;
  company?: string;
  location?: string;
}
```

Add to state declarations (alongside `documents`, `statuses`, etc.):

```tsx
const [jobResults, setJobResults] = useState<JobResultEvent[]>([]);
```

- [ ] **Step 3: Clear `jobResults` at the start of `doSend` and handle `job_result` SSE**

In the `doSend` function, add `setJobResults([])` at the start (alongside the existing `setStatuses([])` call):

```tsx
    setStatuses([]);
    setJobResults([]);
```

In the SSE event handler loop (inside `doSend`), add a new branch after the `document` handler:

```tsx
                } else if (eventType === "job_result") {
                  setJobResults((prev) => [...prev, data]);
```

- [ ] **Step 4: Add the attachment button for Find Jobs mode**

Need to know the conversation mode. Get it from `activeConversation` in AppContext. Add this state check:

```tsx
const { conversations, setActiveConversation, activeConversation } = useApp();
```

Add attachment file handling:

```tsx
const fileInputRef = useRef<HTMLInputElement>(null);

const [attachError, setAttachError] = useState<string | null>(null);

const handleAttachment = async (e: React.ChangeEvent<HTMLInputElement>) => {
  const file = e.target.files?.[0];
  if (!file) return;
  setAttachError(null);
  try {
    await apiUpload(`/conversations/${id}/upload`, file);
    doSend(`I've uploaded an additional document: ${file.name}. Please review it.`);
  } catch (err) {
    console.error("Upload failed:", err);
    setAttachError("Upload failed — please try again.");
  }
  // Reset input so same file can be re-selected
  e.target.value = "";
};
```

- [ ] **Step 5: Update the JSX — render JobCards and attachment button**

In the message render area, add JobCards after status pills and before documents:

```tsx
          {jobResults.map((j, i) => (
            <JobCard
              key={`job-${i}`}
              title={j.title}
              url={j.url}
              snippet={j.snippet}
              matchScore={j.match_score}
              company={j.company}
              location={j.location}
              onAction={(msg) => {
                setInput("");
                doSend(msg);
              }}
            />
          ))}
```

In the input bar, add the attachment button before the textarea (only for `find_jobs` mode):

```tsx
            {activeConversation?.mode === "find_jobs" && (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.png,.jpg,.jpeg"
                  onChange={handleAttachment}
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={streaming}
                  className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0 bg-accent-muted text-accent hover:bg-accent/20 transition"
                  aria-label="Attach file"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                </button>
                {attachError && (
                  <span className="text-xs text-red-500">{attachError}</span>
                )}
              </>
            )}
```

- [ ] **Step 6: Verify it builds**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/\(app\)/chat/\[id\]/page.tsx
git commit -m "Add JobCard rendering, job_result SSE, and attachment button"
```

---

### Task 12: Landing Page — Tab Switcher

**Files:**
- Modify: `frontend/src/app/page.tsx`

- [ ] **Step 1: Rewrite the landing page with tab switcher**

Replace the entire file. Key changes from current:
- Add `activeTab` state toggling between "job_to_resume" and "find_jobs"
- "I have a job posting" tab: same URL input as current
- "Find jobs for me" tab: upload zone + "or describe your experience" link
- Auth gating: on upload interaction, check auth first. If unauthenticated, redirect to `/login?returnTo=/chat&mode=find_jobs`

```tsx
"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { apiJson, apiUpload } from "@/lib/api";

const BRAND_NAME = "Resume AI";

type Tab = "job_to_resume" | "find_jobs";

export default function LandingPage() {
  const [activeTab, setActiveTab] = useState<Tab>("job_to_resume");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const ensureAuth = async (returnTo?: string): Promise<boolean> => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      const path = returnTo ? `/login?returnTo=${encodeURIComponent(returnTo)}` : "/login";
      router.push(path);
      return false;
    }
    return true;
  };

  const handleUrlSubmit = async () => {
    if (!input.trim()) return;
    setLoading(true);
    try {
      if (!(await ensureAuth())) return;
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode: "job_to_resume" }),
      });
      const message = `I want to apply for this job: ${input.trim()}`;
      router.push(`/chat/${conv.id}?initial=${encodeURIComponent(message)}`);
    } catch {
      router.push("/login");
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (file: File) => {
    setUploading(true);
    try {
      if (!(await ensureAuth())) { setUploading(false); return; }
      const conv = await apiJson<{ id: string }>("/conversations", {
        method: "POST",
        body: JSON.stringify({ mode: "find_jobs" }),
      });
      await apiUpload(`/conversations/${conv.id}/upload`, file);
      router.push(`/chat/${conv.id}?initial=${encodeURIComponent("I've uploaded my resume. Please analyze it and help me find matching jobs.")}`);
    } catch {
      router.push("/login");
    } finally {
      setUploading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileUpload(file);
  };

  const handleUploadClick = async () => {
    if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
    fileInputRef.current?.click();
  };

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Nav */}
      <header className="flex items-center justify-between px-8 py-4 max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 bg-accent rounded-md flex items-center justify-center text-[11px] font-bold text-white">R</div>
          <span className="font-semibold text-sm text-text-primary">{BRAND_NAME}</span>
        </div>
        <div className="flex items-center gap-5">
          <a href="#how-it-works" className="text-sm text-text-secondary hover:text-text-primary transition">How it works</a>
          <div className="w-px h-4 bg-border" />
          <a href="/login" className="text-sm text-text-secondary hover:text-text-primary transition">Sign in</a>
          <a
            href="/login"
            className="px-4 py-1.5 text-sm font-medium text-white bg-accent rounded-md hover:bg-accent-hover transition"
          >
            Get Started
          </a>
        </div>
      </header>

      {/* Hero */}
      <section className="text-center px-6 pt-20 pb-10 max-w-3xl mx-auto relative">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[600px] h-[300px] bg-[radial-gradient(ellipse,var(--accent-muted)_0%,transparent_70%)] pointer-events-none" />

        <div className="relative">
          <div className="inline-flex items-center gap-1.5 px-3.5 py-1 border border-border rounded-full text-[11px] text-text-secondary bg-bg-secondary mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-accent" />
            AI-powered job applications
          </div>

          <h1 className="text-4xl md:text-5xl font-bold text-text-primary leading-tight mb-4 tracking-tight">
            Land interviews,<br />not rejections
          </h1>

          <p className="text-base text-text-tertiary max-w-md mx-auto mb-8 leading-relaxed">
            Two tools. One goal. Get the right job with the right documents.
          </p>

          {/* Tab Switcher */}
          <div className="max-w-lg mx-auto">
            <div className="flex bg-bg-secondary border border-border rounded-lg p-1 mb-4">
              <button
                onClick={() => setActiveTab("job_to_resume")}
                className={`flex-1 text-center py-2 text-xs font-medium rounded-md transition ${
                  activeTab === "job_to_resume"
                    ? "bg-accent text-white"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                I have a job posting
              </button>
              <button
                onClick={() => setActiveTab("find_jobs")}
                className={`flex-1 text-center py-2 text-xs font-medium rounded-md transition ${
                  activeTab === "find_jobs"
                    ? "bg-accent text-white"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                Find jobs for me
              </button>
            </div>

            {/* Tab Content */}
            {activeTab === "job_to_resume" ? (
              <>
                <div className="bg-bg-secondary border border-border rounded-xl p-1.5 flex gap-1.5">
                  <div className="flex-1 flex items-center gap-2 px-3">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-text-tertiary flex-shrink-0">
                      <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    </svg>
                    <input
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleUrlSubmit()}
                      placeholder="Paste a job posting URL..."
                      className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-tertiary outline-none py-2"
                    />
                  </div>
                  <button
                    onClick={handleUrlSubmit}
                    disabled={!input.trim() || loading}
                    className="px-6 py-2.5 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover transition disabled:opacity-50"
                  >
                    {loading ? "..." : "Generate"}
                  </button>
                </div>
                <div className="flex items-center justify-center gap-4 mt-3 text-[11px] text-text-tertiary">
                  <span>LinkedIn</span>
                  <span className="text-border">&middot;</span>
                  <span>Indeed</span>
                  <span className="text-border">&middot;</span>
                  <span>Greenhouse</span>
                  <span className="text-border">&middot;</span>
                  <span>Lever</span>
                  <span className="text-border">&middot;</span>
                  <span>Any URL</span>
                </div>
              </>
            ) : (
              <>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.docx,.png,.jpg,.jpeg"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <div
                  onClick={handleUploadClick}
                  onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                  onDrop={async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const file = e.dataTransfer.files?.[0];
                    if (file) {
                      if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
                      handleFileUpload(file);
                    }
                  }}
                  className="bg-bg-secondary border-2 border-dashed border-border rounded-xl p-8 text-center cursor-pointer hover:border-text-tertiary transition"
                >
                  {uploading ? (
                    <>
                      <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin mx-auto mb-3" />
                      <div className="text-sm text-text-secondary">Uploading...</div>
                    </>
                  ) : (
                    <>
                      <div className="w-10 h-10 rounded-lg bg-accent-muted flex items-center justify-center mx-auto mb-3">
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
                        </svg>
                      </div>
                      <div className="text-sm font-medium text-text-primary mb-1">Upload your resume</div>
                      <div className="text-xs text-text-tertiary mb-3">PDF, DOCX, or image</div>
                      <div className="inline-block bg-accent text-white text-xs font-medium px-4 py-1.5 rounded-lg">
                        Choose file
                      </div>
                    </>
                  )}
                </div>
                <div className="mt-3">
                  <button
                    onClick={async () => {
                      if (!(await ensureAuth("/chat?mode=find_jobs"))) return;
                      router.push("/chat?mode=find_jobs");
                    }}
                    className="text-xs text-text-tertiary hover:text-accent transition bg-transparent border-none cursor-pointer"
                  >
                    or describe your experience &rarr;
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </section>

      {/* Social proof */}
      <section className="flex items-center justify-center gap-8 py-6 border-t border-border-subtle max-w-3xl mx-auto">
        {[
          { value: "2.4k+", label: "Resumes generated" },
          { value: "30s", label: "Average generation time" },
          { value: "89%", label: "ATS pass rate" },
        ].map((stat, i) => (
          <div key={i} className="flex items-center gap-8">
            {i > 0 && <div className="w-px h-8 bg-border" />}
            <div className="text-center">
              <div className="text-xl font-bold text-text-primary">{stat.value}</div>
              <div className="text-[11px] text-text-tertiary">{stat.label}</div>
            </div>
          </div>
        ))}
      </section>

      {/* How it works */}
      <section id="how-it-works" className="py-16 px-6">
        <div className="text-center mb-10">
          <h2 className="text-2xl font-semibold text-text-primary tracking-tight mb-2">How it works</h2>
          <p className="text-sm text-text-tertiary">Three steps. No templates. No formatting.</p>
        </div>
        <div className="flex gap-4 max-w-2xl mx-auto">
          {[
            {
              icon: (
                <path d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
              ),
              title: "Paste a URL or upload",
              desc: "Drop any job posting link, or upload your resume to discover matching roles.",
            },
            {
              icon: (
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              ),
              title: "Chat with AI",
              desc: "Answer a few questions about your experience. The AI learns and remembers you.",
            },
            {
              icon: (
                <path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              ),
              title: "Download & apply",
              desc: "Get a tailored resume and cover letter as .docx files. Ready to submit.",
            },
          ].map((step, i) => (
            <div key={i} className="flex-1 bg-bg-secondary border border-border rounded-xl p-5">
              <div className="w-8 h-8 rounded-lg bg-accent-muted flex items-center justify-center mb-3">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
                  {step.icon}
                </svg>
              </div>
              <h3 className="text-sm font-semibold text-text-primary mb-1">{step.title}</h3>
              <p className="text-xs text-text-tertiary leading-relaxed">{step.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Footer */}
      <footer className="flex items-center justify-between px-8 py-5 border-t border-border-subtle max-w-6xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-accent rounded-sm flex items-center justify-center text-[8px] font-bold text-white">R</div>
          <span className="text-xs text-text-tertiary">{BRAND_NAME}</span>
        </div>
        <span className="text-[11px] text-text-tertiary">Built with care. Not with templates.</span>
      </footer>
    </div>
  );
}
```

- [ ] **Step 2: Verify it builds**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "Add tab switcher landing page with dual-mode hero"
```

---

### Task 13: Final Integration Verification

- [ ] **Step 1: Start the backend**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/backend
python -m uvicorn main:app --reload
```

- [ ] **Step 2: Start the frontend**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npm run dev
```

- [ ] **Step 3: Verify the landing page**

1. Visit `http://localhost:3000`
2. Confirm tab switcher shows "I have a job posting" (default) and "Find jobs for me"
3. Switch tabs — URL input swaps to upload zone
4. Click upload zone while not logged in → should redirect to `/login`

- [ ] **Step 4: Verify new chat flow (Job → Resume)**

1. Log in, click "+" in sidebar → navigates to `/chat` (no conversation created)
2. Type a message and send → conversation created, redirected to `/chat/{id}`, message auto-sent

- [ ] **Step 5: Verify new chat flow (Find Jobs)**

1. On `/chat`, select "Find Jobs" mode pill → upload zone appears
2. Upload a PDF → conversation created, file uploaded, redirected to `/chat/{id}`, AI analyzes resume
3. AI responds with extracted profile summary
4. Attachment button (📎) visible in chat input

- [ ] **Step 6: Verify JobCard rendering**

1. In a Find Jobs conversation, after the AI searches for jobs
2. AI calls `present_job_results` → `job_result` SSE events emitted
3. JobCards render inline in chat with match scores and action buttons
4. Click "Generate Resume" → sends message to AI
5. Click "View Details" → sends message to AI

- [ ] **Step 7: Final build check**

```bash
cd /Users/aham/projects/dev/resumeAndCoverLetterAutomation/frontend
npx next build 2>&1 | tail -10
```

- [ ] **Step 8: Commit any fixes from integration testing**

```bash
git add -A
git commit -m "Fix integration issues from end-to-end testing"
```
