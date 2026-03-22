# Running & Testing Guide

## Prerequisites

- Python 3.11+ (`python3.11 --version`)
- Node.js 18+ (`node --version`)
- Docker (optional, for containerized backend)
- All API keys configured (see Environment Setup below)

## Environment Setup

### Backend (`backend/.env`)

Copy the example and fill in real values:

```bash
cp backend/.env.example backend/.env
```

| Variable | Where to get it |
|----------|----------------|
| `SUPABASE_URL` | Supabase Dashboard → Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | Supabase Dashboard → Settings → API → service_role key |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| `TAVILY_API_KEY` | https://app.tavily.com |
| `FIRECRAWL_API_KEY` | https://www.firecrawl.dev |
| `FRONTEND_URL` | `http://localhost:3000` (local) or your Vercel URL |

### Frontend (`frontend/.env.local`)

Copy the example and fill in real values:

```bash
cp frontend/.env.example frontend/.env.local
```

| Variable | Where to get it |
|----------|----------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Same as `SUPABASE_URL` above |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase Dashboard → Settings → API → Publishable key (`sb_publishable_...`) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` (local) or your Cloud Run URL |

---

## Running Locally (Without Docker)

### 1. Backend

```bash
cd backend

# First time only: create venv and install deps
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Run the server
.venv/bin/uvicorn main:app --reload --port 8000
```

Backend runs at **http://localhost:8000**. Check health: `curl http://localhost:8000/health`

API docs available at **http://localhost:8000/docs** (Swagger UI).

### 2. Frontend

```bash
cd frontend

# First time only: install deps
npm install

# Run the dev server
npm run dev
```

Frontend runs at **http://localhost:3000**.

Use `localhost`, not `127.0.0.1`, for browser testing so it matches the backend CORS allowlist.

### 3. Test the Flow

1. Open http://localhost:3000 — redirects to `/login`
2. Sign up with email/password (or Google if configured)
3. Click **+ New Chat** in the sidebar
4. Type something like: "I want to apply for a Senior Python Developer role at Google"
5. The AI should search for jobs, ask you questions, and eventually generate documents

---

## Running Locally (With Docker)

### Backend Only (Docker)

```bash
cd backend

# Build the image
docker build -t resume-api .

# Run the container
docker run --rm -p 8000:8000 --env-file .env resume-api
```

Backend runs at **http://localhost:8000**. Frontend still runs with `npm run dev` as above.

### Full Stack (Docker Compose) — optional

If you want both services containerized, create `docker-compose.yml` at the project root:

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    env_file:
      - ./backend/.env
  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL}
      - NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY}
      - NEXT_PUBLIC_API_URL=http://localhost:8000
```

Run: `docker compose up --build`

---

## Running Tests

```bash
cd backend
.venv/bin/python -m pytest tests/ -v

# Local API harness (works through the team access gate)
.venv/bin/python test_api.py \
  --base-url http://127.0.0.1:8000 \
  --access-code '<current-team-access-code>' \
  --verbose

# Resume upload scenario (PDF or DOCX)
.venv/bin/python test_api.py \
  --test upload_and_stream \
  --base-url http://127.0.0.1:8000 \
  --access-code '<current-team-access-code>' \
  --resume /absolute/path/to/resume.docx \
  --verbose
```

## Visual DOCX Rendering on macOS

Use the local render helper to run the full LibreOffice -> PDF -> PNG pipeline:

```bash
scripts/render_docx_macos.sh /absolute/path/to/file.docx
```

Notes:
- This uses `open -n -W -a /Applications/LibreOffice.app --args ...` instead of calling `soffice` directly. On this machine, direct `soffice --headless` crashes, while the LaunchServices path works.
- Install `poppler` first so `pdftoppm` is available: `brew install poppler`
- If macOS prompts when LibreOffice launches, click `Open` or `Allow`
- Output images, PDFs, and LibreOffice logs are written under `tmp/docs/` by default. Override with `RENDER_OUTDIR=/absolute/path`

## Team Access Gate

The shared team-access code is stored in Supabase and is separate from Supabase Auth.

- By default the gate is disabled until you configure the first code.
- When enabled, users must sign in first and then enter the shared code on `/access-code`.
- Rotating the code invalidates all previously verified access until the new code is entered.

See [DEPLOY_TEAM_TEST.md](/Users/aham/projects/dev/resumeAndCoverLetterAutomation/docs/DEPLOY_TEAM_TEST.md) for the SQL snippets to enable, rotate, block, and restore access.

---

## API Endpoints Reference

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| POST | `/conversations` | Yes | Create new conversation `{ "mode": "job_to_resume" }` |
| GET | `/conversations` | Yes | List your conversations |
| GET | `/conversations/{id}` | Yes | Get conversation with messages |
| POST | `/conversations/{id}/messages` | Yes | Send message, get SSE stream |
| GET | `/documents/{id}/download` | Yes | Get signed download URL |

**Auth:** Pass `Authorization: Bearer <supabase-jwt>` header.

**SSE Events** from `/conversations/{id}/messages`:
- `event: message` — AI text chunk `{"content": "..."}`
- `event: status` — Tool status `{"tool": "search_jobs", "state": "running"|"done"}`
- `event: document` — Doc ready `{"document_id": "...", "doc_type": "...", "download_url": "..."}`
- `event: error` — Error `{"message": "..."}`

---

## Troubleshooting

**Backend won't start:**
- Check `.env` file exists in `backend/` and all values are filled in
- Make sure you're using Python 3.11+ (`python3.11 --version`)
- Run `.venv/bin/pip install -r requirements.txt` again

**Frontend build fails with "Supabase URL required":**
- Make sure `frontend/.env.local` exists with all 3 values filled in

**"401 Unauthorized" on API calls:**
- Backend verifies tokens via Supabase JWKS (no JWT secret needed)
- Check that the frontend is sending the JWT token (look at Network tab)
- Make sure `SUPABASE_URL` in backend `.env` is correct (used to fetch JWKS)

**Google OAuth not working:**
- You need to set up OAuth credentials in GCP Console
- Redirect URI must be `https://<project-ref>.supabase.co/auth/v1/callback`
- Enable Google provider in Supabase Dashboard → Auth → Providers

**CORS errors in browser:**
- Make sure `FRONTEND_URL` in backend `.env` matches where the frontend runs
- For local dev, it should be `http://localhost:3000`
