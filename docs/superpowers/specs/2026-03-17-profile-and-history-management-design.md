# Profile Page & History Management — Design Spec

## Goal

Add a profile page where users can view and manage all data the AI has saved about them, their uploaded files, and generated documents. Enhance the history page with bulk delete capability.

## Architecture

Single new page (`/profile`) under the existing `(app)` route group, reusing the same layout (sidebar + top bar). Backend gets new CRUD endpoints for user data management. History page gains a selection mode for bulk operations. All deletions cascade properly through related tables and storage buckets.

## Scope

### In Scope
- Profile page with account info, AI-learned context, uploaded files, generated documents, danger zone
- Edit/delete AI-learned context entries
- Download/delete uploaded files and generated documents
- Bulk conversation deletion on history page
- Individual conversation deletion (3-dot menu)
- "Delete All Data" action
- Sidebar navigation addition (Profile link in user menu)

### Out of Scope
- Account deletion (requires Supabase Auth admin API — separate feature)
- Email change (Supabase Auth handles this separately)
- Password change
- Notification preferences
- Export/download all data

---

## Backend API

**Note:** The backend uses the Supabase service-role client (`supabase_service_key`), which bypasses RLS. No new database migrations or RLS policies are needed for delete operations.

### New Endpoints

#### `GET /profile`

Returns aggregated user data for the profile page.

**Response:**
```json
{
  "profile": { "id": "uuid", "full_name": "string", "email": "string" },
  "user_context": [
    { "id": "uuid", "category": "work_experience", "content": {}, "updated_at": "iso8601" }
  ],
  "uploaded_files": [
    { "id": "uuid", "filename": "string", "mime_type": "string", "file_size": 12345, "download_url": "signed_url", "created_at": "iso8601", "conversation_id": "uuid" }
  ],
  "generated_documents": [
    { "id": "uuid", "doc_type": "resume", "filename": "string", "file_url": "string", "download_url": "signed_url", "created_at": "iso8601", "job_id": "uuid" }
  ]
}
```

**Queries:**
- `profiles` table for profile info
- `user_context` table filtered by user_id
- `conversation_files` table filtered by user_id
- `generated_documents` table filtered by user_id, with stored filenames and signed storage URLs for fallback/direct access

#### `PATCH /profile`

Update user profile (name only for now).

**Request:** `{ "full_name": "string" }`
**Response:** `{ "full_name": "string" }`

Updates `profiles` table.

#### `DELETE /user-context/{context_id}`

Delete a single AI-learned context entry.

**Validation:** Verify the context entry belongs to the authenticated user.
**Response:** `{ "status": "deleted" }`

#### `PUT /user-context/{context_id}`

Update a single AI-learned context entry's content.

**Request:** `{ "content": {} }`
**Validation:** Verify ownership.
**Response:** `{ "id": "uuid", "category": "string", "content": {}, "updated_at": "iso8601" }`

#### `DELETE /conversations/{conversation_id}`

Delete a conversation and all related data.

**Cascade strategy:** The database uses `ON DELETE CASCADE` on all foreign keys, so deleting a conversation row automatically removes messages, jobs, generated_documents, and conversation_files from the DB. The backend only needs to manually clean up storage bucket files before deleting the conversation row.

**Steps:**
1. Fetch `conversation_files` for this conversation → collect `storage_path` values → delete from `uploads` bucket
2. Fetch `jobs` → for each job, fetch `generated_documents` → collect `file_url` values → delete from `documents` bucket
3. Delete the conversation row (DB cascade handles all related rows)

**Response:** `{ "status": "deleted" }`

#### `POST /conversations/bulk-delete`

Delete multiple conversations.

**Request:** `{ "conversation_ids": ["uuid", ...] }`
**Validation:** Verify all conversations belong to authenticated user.
**Processing:** Runs the same cascade logic as single delete for each conversation.
**Response:** `{ "deleted_count": 3 }`

#### `DELETE /conversation-files/{file_id}`

Delete a single uploaded file.

**Processing:**
1. Delete from `uploads` storage bucket using `storage_path`
2. Delete DB row from `conversation_files`

**Response:** `{ "status": "deleted" }`

#### `DELETE /generated-documents/{document_id}`

Delete a single generated document.

**Processing:**
1. Delete from `documents` storage bucket using `file_url`
2. Delete DB row from `generated_documents`

**Response:** `{ "status": "deleted" }`

#### `DELETE /profile/all-data`

Delete all user data except the auth account itself.

**Processing:**
1. Fetch all `conversation_files` → delete from `uploads` storage bucket
2. Fetch all `generated_documents` → delete from `documents` storage bucket
3. Delete all `conversations` (DB cascade removes messages, jobs, generated_documents, conversation_files)
4. Delete all `user_context`

**Response:** `{ "status": "deleted" }`

Note: Does not delete `profiles` row or Supabase Auth user — they can still sign in, they just start fresh. The `full_name` on the profiles row is preserved (not reset).

### Request/Response Models (models.py additions)

```python
class UpdateProfileRequest(BaseModel):
    full_name: str

class UpdateUserContextRequest(BaseModel):
    content: dict

class BulkDeleteConversationsRequest(BaseModel):
    conversation_ids: list[str]  # max 100 items, validated in endpoint
```

---

## Frontend

### New Page: `/profile`

**File:** `frontend/src/app/(app)/profile/page.tsx`

