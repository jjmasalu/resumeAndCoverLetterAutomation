# Find Jobs Mode Redesign — Design Spec

## Overview

Redesign the "Find Jobs" mode to accept resume uploads, present structured job results, and differentiate the two modes (Job → Resume vs Find Jobs) as distinct product experiences within the same app. Update the landing page to surface both modes to new visitors.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| User input method | File upload + text fallback | Fastest path for users with a resume, doesn't block those without |
| Mode differentiation | Entry + results presentation | Distinct entry UX and structured JobCards make Find Jobs feel like a discovery tool, not a chatbot |
| Landing page | Tab switcher | Both modes equally discoverable, one active at a time, no clutter. Default tab is "I have a job posting" |
| Find Jobs entry (in-app) | Upload zone above chat | Prominent drag/drop area signals "this mode is different." Disappears after upload, attachment button persists in chat input |
| Job results display | Inline job cards in chat | Builds on existing card component pattern (DownloadCard), keeps architecture simple, match score + action buttons are structured enough |
| Post-upload behavior | Show extracted summary → confirm → search | Builds trust without the overhead of an editable profile card. Corrections happen naturally in chat |

## Landing Page: Tab Switcher

### Current State
Single hero with URL input, hardcoded to `job_to_resume` mode.

### New Design
Same hero headline and branding. Below the headline, a pill toggle switches between two tabs:

**"I have a job posting" tab (default):**
- URL input + "Generate" button (same as current)
- On submit: checks auth, creates conversation with `mode: "job_to_resume"`, redirects to `/chat/{id}?initial=<message>`

**"Find jobs for me" tab:**
- File upload zone: drag/drop area with "Choose file" button
- Supported formats: PDF, DOCX, PNG, JPG
- Below the upload zone: text link "or describe your experience →" that navigates to `/chat` in find_jobs mode (no file)
- On file submit: checks auth, creates conversation with `mode: "find_jobs"`, uploads file to `/conversations/{id}/upload`, redirects to `/chat/{id}?initial=I've uploaded my resume. Please analyze it and help me find matching jobs.`

**"How it works" section:** Update to reflect both flows or use a combined 3-step flow.

## File Upload Infrastructure

### New Endpoint: `POST /conversations/{id}/upload`

- Accepts: `multipart/form-data` with a single file field
- Validates: file type (PDF, DOCX, PNG, JPG), max size 10MB
- Auth: requires Bearer token (same as other endpoints)
- Flow:
  1. Upload file to Supabase Storage at `{user_id}/{conversation_id}/{filename}`
  2. Upload file to Gemini Files API via `client.files.upload(file=<bytes>)` to get a multimodal-ready reference
  3. Store metadata in `conversation_files` table (storage path, Gemini file URI, mime type)
  4. Return `{ file_id, filename, gemini_file_uri }`

### Frontend `FileUpload` Component

- Drag-and-drop zone with click fallback
- Shows upload progress indicator during upload
- Shows filename + checkmark after successful upload
- Accepts `.pdf`, `.docx`, `.png`, `.jpg`
- Emits file to parent; parent handles the API call
- Used in: `/chat` page (Find Jobs empty state), `/chat/[id]` page (attachment button in Find Jobs mode)

### File Processing in `stream_chat()`

When a conversation has an uploaded file and it's the first message exchange:

```python
# Check for uploaded file
file_record = get_conversation_file(conversation_id)
contents = []
if file_record and not has_prior_messages:
    contents.append(types.Part.from_uri(
        file_uri=file_record.gemini_file_uri,
        mime_type=file_record.mime_type
    ))
contents.append(types.Part.from_text(user_message))
```

The file is included in the Gemini `contents` array alongside the user's text message. Gemini processes both multimodally.

## Mode-Specific Chat Experiences

### `/chat` Page (New Conversation Entry)

Has mode selector pills at top. Selected mode changes the empty state:

**Job → Resume (default):**
- Empty state: chat icon + "Start a conversation" + "Paste a job posting URL or describe the role you're targeting."
- Input bar at bottom with text input (same as current)

**Find Jobs:**
- Empty state: upload zone centered — drag/drop area with upload icon, "Upload your resume" heading, "PDF, DOCX, or image — we'll extract everything" subtext, "Choose file" button
- "Or" divider below upload zone
- "Type your experience in the chat below" text pointing to input bar
- Input bar placeholder changes to: "Describe your experience and what roles you're looking for..."

**On submit (either mode):**
1. Create conversation via `POST /conversations` with selected mode
2. If file was selected (Find Jobs): upload via `POST /conversations/{id}/upload`
3. Redirect to `/chat/{id}?initial=<message>`

### `/chat/[id]` Page (Active Conversation)

**Job → Resume conversations:** No changes. Works exactly as today.

