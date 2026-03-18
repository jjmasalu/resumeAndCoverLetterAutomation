# Profile Page & History Management Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a profile page to view/manage AI-learned data, uploaded files, and generated documents, plus bulk delete on the history page.

**Architecture:** New backend endpoints in `main.py` for CRUD on profile/context/files/docs with cascade delete logic. New frontend page at `/(app)/profile/page.tsx`. Enhanced history page with selection mode. Reusable `ConfirmDialog` component for all destructive actions.

**Tech Stack:** FastAPI, Supabase (Postgres + Storage), Next.js 15, React, Tailwind CSS

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `frontend/src/app/(app)/profile/page.tsx` | Profile page with all sections |
| `frontend/src/components/ConfirmDialog.tsx` | Reusable confirmation modal |

### Modified Files
| File | Changes |
|------|---------|
| `backend/models.py` | Add 3 new request models |
| `backend/main.py` | Add 9 new endpoints |
| `frontend/src/components/Sidebar.tsx` | Add Profile link to user menu |
| `frontend/src/app/(app)/history/page.tsx` | Add select mode + bulk delete + individual delete |
| `frontend/src/app/(app)/layout.tsx` | Add "Profile" to TopBar title logic |

---

## Chunk 1: Backend Endpoints

### Task 1: Add Request Models

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add 3 new Pydantic models to `models.py`**

Append after the `UploadFileResponse` class (line 57):

```python
class UpdateProfileRequest(BaseModel):
    full_name: str


class UpdateUserContextRequest(BaseModel):
    content: dict


class BulkDeleteConversationsRequest(BaseModel):
    conversation_ids: list[str]
```

- [ ] **Step 2: Verify the backend still starts**

Run: `cd backend && python -c "from models import UpdateProfileRequest, UpdateUserContextRequest, BulkDeleteConversationsRequest; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "add request models for profile and bulk delete endpoints"
```

---

### Task 2: Profile Endpoints (GET + PATCH)

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/models.py` (import)

- [ ] **Step 1: Add imports in `main.py`**

Add `UpdateProfileRequest` to the models import at `main.py:11`:

```python
from models import (
    CreateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    UploadFileResponse,
    UpdateProfileRequest,
)
```

- [ ] **Step 2: Add `GET /profile` endpoint**

Add after the `health` endpoint (after line 48) in `main.py`:

```python
@app.get("/profile")
async def get_profile(user_id: str = Depends(get_current_user)):
    # Profile info
    profile = supabase.table("profiles").select("id, full_name, email").eq("id", user_id).maybe_single().execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail="Profile not found")

    # AI-learned context
    context = supabase.table("user_context").select("id, category, content, updated_at").eq("user_id", user_id).order("category").execute()

    # Uploaded files
    files = supabase.table("conversation_files").select("id, filename, mime_type, file_size, storage_path, created_at, conversation_id").eq("user_id", user_id).order("created_at", desc=True).execute()
    uploaded_files = []
    for f in files.data:
        try:
            signed = supabase.storage.from_("uploads").create_signed_url(f["storage_path"], 3600)
            download_url = signed.get("signedURL", "")
        except Exception:
            download_url = ""
        uploaded_files.append({
            "id": f["id"],
            "filename": f["filename"],
            "mime_type": f["mime_type"],
            "file_size": f["file_size"],
            "download_url": download_url,
            "created_at": f["created_at"],
            "conversation_id": f["conversation_id"],
        })

    # Generated documents
    docs = supabase.table("generated_documents").select("id, doc_type, file_url, created_at, job_id").eq("user_id", user_id).order("created_at", desc=True).execute()
    generated_documents = []
    for d in docs.data:
        try:
            signed = supabase.storage.from_("documents").create_signed_url(d["file_url"], 3600)
            download_url = signed.get("signedURL", "")
        except Exception:
            download_url = ""
        generated_documents.append({
            "id": d["id"],
            "doc_type": d["doc_type"],
            "file_url": d["file_url"],
            "download_url": download_url,
            "created_at": d["created_at"],
            "job_id": d["job_id"],
        })

    return {
        "profile": profile.data,
        "user_context": context.data,
        "uploaded_files": uploaded_files,
        "generated_documents": generated_documents,
    }