Single client component (`"use client"`) with sections:

#### Account Section
- Avatar (first letter of name/email, blue bg — same pattern as sidebar)
- Editable name field with Save button
- Email (read-only, from Supabase auth session)
- Uses `PATCH /profile` on save

#### AI-Learned Context Section
- Fetches from `GET /profile` response's `user_context` array
- Each category rendered as a card with:
  - Category label (uppercase, accent color)
  - Content rendered as readable text (format depends on category — skills as tags, experience as lines, etc.)
  - Edit button → opens inline edit mode (plain textarea showing content as readable text, not raw JSON — the backend parses it back)
  - Delete button → confirmation dialog → `DELETE /user-context/{id}`
- Empty state: "No AI-learned data yet. Start a conversation and the AI will remember your background."

#### Uploaded Files Section
- List from `GET /profile` response's `uploaded_files` array
- Each file: icon, filename, size, date, conversation link
- Download button → calls the authenticated `/documents/{id}/download` endpoint and uses stored `filename`
- Delete button → confirmation → `DELETE /conversation-files/{id}`
- Empty state: "No uploaded files."

#### Generated Documents Section
- List from `GET /profile` response's `generated_documents` array
- Each doc: icon (green), type + job title, date
- Download button → calls the authenticated `/documents/{id}/download` endpoint and uses stored `filename`
- Delete button → confirmation → `DELETE /generated-documents/{id}`
- Empty state: "No generated documents yet."

#### Danger Zone Section
- Red-themed section at bottom
- "Delete All Data" button → confirmation modal ("This will delete all your conversations, files, documents, and AI-learned data. This cannot be undone.") → `DELETE /profile/all-data`
- On success: redirect to `/chat` with refreshed state

### Modified Page: `/history`

**File:** `frontend/src/app/(app)/history/page.tsx`

Additions:
- "Select" toggle button in header → enters selection mode
- Selection mode shows:
  - Checkbox on each conversation row
  - "Select all" checkbox in action bar
  - "N selected" count
  - "Delete Selected" button (red) → confirmation → `POST /conversations/bulk-delete`
  - "Cancel" button → exits selection mode
- 3-dot menu on each conversation gets a "Delete" option → confirmation → `DELETE /conversations/{id}`
- After deletion: refresh conversation list via `refreshConversations()` from AppContext

### Modified Component: `Sidebar.tsx`

- Expand the user menu dropdown (currently just sign out)
- Add "Profile" link above "Sign out" with a gear/user icon
- Profile link navigates to `/profile`

### Confirmation Dialog

Reusable confirmation dialog component for all delete actions:
- `frontend/src/components/ConfirmDialog.tsx`
- Props: `open`, `onConfirm`, `onCancel`, `title`, `message`, `confirmLabel` (default "Delete"), `variant` (default "danger")
- Modal overlay with title, message, Cancel + Confirm buttons
- Confirm button styled red for danger variant
- Follows existing design tokens (bg-secondary, border, text colors)

---

## Styling

All new UI follows the existing design system:
- CSS variables: `--bg-primary`, `--bg-secondary`, `--bg-tertiary`, `--accent`, `--border`, `--text-primary`, `--text-secondary`, `--text-tertiary`, `--danger`
- Tailwind classes using these tokens: `bg-bg-secondary`, `border-border`, `text-text-primary`, etc.
- Same border radius (`rounded-xl`, `rounded-lg`), spacing, and typography patterns
- Dark mode default, light mode via `.light` class (already handled by ThemeProvider)

---

## Data Flow

### Profile Page Load
1. Component mounts → shows loading spinner → `GET /profile` with auth token
2. Backend queries 4 tables, generates signed URLs for files and stores semantic filenames for generated documents
3. Frontend renders sections from response

### Delete AI Context Entry
1. User clicks Delete on a context card → ConfirmDialog opens
2. User confirms → `DELETE /user-context/{id}`
3. On success → remove from local state (optimistic or refetch)

### Bulk Delete Conversations
1. User enters select mode on history page
2. Checks conversations → clicks "Delete Selected"
3. ConfirmDialog: "Delete N conversations? This also deletes their messages, files, and generated documents."
4. Confirm → `POST /conversations/bulk-delete` with IDs
5. On success → `refreshConversations()` + remove from local list

### Delete All Data
1. User clicks "Delete All Data" in danger zone
2. ConfirmDialog with strong warning
3. Confirm → `DELETE /profile/all-data`
4. On success → `refreshConversations()` + redirect to `/chat`

---

## Error Handling

- All delete endpoints return 404 if resource doesn't exist or doesn't belong to user
- Frontend shows toast/inline error on failure, reverts optimistic updates
- Cascade deletions use try/catch per step — if storage delete fails, still proceed with DB cleanup (storage is secondary)
- Bulk delete returns count of successfully deleted (partial success is possible)
- All delete buttons disable after click (loading state) to prevent double-clicks
- Signed URLs in profile response expire after 1 hour — if download fails, user can refresh the page

---

## Testing

### Backend
- Add tests to `test_api.py`: profile fetch, name update, context delete, conversation delete (verify cascade), bulk delete, file delete, document delete, all-data delete
- Verify cascade: after conversation delete, messages/files/docs should be gone

### Frontend
- Playwright tests: navigate to profile, verify sections render, delete a context entry, bulk delete conversations from history
