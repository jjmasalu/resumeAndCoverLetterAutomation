# AI Resume & Cover Letter Automation — Design Spec

## Overview

A conversational AI tool that generates tailored resumes and cover letters. Users describe the role they want, the AI researches the job posting, asks targeted questions to learn about the user, and produces polished `.docx` documents. The system progressively builds a profile of the user so future generations require fewer questions.

## Two Modes

1. **Job → Resume**: User has a specific role in mind. System finds/scrapes the job posting, asks the user targeted questions based on JD requirements, generates tailored documents.
2. **Find Jobs → Resume**: User has built up profile context. System searches for matching jobs based on skills/experience, presents options, generates documents for selected ones.

**Mode differences:** In "job_to_resume" mode, the system prompt focuses on extracting job requirements and asking the user about relevant experience. In "find_jobs" mode, the system prompt focuses on understanding what the user is looking for and using their existing context to search for matching roles. The `mode` field is set when creating a conversation and determines which system prompt is used.

## Architecture

**Approach: Backend-Driven Chat**

All AI orchestration lives in FastAPI. Gemini's native function calling feature (via the `google-genai` SDK) handles tool invocation. Frontend is a thin chat UI that streams responses via SSE.

**SSE connection is browser-direct.** The browser connects to the Cloud Run FastAPI URL directly — NOT proxied through a Next.js API route. This avoids Vercel's serverless function timeout limits.

```
Browser ──SSE──> FastAPI (Cloud Run) ──> Gemini 2.5 Flash
   │                  │                       │
   │                  │              function calling
   │                  │                       │
   │                  │            ┌──────────┼──────────┐
   │                  │         Tavily    Firecrawl    docxtpl
   │                  │        (search)    (scrape)    (render)
   │                  │
   │                  ├──> Supabase DB (context, messages, jobs)
   │                  └──> Supabase Storage (generated .docx files)
   │
   └──> Supabase Auth (login, JWT)
```

### Auth Validation

FastAPI validates JWTs via Supabase's JWKS endpoint using ES256 (ECDSA). `PyJWKClient` fetches and caches signing keys automatically. Every protected endpoint depends on `get_current_user()` which extracts the user ID from the token's `sub` claim. No shared JWT secret is needed.

### CORS

FastAPI CORS middleware allows:
- `http://localhost:3000` (development)
- The Vercel production URL
- Credentials (cookies/auth headers) included

### Error Handling

External service failures are surfaced as chat messages to the user. The AI acknowledges the failure and suggests alternatives:
- **Firecrawl fails** → "I couldn't access that job posting. Can you paste the job description directly?"
- **Tavily returns no results** → "I couldn't find that job listing. Could you try different keywords or paste a URL?"
- **Gemini function call malformed** → retry once, then surface a generic error message
- **SSE connection drops** → frontend auto-reconnects and resumes from last message ID

## Data Model (Supabase Postgres)

### `profiles`
Extends Supabase Auth. Created via trigger on user signup.
- `id` (uuid, PK, FK → auth.users)
- `full_name` (text)
- `email` (text)
- `created_at` (timestamptz)

### `user_context`
Progressive profile — AI's growing knowledge about the user.
- `id` (uuid, PK)
- `user_id` (uuid, FK → profiles)
- `category` (text) — e.g. "work_experience", "skills", "education", "certifications"
- `content` (jsonb)
- `source_conversation_id` (uuid, FK → conversations, nullable)
- `updated_at` (timestamptz)

### `conversations`
Chat sessions.
- `id` (uuid, PK)
- `user_id` (uuid, FK → profiles)
- `mode` (text) — "job_to_resume" or "find_jobs"
- `title` (text)
- `status` (text) — "active", "completed"
- `created_at` (timestamptz)

### `messages`
Individual chat messages.
- `id` (uuid, PK)
- `conversation_id` (uuid, FK → conversations)
- `role` (text) — "user", "assistant", "system"
- `content` (text)
- `metadata` (jsonb) — tool calls, job data, etc.
- `created_at` (timestamptz)

### `jobs`
Scraped job postings. Multiple jobs per conversation in "find_jobs" mode.
- `id` (uuid, PK)
- `conversation_id` (uuid, FK → conversations)
- `user_id` (uuid, FK → profiles)
- `title` (text)
- `company` (text)
- `url` (text)
- `description_md` (text)
- `created_at` (timestamptz)

### `generated_documents`
Resume/cover letter outputs. Multiple per job (resume + cover letter).
- `id` (uuid, PK)
- `job_id` (uuid, FK → jobs)
- `user_id` (uuid, FK → profiles)
- `doc_type` (text) — "resume", "cover_letter"
- `filename` (text) — stored semantic download name, versioned per user when needed
- `file_url` (text) — Supabase Storage path (bucket: `documents`, per-user prefix)
- `created_at` (timestamptz)