@app.patch("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    user_id: str = Depends(get_current_user),
):
    result = supabase.table("profiles").update({"full_name": body.full_name}).eq("id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"full_name": result.data[0]["full_name"]}
```

- [ ] **Step 3: Test manually**

Run: `cd backend && python -c "import main; print('endpoints loaded OK')"`
Expected: No import errors

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "add profile get and update endpoints"
```

---

### Task 3: User Context Endpoints (PUT + DELETE)

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add `UpdateUserContextRequest` to imports in `main.py`**

Add to the models import block:

```python
from models import (
    CreateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    UploadFileResponse,
    UpdateProfileRequest,
    UpdateUserContextRequest,
)
```

- [ ] **Step 2: Add PUT and DELETE endpoints for user context**

Add after the `update_profile` endpoint:

```python
@app.put("/user-context/{context_id}")
async def update_user_context(
    context_id: str,
    body: UpdateUserContextRequest,
    user_id: str = Depends(get_current_user),
):
    existing = supabase.table("user_context").select("id").eq("id", context_id).eq("user_id", user_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Context entry not found")

    from datetime import datetime, timezone
    result = supabase.table("user_context").update({
        "content": body.content,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", context_id).execute()

    return result.data[0] if result.data else {"status": "updated"}


@app.delete("/user-context/{context_id}")
async def delete_user_context(
    context_id: str,
    user_id: str = Depends(get_current_user),
):
    existing = supabase.table("user_context").select("id").eq("id", context_id).eq("user_id", user_id).maybe_single().execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Context entry not found")

    supabase.table("user_context").delete().eq("id", context_id).execute()
    return {"status": "deleted"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "add user context update and delete endpoints"
```

---

### Task 4: Conversation Delete + Bulk Delete Endpoints

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add `BulkDeleteConversationsRequest` to imports**

Update the models import to include it:

```python
from models import (
    CreateConversationRequest,
    SendMessageRequest,
    ConversationResponse,
    UploadFileResponse,
    UpdateProfileRequest,
    UpdateUserContextRequest,
    BulkDeleteConversationsRequest,
)
```

- [ ] **Step 2: Add a helper function for conversation cascade delete**

Add this helper above the endpoint definitions (after the `ALLOWED_MIME_TYPES` / `MAX_FILE_SIZE` block):

```python
async def _delete_conversation_storage(conversation_id: str):
    """Clean up storage files before deleting a conversation (DB cascade handles rows)."""
    # Clean up uploaded files from storage
    files = supabase.table("conversation_files").select("storage_path").eq("conversation_id", conversation_id).execute()
    for f in files.data:
        try:
            supabase.storage.from_("uploads").remove([f["storage_path"]])
        except Exception as e:
            logger.warning("Failed to delete upload %s: %s", f["storage_path"], e)

    # Clean up generated documents from storage
    jobs = supabase.table("jobs").select("id").eq("conversation_id", conversation_id).execute()
    for job in jobs.data:
        docs = supabase.table("generated_documents").select("file_url").eq("job_id", job["id"]).execute()
        for d in docs.data:
            try:
                supabase.storage.from_("documents").remove([d["file_url"]])
            except Exception as e:
                logger.warning("Failed to delete document %s: %s", d["file_url"], e)
```

- [ ] **Step 3: Add DELETE single conversation endpoint**

Add after the user context endpoints:

```python
@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    conv = supabase.table("conversations").select("id").eq("id", conversation_id).eq("user_id", user_id).maybe_single().execute()
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    await _delete_conversation_storage(conversation_id)
    supabase.table("conversations").delete().eq("id", conversation_id).execute()
    return {"status": "deleted"}
```

- [ ] **Step 4: Add POST bulk delete endpoint**

```python
@app.post("/conversations/bulk-delete")
async def bulk_delete_conversations(
    body: BulkDeleteConversationsRequest,
    user_id: str = Depends(get_current_user),
):
    if len(body.conversation_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 conversations per request")

    convs = supabase.table("conversations").select("id").eq("user_id", user_id).in_("id", body.conversation_ids).execute()
    valid_ids = {c["id"] for c in convs.data}

    deleted = 0
    for conv_id in body.conversation_ids:
        if conv_id not in valid_ids:
            continue
        try:
            await _delete_conversation_storage(conv_id)
            supabase.table("conversations").delete().eq("id", conv_id).execute()
            deleted += 1
        except Exception as e:
            logger.error("Failed to delete conversation %s: %s", conv_id[:8], e)

    return {"deleted_count": deleted}
```

- [ ] **Step 5: Commit**

```bash
git add backend/main.py
git commit -m "add conversation delete and bulk delete endpoints"
```

---

### Task 5: File Delete, Document Delete, and Delete All Data Endpoints

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Add DELETE endpoint for uploaded files**

```python
@app.delete("/conversation-files/{file_id}")
async def delete_conversation_file(
    file_id: str,
    user_id: str = Depends(get_current_user),
):
    file = supabase.table("conversation_files").select("id, storage_path").eq("id", file_id).eq("user_id", user_id).maybe_single().execute()
    if not file.data:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        supabase.storage.from_("uploads").remove([file.data["storage_path"]])
    except Exception as e:
        logger.warning("Failed to delete upload from storage: %s", e)

    supabase.table("conversation_files").delete().eq("id", file_id).execute()
    return {"status": "deleted"}
```

- [ ] **Step 2: Add DELETE endpoint for generated documents**

```python
@app.delete("/generated-documents/{document_id}")
async def delete_generated_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
):
    doc = supabase.table("generated_documents").select("id, file_url").eq("id", document_id).eq("user_id", user_id).maybe_single().execute()
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        supabase.storage.from_("documents").remove([doc.data["file_url"]])
    except Exception as e:
        logger.warning("Failed to delete document from storage: %s", e)

    supabase.table("generated_documents").delete().eq("id", document_id).execute()
    return {"status": "deleted"}
```

- [ ] **Step 3: Add DELETE endpoint for all user data**

```python
@app.delete("/profile/all-data")
async def delete_all_data(user_id: str = Depends(get_current_user)):
    # Clean up storage: uploaded files
    files = supabase.table("conversation_files").select("storage_path").eq("user_id", user_id).execute()
    for f in files.data:
        try:
            supabase.storage.from_("uploads").remove([f["storage_path"]])
        except Exception as e:
            logger.warning("Failed to delete upload %s: %s", f["storage_path"], e)

    # Clean up storage: generated documents
    docs = supabase.table("generated_documents").select("file_url").eq("user_id", user_id).execute()
    for d in docs.data:
        try:
            supabase.storage.from_("documents").remove([d["file_url"]])
        except Exception as e:
            logger.warning("Failed to delete document %s: %s", d["file_url"], e)

    # Delete all conversations (cascades to messages, jobs, generated_documents, conversation_files)
    supabase.table("conversations").delete().eq("user_id", user_id).execute()

    # Delete user context
    supabase.table("user_context").delete().eq("user_id", user_id).execute()

    return {"status": "deleted"}
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "add file delete, document delete, and delete-all-data endpoints"
```

---

### Task 6: Backend Test Coverage

**Files:**
- Modify: `backend/test_api.py`

- [ ] **Step 1: Add profile and delete tests to `test_api.py`**

Add the following test functions to the existing test suite. They follow the same synchronous pattern as existing tests (using `httpx`, `TestResult`, `headers()`, and `BASE_URL`). Add them before the `ALL_TESTS` list, and add them to both `ALL_TESTS` and update the test map.

```python
def test_get_profile(token: str, verbose: bool) -> TestResult:
    r = TestResult("GET /profile")
    resp = httpx.get(f"{BASE_URL}/profile", headers=headers(token))
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    body = resp.json()
    for key in ("profile", "user_context", "uploaded_files", "generated_documents"):
        if key not in body:
            return r.fail(f"Missing '{key}' in response")
    if not body["profile"].get("email"):
        return r.fail("Missing email in profile")
    r.info(f"Context: {len(body['user_context'])}, Files: {len(body['uploaded_files'])}, Docs: {len(body['generated_documents'])}")
    return r.ok()


def test_update_profile(token: str, verbose: bool) -> TestResult:
    r = TestResult("PATCH /profile")
    resp = httpx.patch(f"{BASE_URL}/profile", headers=headers(token),
                       json={"full_name": "Test User"})
    if resp.status_code != 200:
        return r.fail(f"Status {resp.status_code}: {resp.text}")
    if resp.json().get("full_name") != "Test User":
        return r.fail(f"Unexpected response: {resp.json()}")
    r.info("Updated name to 'Test User'")
    return r.ok()


def test_delete_conversation(token: str, verbose: bool) -> TestResult:
    r = TestResult("DELETE /conversations/:id")
    # Create a conversation
    create = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                        json={"mode": "job_to_resume"})
    conv_id = create.json()["id"]
    r.info(f"Created: {conv_id[:8]}...")

    # Delete it
    del_resp = httpx.delete(f"{BASE_URL}/conversations/{conv_id}", headers=headers(token))
    if del_resp.status_code != 200:
        return r.fail(f"Delete status {del_resp.status_code}: {del_resp.text}")
    if del_resp.json().get("status") != "deleted":
        return r.fail(f"Unexpected response: {del_resp.json()}")

    # Verify it's gone
    get_resp = httpx.get(f"{BASE_URL}/conversations/{conv_id}", headers=headers(token))
    if get_resp.status_code != 404:
        return r.fail(f"Expected 404 after delete, got {get_resp.status_code}")
    r.info("Verified conversation deleted")
    return r.ok()


def test_bulk_delete(token: str, verbose: bool) -> TestResult:
    r = TestResult("POST /conversations/bulk-delete")
    # Create 2 conversations
    ids = []
    for _ in range(2):
        resp = httpx.post(f"{BASE_URL}/conversations", headers=headers(token),
                          json={"mode": "job_to_resume"})
        ids.append(resp.json()["id"])
    r.info(f"Created {len(ids)} conversations")

    # Bulk delete
    del_resp = httpx.post(f"{BASE_URL}/conversations/bulk-delete", headers=headers(token),
                          json={"conversation_ids": ids})
    if del_resp.status_code != 200:
        return r.fail(f"Status {del_resp.status_code}: {del_resp.text}")
    count = del_resp.json().get("deleted_count", 0)
    if count != 2:
        return r.fail(f"Expected deleted_count=2, got {count}")
    r.info(f"Deleted {count} conversations")
    return r.ok()
```

Add these 4 functions to `ALL_TESTS` (append after existing entries).

- [ ] **Step 2: Run the tests**

Run: `cd backend && python test_api.py --test profile` (matches test_get_profile and test_update_profile)
Then: `cd backend && python test_api.py --test delete` (matches test_delete_conversation and test_bulk_delete)
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/test_api.py
git commit -m "add backend tests for profile and delete endpoints"
```

---

## Chunk 2: Frontend — Shared Components

### Task 7: ConfirmDialog Component

**Files:**
- Create: `frontend/src/components/ConfirmDialog.tsx`

- [ ] **Step 1: Create the ConfirmDialog component**

```tsx
"use client";

import { useEffect, useRef } from "react";

interface ConfirmDialogProps {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: "danger" | "default";
  loading?: boolean;
}

export default function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  message,
  confirmLabel = "Delete",
  variant = "danger",
  loading = false,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) cancelRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onCancel} />
      <div className="relative bg-bg-secondary border border-border rounded-xl p-6 w-full max-w-sm mx-4 shadow-lg">
        <h3 className="text-sm font-semibold text-text-primary mb-2">{title}</h3>
        <p className="text-xs text-text-secondary mb-5 leading-relaxed">{message}</p>
        <div className="flex justify-end gap-2">
          <button
            ref={cancelRef}
            onClick={onCancel}
            disabled={loading}
            className="px-3.5 py-1.5 text-xs rounded-lg bg-bg-tertiary text-text-secondary hover:text-text-primary transition"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`px-3.5 py-1.5 text-xs rounded-lg text-white transition ${
              variant === "danger"
                ? "bg-danger hover:bg-red-600"
                : "bg-accent hover:bg-accent-hover"
            } ${loading ? "opacity-50 cursor-not-allowed" : ""}`}
          >
            {loading ? "Deleting..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -5`
Expected: Build succeeds (new component is unused but valid)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ConfirmDialog.tsx
git commit -m "add reusable confirm dialog component"
```

---

### Task 8: Sidebar — Add Profile Link

**Files:**
- Modify: `frontend/src/components/Sidebar.tsx:137-148`

- [ ] **Step 1: Add Profile link to user menu**

Replace the menu dropdown content (lines 140-147 of `Sidebar.tsx`):

```tsx
{menuOpen && (
  <>
    <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} />
    <div className="absolute bottom-full right-0 mb-1 w-36 bg-bg-secondary border border-border rounded-lg shadow-lg z-50 py-1">
      <button
        onClick={() => { setMenuOpen(false); router.push("/profile"); }}
        className="w-full text-left px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-tertiary hover:text-text-primary transition flex items-center gap-2"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
          <circle cx="12" cy="7" r="4" />
        </svg>
        Profile
      </button>
      <button
        onClick={() => { setMenuOpen(false); handleSignOut(); }}
        className="w-full text-left px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-tertiary hover:text-text-primary transition flex items-center gap-2"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <polyline points="16 17 21 12 16 7" />
          <line x1="21" y1="12" x2="9" y2="12" />
        </svg>
        Sign out
      </button>
    </div>
  </>
)}
```

- [ ] **Step 2: Update TopBar in layout.tsx to handle /profile path**

In `frontend/src/app/(app)/layout.tsx`, update the TopBar title logic (around line 17):

```tsx
if (pathname === "/history") {
  title = "All Conversations";
} else if (pathname === "/profile") {
  title = "Profile";
} else if (activeConversation) {
  title = activeConversation.title;
  status = activeConversation.status;
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Sidebar.tsx frontend/src/app/\(app\)/layout.tsx
git commit -m "add profile link to sidebar menu and topbar"
```

---

## Chunk 3: Frontend — Profile Page

### Task 9: Profile Page — Account + AI Context Sections

**Files:**
- Create: `frontend/src/app/(app)/profile/page.tsx`

- [ ] **Step 1: Create the profile page with account and context sections**

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiJson, apiFetch } from "@/lib/api";
import { useApp } from "@/components/AppContext";
import ConfirmDialog from "@/components/ConfirmDialog";

interface Profile {
  id: string;
  full_name: string | null;
  email: string;
}

interface UserContext {
  id: string;
  category: string;
  content: Record<string, unknown>;
  updated_at: string;
}

interface UploadedFile {
  id: string;
  filename: string;
  mime_type: string;
  file_size: number;
  download_url: string;
  created_at: string;
  conversation_id: string;
}

interface GeneratedDocument {
  id: string;
  doc_type: string;
  file_url: string;
  download_url: string;
  created_at: string;
  job_id: string;
}

interface ProfileData {
  profile: Profile;
  user_context: UserContext[];
  uploaded_files: UploadedFile[];
  generated_documents: GeneratedDocument[];
}

const CATEGORY_LABELS: Record<string, string> = {
  work_experience: "Work Experience",
  skills: "Skills",
  education: "Education",
  certifications: "Certifications",
  personal_info: "Personal Info",
  preferences: "Preferences",
};

function formatContextContent(category: string, content: Record<string, unknown>): string {
  if (category === "skills" && Array.isArray(content.skills)) {
    return (content.skills as string[]).join(", ");
  }
  // Generic: render key-value pairs as readable text
  const lines: string[] = [];
  for (const [key, value] of Object.entries(content)) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (typeof item === "object" && item !== null) {
          lines.push(Object.values(item as Record<string, unknown>).filter(Boolean).join(" — "));
        } else {
          lines.push(String(item));
        }
      }
    } else if (typeof value === "object" && value !== null) {
      lines.push(`${key}: ${JSON.stringify(value)}`);
    } else {
      lines.push(`${key}: ${value}`);
    }
  }
  return lines.join("\n");
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProfilePage() {
  const [data, setData] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [nameValue, setNameValue] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [editingContext, setEditingContext] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    loading: boolean;
  }>({ open: false, title: "", message: "", onConfirm: () => {}, loading: false });
  const router = useRouter();
  const { refreshConversations } = useApp();

  const fetchProfile = useCallback(async () => {
    try {
      const result = await apiJson<ProfileData>("/profile");
      setData(result);
      setNameValue(result.profile.full_name || "");
    } catch (err) {
      console.error("Failed to load profile:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  const handleSaveName = async () => {
    if (!nameValue.trim() || savingName) return;
    setSavingName(true);
    try {
      await apiJson("/profile", {
        method: "PATCH",
        body: JSON.stringify({ full_name: nameValue.trim() }),
      });
    } catch (err) {
      console.error("Failed to update name:", err);
    } finally {
      setSavingName(false);
    }
  };

  const handleDeleteContext = (ctx: UserContext) => {
    setConfirmState({
      open: true,
      title: `Delete ${CATEGORY_LABELS[ctx.category] || ctx.category}?`,
      message: "This AI-learned data will be permanently removed. The AI won't remember this information in future conversations.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/user-context/${ctx.id}`, { method: "DELETE" });
          setData((prev) =>
            prev ? { ...prev, user_context: prev.user_context.filter((c) => c.id !== ctx.id) } : prev
          );
        } catch (err) {
          console.error("Failed to delete context:", err);
        }
        setConfirmState((s) => ({ ...s, open: false, loading: false }));
      },
    });
  };

  const handleSaveContext = async (ctx: UserContext) => {
    try {
      const updated = await apiJson<UserContext>(`/user-context/${ctx.id}`, {
        method: "PUT",
        body: JSON.stringify({ content: { text: editValue } }),
      });
      setData((prev) =>
        prev
          ? { ...prev, user_context: prev.user_context.map((c) => (c.id === ctx.id ? { ...c, content: updated.content, updated_at: updated.updated_at } : c)) }
          : prev
      );
      setEditingContext(null);
    } catch (err) {
      console.error("Failed to update context:", err);
    }
  };

  const handleDeleteFile = (file: UploadedFile) => {
    setConfirmState({
      open: true,
      title: `Delete ${file.filename}?`,
      message: "This uploaded file will be permanently removed from cloud storage.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/conversation-files/${file.id}`, { method: "DELETE" });
          setData((prev) =>
            prev ? { ...prev, uploaded_files: prev.uploaded_files.filter((f) => f.id !== file.id) } : prev
          );
        } catch (err) {
          console.error("Failed to delete file:", err);
        }
        setConfirmState((s) => ({ ...s, open: false, loading: false }));
      },
    });
  };

  const handleDeleteDoc = (doc: GeneratedDocument) => {
    setConfirmState({
      open: true,
      title: `Delete this ${doc.doc_type === "resume" ? "resume" : "cover letter"}?`,
      message: "This generated document will be permanently removed from cloud storage.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/generated-documents/${doc.id}`, { method: "DELETE" });
          setData((prev) =>
            prev ? { ...prev, generated_documents: prev.generated_documents.filter((d) => d.id !== doc.id) } : prev
          );
        } catch (err) {
          console.error("Failed to delete document:", err);
        }
        setConfirmState((s) => ({ ...s, open: false, loading: false }));
      },
    });
  };

  const handleDeleteAll = () => {
    setConfirmState({
      open: true,
      title: "Delete all data?",
      message: "This will permanently delete all your conversations, messages, uploaded files, generated documents, and AI-learned data. This cannot be undone.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch("/profile/all-data", { method: "DELETE" });
          await refreshConversations();
          router.push("/chat");
        } catch (err) {
          console.error("Failed to delete all data:", err);
          setConfirmState((s) => ({ ...s, open: false, loading: false }));
        }
      },
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-sm text-text-tertiary">Failed to load profile.</p>
      </div>
    );
  }

  const avatar = (data.profile.full_name || data.profile.email || "U")[0].toUpperCase();

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-2xl mx-auto space-y-0">
        {/* Account Section */}
        <section className="pb-6 border-b border-border">
          <div className="flex items-center gap-4 mb-4">
            <div className="w-12 h-12 rounded-xl bg-accent flex items-center justify-center text-xl font-semibold text-white flex-shrink-0">
              {avatar}
            </div>
            <div>
              <p className="text-sm font-semibold text-text-primary">
                {data.profile.full_name || "No name set"}
              </p>
              <p className="text-xs text-text-tertiary">{data.profile.email}</p>
            </div>
          </div>
          <div className="flex gap-2">
            <input
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              placeholder="Your name"
              className="flex-1 bg-bg-secondary border border-border rounded-lg px-3 py-1.5 text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-accent/50 transition"
            />
            <button
              onClick={handleSaveName}
              disabled={savingName || !nameValue.trim()}
              className="px-4 py-1.5 text-xs font-medium bg-accent text-white rounded-lg hover:bg-accent-hover transition disabled:opacity-50"
            >
              {savingName ? "Saving..." : "Save"}
            </button>
          </div>
        </section>

        {/* AI-Learned Context Section */}
        <section className="py-6 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary mb-1">AI-Learned Context</h3>
          <p className="text-xs text-text-tertiary mb-4">Data the AI has saved about you from conversations</p>

          {data.user_context.length === 0 ? (
            <div className="bg-bg-secondary border border-border rounded-lg p-4 text-center">
              <p className="text-xs text-text-tertiary">
                No AI-learned data yet. Start a conversation and the AI will remember your background.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {data.user_context.map((ctx) => (
                <div key={ctx.id} className="bg-bg-secondary border border-border rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-accent">
                      {CATEGORY_LABELS[ctx.category] || ctx.category}
                    </span>
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => {
                          if (editingContext === ctx.id) {
                            setEditingContext(null);
                          } else {
                            setEditingContext(ctx.id);
                            setEditValue(formatContextContent(ctx.category, ctx.content));
                          }
                        }}
                        className="px-2 py-0.5 text-[10px] rounded border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition"
                      >
                        {editingContext === ctx.id ? "Cancel" : "Edit"}
                      </button>
                      <button
                        onClick={() => handleDeleteContext(ctx)}
                        className="px-2 py-0.5 text-[10px] rounded border border-border text-danger hover:bg-danger/10 transition"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                  {editingContext === ctx.id ? (
                    <div className="space-y-2">
                      <textarea
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        rows={4}
                        className="w-full bg-bg-primary border border-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-tertiary resize-none outline-none focus:border-accent/50 transition"
                      />
                      <button
                        onClick={() => handleSaveContext(ctx)}
                        className="px-3 py-1 text-xs bg-accent text-white rounded-lg hover:bg-accent-hover transition"
                      >
                        Save
                      </button>
                    </div>
                  ) : (
                    <p className="text-xs text-text-secondary whitespace-pre-line leading-relaxed">
                      {formatContextContent(ctx.category, ctx.content)}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Uploaded Files Section */}
        <section className="py-6 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary mb-1">Uploaded Files</h3>
          <p className="text-xs text-text-tertiary mb-4">Resumes and documents you&apos;ve uploaded</p>

          {data.uploaded_files.length === 0 ? (
            <div className="bg-bg-secondary border border-border rounded-lg p-4 text-center">
              <p className="text-xs text-text-tertiary">No uploaded files.</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {data.uploaded_files.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center justify-between bg-bg-secondary border border-border rounded-lg px-4 py-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent flex-shrink-0">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                    </svg>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-text-primary truncate">{file.filename}</p>
                      <p className="text-[10px] text-text-tertiary">
                        {formatFileSize(file.file_size)} &middot; {new Date(file.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-1.5 flex-shrink-0 ml-3">
                    {file.download_url && (
                      <a
                        href={file.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2 py-0.5 text-[10px] rounded border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition"
                      >
                        Download
                      </a>
                    )}
                    <button
                      onClick={() => handleDeleteFile(file)}
                      className="px-2 py-0.5 text-[10px] rounded border border-border text-danger hover:bg-danger/10 transition"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Generated Documents Section */}
        <section className="py-6 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary mb-1">Generated Documents</h3>
          <p className="text-xs text-text-tertiary mb-4">Resumes and cover letters the AI created for you</p>

          {data.generated_documents.length === 0 ? (
            <div className="bg-bg-secondary border border-border rounded-lg p-4 text-center">
              <p className="text-xs text-text-tertiary">No generated documents yet.</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {data.generated_documents.map((doc) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between bg-bg-secondary border border-border rounded-lg px-4 py-3"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-success flex-shrink-0">
                      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                      <polyline points="14 2 14 8 20 8" />
                      <line x1="16" y1="13" x2="8" y2="13" />
                      <line x1="16" y1="17" x2="8" y2="17" />
                    </svg>
                    <div className="min-w-0">
                      <p className="text-xs font-medium text-text-primary truncate">
                        {doc.doc_type === "resume" ? "Resume" : "Cover Letter"}
                      </p>
                      <p className="text-[10px] text-text-tertiary">
                        Generated {new Date(doc.created_at).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-1.5 flex-shrink-0 ml-3">
                    {doc.download_url && (
                      <a
                        href={doc.download_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-2 py-0.5 text-[10px] rounded border border-border text-text-secondary hover:text-text-primary hover:bg-bg-tertiary transition"
                      >
                        Download
                      </a>
                    )}
                    <button
                      onClick={() => handleDeleteDoc(doc)}
                      className="px-2 py-0.5 text-[10px] rounded border border-border text-danger hover:bg-danger/10 transition"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Danger Zone */}
        <section className="py-6">
          <h3 className="text-sm font-semibold text-danger mb-1">Danger Zone</h3>
          <p className="text-xs text-text-tertiary mb-4">Irreversible actions</p>
          <button
            onClick={handleDeleteAll}
            className="px-4 py-1.5 text-xs font-medium border border-danger text-danger rounded-lg hover:bg-danger/10 transition"
          >
            Delete All Data
          </button>
        </section>
      </div>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
        loading={confirmState.loading}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify frontend build**

Run: `cd frontend && npx next build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/profile/page.tsx
git commit -m "add profile page with account, context, files, documents, and danger zone"
```

---

## Chunk 4: Frontend — History Page Enhancements

### Task 10: History Page — Select Mode + Bulk Delete + Individual Delete

**Files:**
- Modify: `frontend/src/app/(app)/history/page.tsx`

- [ ] **Step 1: Rewrite history page with selection mode and delete functionality**

Replace the full content of `frontend/src/app/(app)/history/page.tsx`:

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApp } from "@/components/AppContext";
import { apiJson, apiFetch } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";

type ModeFilter = "all" | "job_to_resume" | "find_jobs";
type StatusFilter = "all" | "active" | "completed";

export default function HistoryPage() {
  const { conversations, loading, refreshConversations } = useApp();
  const [modeFilter, setModeFilter] = useState<ModeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmState, setConfirmState] = useState<{
    open: boolean;
    title: string;
    message: string;
    onConfirm: () => void;
    loading: boolean;
  }>({ open: false, title: "", message: "", onConfirm: () => {}, loading: false });
  const router = useRouter();

  const filtered = conversations.filter((c) => {
    const matchesMode = modeFilter === "all" || c.mode === modeFilter;
    const matchesStatus = statusFilter === "all" || c.status === statusFilter;
    return matchesMode && matchesStatus;
  });

  const handleNew = async () => {
    const conv = await apiJson<{ id: string }>("/conversations", {
      method: "POST",
      body: JSON.stringify({ mode: "job_to_resume" }),
    });
    await refreshConversations();
    router.push(`/chat/${conv.id}`);
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selected.size === filtered.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filtered.map((c) => c.id)));
    }
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelected(new Set());
  };

  const handleBulkDelete = () => {
    const count = selected.size;
    setConfirmState({
      open: true,
      title: `Delete ${count} conversation${count > 1 ? "s" : ""}?`,
      message: "This also deletes their messages, uploaded files, and generated documents. This cannot be undone.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiJson("/conversations/bulk-delete", {
            method: "POST",
            body: JSON.stringify({ conversation_ids: [...selected] }),
          });
          await refreshConversations();
          exitSelectMode();
        } catch (err) {
          console.error("Bulk delete failed:", err);
        }
        setConfirmState((s) => ({ ...s, open: false, loading: false }));
      },
    });
  };

  const handleDeleteSingle = (id: string, title: string) => {
    setConfirmState({
      open: true,
      title: `Delete "${title}"?`,
      message: "This also deletes messages, uploaded files, and generated documents for this conversation.",
      loading: false,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, loading: true }));
        try {
          await apiFetch(`/conversations/${id}`, { method: "DELETE" });
          await refreshConversations();
        } catch (err) {
          console.error("Delete failed:", err);
        }
        setConfirmState((s) => ({ ...s, open: false, loading: false }));
      },
    });
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6">
      <div className="max-w-3xl mx-auto">
        {/* Header with filters + select toggle */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex gap-1.5 flex-wrap">
            {(["all", "job_to_resume", "find_jobs"] as ModeFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setModeFilter(f)}
                className={`px-3 py-1 rounded-full text-xs transition ${
                  modeFilter === f
                    ? "bg-accent-muted text-accent border border-accent/20"
                    : "bg-bg-secondary text-text-secondary border border-border hover:text-text-primary"
                }`}
              >
                {f === "all" ? "All modes" : f === "job_to_resume" ? "Job \u2192 Resume" : "Find Jobs"}
              </button>
            ))}
            <div className="w-px h-5 bg-border self-center mx-1" />
            {(["all", "active", "completed"] as StatusFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => setStatusFilter(f)}
                className={`px-3 py-1 rounded-full text-xs transition ${
                  statusFilter === f
                    ? "bg-accent-muted text-accent border border-accent/20"
                    : "bg-bg-secondary text-text-secondary border border-border hover:text-text-primary"
                }`}
              >
                {f === "all" ? "All status" : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
          {!selectMode && filtered.length > 0 && (
            <button
              onClick={() => setSelectMode(true)}
              className="px-3 py-1 rounded-lg text-xs bg-bg-secondary border border-border text-text-secondary hover:text-text-primary transition"
            >
              Select
            </button>
          )}
        </div>

        {/* Selection action bar */}
        {selectMode && (
          <div className="flex items-center justify-between bg-accent-muted border border-accent/20 rounded-lg px-4 py-2 mb-4">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                checked={selected.size === filtered.length && filtered.length > 0}
                onChange={toggleSelectAll}
                className="accent-accent"
              />
              <span className="text-xs text-text-secondary">
                {selected.size} selected
              </span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleBulkDelete}
                disabled={selected.size === 0}
                className="px-3 py-1 text-xs rounded-lg border border-danger text-danger hover:bg-danger/10 transition disabled:opacity-50"
              >
                Delete Selected
              </button>
              <button
                onClick={exitSelectMode}
                className="px-3 py-1 text-xs rounded-lg bg-bg-secondary border border-border text-text-secondary hover:text-text-primary transition"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* List */}
        {loading && (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-lg bg-bg-secondary animate-pulse" />
            ))}
          </div>
        )}

        {!loading && filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-12 h-12 rounded-xl bg-bg-secondary border border-border flex items-center justify-center mb-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-accent">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h3 className="text-sm font-medium text-text-primary mb-1">No conversations yet</h3>
            <p className="text-xs text-text-tertiary mb-4">Start a new chat to generate your first tailored resume.</p>
            <button
              onClick={handleNew}
              className="px-4 py-1.5 text-xs font-medium bg-accent text-white rounded-md hover:bg-accent-hover transition"
            >
              New Chat
            </button>
          </div>
        )}

        {!loading && filtered.length > 0 && (
          <div className="space-y-1">
            {filtered.map((c) => (
              <div
                key={c.id}
                className="flex items-center gap-3 px-4 py-3 bg-bg-secondary border border-border rounded-lg hover:border-accent/30 transition group"
              >
                {selectMode && (
                  <input
                    type="checkbox"
                    checked={selected.has(c.id)}
                    onChange={() => toggleSelect(c.id)}
                    className="accent-accent flex-shrink-0"
                  />
                )}
                <button
                  onClick={() => !selectMode && router.push(`/chat/${c.id}`)}
                  className="flex-1 text-left min-w-0"
                >
                  <p className="text-sm font-medium text-text-primary truncate group-hover:text-accent transition">
                    {c.title}
                  </p>
                  <p className="text-[11px] text-text-tertiary mt-0.5">
                    {c.mode === "job_to_resume" ? "Job \u2192 Resume" : "Find Jobs"} &middot;{" "}
                    {new Date(c.created_at).toLocaleDateString()}
                  </p>
                </button>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full flex-shrink-0 ${
                    c.status === "active"
                      ? "bg-accent-muted text-accent"
                      : "bg-bg-tertiary text-text-secondary"
                  }`}
                >
                  {c.status === "active" ? "Active" : "Completed"}
                </span>
                {!selectMode && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSingle(c.id, c.title);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-bg-tertiary transition text-text-tertiary hover:text-danger"
                    aria-label="Delete conversation"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmState.open}
        title={confirmState.title}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
        loading={confirmState.loading}
      />
    </div>
  );
}
```

- [ ] **Step 2: Verify frontend build**

Run: `cd frontend && npx next build 2>&1 | tail -10`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/\(app\)/history/page.tsx
git commit -m "add select mode, bulk delete, and individual delete to history page"
```

---

### Task 11: End-to-End Manual Testing

- [ ] **Step 1: Start both backend and frontend**

Run backend: `cd backend && uvicorn main:app --reload --port 8000`
Run frontend: `cd frontend && npm run dev`

- [ ] **Step 2: Test profile page**

1. Navigate to `/profile` via sidebar user menu
2. Verify all sections render (account, context, files, documents, danger zone)
3. Edit name → Save → verify it persists on refresh
4. If context entries exist, edit one → Save → verify update
5. Delete a context entry → confirm dialog → verify removal

- [ ] **Step 3: Test history page delete features**

1. Navigate to `/history`
2. Click "Select" → checkboxes appear
3. Select 1+ conversations → "Delete Selected" → confirm → verify removal
4. Exit select mode → hover over a conversation → click trash icon → confirm → verify removal

- [ ] **Step 4: Test file/document download and delete on profile**

1. If uploaded files exist, click Download → verify file downloads
2. Click Delete on a file → confirm → verify removal
3. Same for generated documents

- [ ] **Step 5: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix issues found during manual testing"
```