**Find Jobs conversations:** Two additions:

1. **Attachment button (📎)** in the chat input bar — opens file picker for uploading additional files mid-conversation. Only visible when the conversation mode is `find_jobs`.

2. **JobCard component** — rendered inline in chat flow when `job_result` SSE events arrive. Displays:
   - Job title (bold)
   - Company + location
   - Match score badge: green (≥80%), amber (≥60%), red (<60%)
   - Snippet (2 lines, truncated)
   - Two action buttons:
     - "Generate Resume" → sends a chat message asking the AI to generate docs for this specific job
     - "View Details" → sends a chat message asking the AI to scrape and show the full JD

## New SSE Event Type: `job_result`

```
event: job_result
data: {"title": "Senior Frontend Engineer", "company": "Stripe", "location": "Remote", "match_score": 92, "snippet": "Build and scale...", "url": "https://..."}
```

Emitted by the backend when the AI processes search results in Find Jobs mode. The frontend renders these as `JobCard` components inline in the chat. The AI also receives the data for composing its text response.

## Backend AI Changes

### Updated Find Jobs System Prompt

**When file uploaded:**
```
You are a career assistant helping the user find jobs that match their profile.

The user has uploaded their resume. Analyze it thoroughly — extract work experience,
skills, education, certifications, and any other relevant details. Respond with a
concise summary of what you found and ask if anything needs correction.

Use save_user_context to persist each category you extract (work_experience, skills,
education, certifications, personal_info).

Once the user confirms their profile, ask what kind of roles they're looking for
(or suggest based on their profile). Then use search_jobs to find matching positions.

For each promising result, use scrape_job to get the full description, then assess
how well it matches the user's profile (0-100%). Present results as structured job
cards with your match assessment.

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card.
```

**When no file (text fallback):**
```
You are a career assistant helping the user find jobs that match their profile.

Ask focused questions to understand the user's background — experience, skills,
education, what they're looking for. Use save_user_context as you learn things.

Once you have enough context, ask what roles they want and use search_jobs to find
matching positions. For each promising result, use scrape_job to get the full
description, then assess how well it matches the user's profile (0-100%).

IMPORTANT: When you generate a document, do NOT paste the download URL in your
response. The UI will automatically show a download card.
```

### Match Score Calculation

No new tool needed. After the AI gets search results from `search_jobs` and scrapes top results with `scrape_job`, it compares each JD against the user's known profile to assign a match percentage. This happens in the AI's reasoning via prompt engineering. The AI emits `job_result` SSE events with the calculated scores.

### Job Result Emission

The `search_jobs` tool handler in `_execute_tool()` is modified: after getting results, emit a `job_result` SSE event for each result. The AI still gets the results as a function response for its text reply.

## Data Model Changes

### New Table: `conversation_files`

```sql
create table conversation_files (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references conversations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  filename text not null,
  storage_path text not null,
  gemini_file_uri text not null,
  mime_type text not null,
  created_at timestamptz not null default now()
);

-- RLS
alter table conversation_files enable row level security;

create policy "Users can read own files"
  on conversation_files for select
  using (user_id = auth.uid());

create policy "Users can insert own files"
  on conversation_files for insert
  with check (user_id = auth.uid());
```

### Existing Tables — No Changes

- `conversations` — `mode` field already supports `find_jobs`
- `messages` — no changes
- `jobs` — still used when AI scrapes a job from Find Jobs results
- `generated_documents` — still used when user clicks "Generate Resume" on a JobCard
- `user_context` — still used to persist extracted profile data via `save_user_context`

## What's NOT in Scope

- **Editable profile page** (IMPROVEMENTS.md #6) — separate feature. Resume upload bootstraps profile via `save_user_context` through chat.
- **Side panel for results** — decided against in favor of inline JobCards
- **Multiple file uploads in a single drop** — one file at a time for v1
- **File format conversion** — Gemini handles PDF/images natively, DOCX support TBD (may need extraction library as fallback)

## Component Inventory

**New components (3):**
- `FileUpload` — drag/drop + click upload zone
- `JobCard` — inline job result card with match score and action buttons
- Upload API helper in `lib/api.ts`

**Modified frontend files (4):**
- `app/page.tsx` — landing page tab switcher
- `app/(app)/chat/page.tsx` — mode-specific empty states
- `app/(app)/chat/[id]/page.tsx` — attachment button, JobCard rendering, job_result SSE handling
- `components/Sidebar.tsx` — mode badge on recent conversations (optional polish)

**Modified backend files (4):**
- `main.py` — new upload endpoint
- `chat.py` — file-aware streaming, job_result SSE events, updated system prompts
- `tools.py` — search_jobs structured result emission
- `models.py` — new request/response types for upload

**New migration (1):**
- `conversation_files` table + RLS policies