### Supabase Storage
- Bucket: `documents`
- Path: `{user_id}/{document_id}.docx`
- Access: private, downloaded through the authenticated backend endpoint; signed URLs are still available internally for storage access and fallback flows

## Backend (FastAPI on Cloud Run)

### Endpoints
- `POST /conversations` — start a new conversation (body: `{ mode }`)
- `POST /conversations/{id}/messages` — send message, get streamed SSE response
- `GET /conversations` — list user's conversations
- `GET /conversations/{id}` — get conversation with messages
- `GET /documents/{id}/download` — streams the authenticated `.docx` download with a submission-ready filename

### Gemini Function Declarations

Four tools declared via Gemini's native function calling:

**`search_jobs(query: str, location: str | None)`**
→ Calls Tavily. Returns `[{ title, company, url, snippet }]`.

**`scrape_job(url: str)`**
→ Calls Firecrawl. Returns `{ title, company, description_md }`.

**`generate_document(doc_type: "resume" | "cover_letter", sections: dict)`**
→ Calls docxtpl. `sections` is a dict matching template variables:
- Resume: `{ name, title, summary, experiences: [{ company, role, dates, bullets }], skills, education }`
- Cover letter: `{ name, date, company, hiring_manager, role, paragraphs: [str] }`
→ Returns `{ document_id, filename, download_url }`.

**`save_user_context(category: str, content: dict)`**
→ Upserts to `user_context` table. Gemini invokes this when it learns something worth remembering (e.g., user mentions 5 years of Python experience). This keeps context extraction on-demand rather than running after every message, avoiding doubled API costs.

### SSE Event Types

```
event: message      # AI text chunk (streamed)
data: {"content": "..."}

event: status       # Tool execution status
data: {"tool": "search_jobs", "state": "running"|"done"}

event: document     # Document ready for download
data: {"document_id": "...", "doc_type": "resume", "filename": "...", "download_url": "..."}

event: error        # Error message
data: {"message": "..."}
```

### Streaming Chat Flow (Core Loop)
1. User sends message → FastAPI receives it, saves to `messages`
2. Load user's `user_context` + conversation history from Supabase
3. Build system prompt (varies by `mode`) + context + history
4. Send to Gemini 2.5 Flash with the four function declarations
5. Stream response: text chunks → SSE `message` events; function calls → execute server-side, emit `status` events, feed results back to Gemini
6. Save assistant message to `messages` when complete

### File Structure
```
backend/
├── main.py              # FastAPI app, routes, CORS, auth dependency
├── chat.py              # Gemini conversation orchestration + SSE
├── tools.py             # Tool implementations (Tavily, Firecrawl, docxtpl, context)
├── models.py            # Pydantic models
├── db.py                # Supabase client wrapper
├── config.py            # Environment variables via pydantic-settings
├── requirements.txt
├── Dockerfile
└── templates/
    ├── resume.docx
    └── cover_letter.docx
```

## Frontend (Next.js on Vercel)

### Pages
- `/` — landing page with sign-in
- `/chat` — new conversation (redirects to `/chat/[id]` after creation)
- `/chat/[id]` — conversation view
- `/history` — past conversations + generated documents

### Components
- Sidebar — conversation list, "New Chat", mode toggle
- Chat area — message bubbles, streaming text
- Status pill — shows tool execution status (driven by SSE `status` events)
- Download card — appears inline when SSE `document` event arrives

### Auth
- Supabase Auth UI: Google + email/password
- `@supabase/ssr` for Next.js integration
- JWT stored in cookie, sent as `Authorization: Bearer <token>` to FastAPI

### Styling
- Tailwind CSS

## Environment Variables

### Backend (.env)
| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (for server-side DB access) |
| `SUPABASE_JWT_SECRET` | JWT secret for token validation |
| `GEMINI_API_KEY` | Google AI API key |
| `TAVILY_API_KEY` | Tavily API key |
| `FIRECRAWL_API_KEY` | Firecrawl API key |
| `FRONTEND_URL` | Vercel URL for CORS (default: http://localhost:3000) |

### Frontend (.env.local)
| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anon/public key |
| `NEXT_PUBLIC_API_URL` | FastAPI backend URL |

## Infrastructure

| Component | Platform | Notes |
|-----------|----------|-------|
| Frontend | Vercel | Auto-deploy from GitHub |
| Backend | Google Cloud Run | Containerized FastAPI |
| Database | Supabase (us-east-1) | Project: hwzptzrjqcniukwrjnrb |
| File Storage | Supabase Storage | Bucket: `documents`, private objects downloaded through backend auth |
| GCP Project | resumeandcoverletterautomation | Project #226128760445 |
