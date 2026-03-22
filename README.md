# AI Resume & Cover Letter Automation

Automatically generate tailored resumes and cover letters for any job posting — paste a URL or just describe the role.

---

## How It Works

1. Paste a job URL **or** search by job title/keywords
2. **Tavily** finds the job posting URL → **Firecrawl** extracts the full description
3. **Gemini 2.5 Flash** tailors your resume and writes a cover letter via conversational chat
4. Download a polished `.docx` file

---

## Tech Stack

### Frontend
- **Next.js** — Chat UI, auth pages, conversation history, document downloads
- **Vercel** — deploys the Next.js app
- **Supabase Auth** — email/password and Google OAuth login

### Backend
- **Python + FastAPI** — API that orchestrates scraping, AI calls, and document generation
- **Google Cloud Run** — serverless container hosting for the FastAPI app
- **Supabase** — Postgres for conversations, messages, jobs, user context, and generated document records
- **Supabase Storage** — stores generated `.docx` files with signed download URLs

### Document Generation
- **docxtpl** (python-docx-template) — fills Jinja2-templated `.docx` files with AI-generated content; design your resume layout in Word once, reuse forever

### Job Research / Scraping
Two-stage pipeline:
1. **Tavily** — when no URL is provided, searches the web and returns ranked job posting URLs
2. **Firecrawl** (v4) — takes the URL and extracts the full job description as clean Markdown; handles JS rendering and anti-blocking

### AI
- **Gemini 2.5 Flash** (Google AI) — generates tailored resume bullet points and cover letter copy via native function calling; ~25x cheaper on output tokens than comparable models
- **Turn router** — a lightweight classifier step decides whether the assistant should respond directly, save profile memory, or enter the full tool-driven flow

### Auth
- **Supabase Auth** with ES256 JWTs — backend verifies tokens via JWKS endpoint (no shared JWT secret needed)
- **PyJWT** with `PyJWKClient` for automatic key caching and rotation
- **Supabase-backed team access gate** — optional shared code layer for short-lived team test environments, with rotation and per-user revocation

---

## Architecture

```
Browser (Next.js on Vercel)
    │
    ├──> Supabase Auth (login, JWT)
    │
    └──SSE──> FastAPI (Cloud Run)
                  │
                  ├──> Gemini 2.5 Flash (chat + function calling)
                  │         └──> turn router (small talk / clarification / tool intent)
                  │         │
                  │    ┌────┼────┐────────────┐
                  │  Tavily  Firecrawl    save_user_context
                  │ (search)  (scrape)    (remember user info)
                  │                │
                  │            docxtpl
                  │        (fill .docx template)
                  │                │
                  ├──> Supabase DB (conversations, messages, jobs, user_context, documents)
                  └──> Supabase Storage (generated .docx files)
```

---

## Project Structure

```
/
├── frontend/                          # Next.js app
│   ├── src/
│   │   ├── app/
│   │   │   ├── login/page.tsx         # Sign in / sign up page
│   │   │   ├── actions/auth.ts        # Server Actions for auth
│   │   │   ├── auth/callback/route.ts # OAuth callback handler
│   │   │   ├── (app)/
│   │   │   │   ├── layout.tsx         # App layout with sidebar
│   │   │   │   ├── chat/[id]/page.tsx # Chat page with SSE streaming
│   │   │   │   ├── chat/page.tsx      # Chat landing (no conversation selected)
│   │   │   │   └── history/page.tsx   # Conversation history list
│   │   │   └── globals.css            # Theme system (CSS variables)
│   │   ├── components/
│   │   │   ├── Sidebar.tsx            # Navigation sidebar
│   │   │   ├── ChatMessage.tsx        # Chat bubble component
│   │   │   ├── StatusPill.tsx         # Tool status indicator
│   │   │   └── DownloadCard.tsx       # Document download card
│   │   ├── lib/
│   │   │   ├── api.ts                 # API client with auth
│   │   │   └── supabase/              # Supabase client/server helpers
│   │   └── middleware.ts              # Auth middleware (session refresh)
│   └── .env.local                     # Frontend env vars
│
├── backend/                           # FastAPI app
│   ├── main.py                        # API routes and CORS
│   ├── auth.py                        # JWT verification via JWKS
│   ├── chat.py                        # Chat orchestration with Gemini function calling
│   ├── tools.py                       # Tool implementations (search, scrape, generate, save_context)
│   ├── config.py                      # Pydantic settings
│   ├── models.py                      # Request/response models
│   ├── db.py                          # Supabase client
│   ├── templates/                     # .docx resume/cover letter templates
│   │   ├── resume.docx
│   │   └── cover_letter.docx
│   ├── tests/
│   │   └── test_auth.py
│   └── .env                           # Backend env vars
│
├── docs/
│   ├── RUNNING.md                     # Setup and running guide
│   ├── DEPLOY_TEAM_TEST.md            # Cloud Run deployment + rotatable team access gate
│   └── IMPROVEMENTS.md                # Known issues and future improvements
└── README.md
```

---

## Key Dependencies

| Layer | Package | Version |
|---|---|---|
| Backend framework | `fastapi`, `uvicorn` | 0.115, 0.34 |
| Document generation | `docxtpl` | 0.19 |
| Job discovery | `tavily-python` | 0.7 |
| Job scraping | `firecrawl-py` | 4.3 |
| AI | `google-genai` | 1.14 |
| Database / Auth | `supabase`, `PyJWT` | 2.28, 2.9+ |
| Frontend | `next`, `react` | 15, 19 |
