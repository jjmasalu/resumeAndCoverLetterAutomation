# AI Resume & Cover Letter Automation

Automatically generate tailored resumes and cover letters for any job posting — just paste a URL.

---

## How It Works

1. Provide a job posting URL
2. The scraper extracts the job description
3. AI tailors your master resume and generates a cover letter
4. Download a polished `.docx` file

---

## Tech Stack

### Frontend
- **Next.js** — UI for inputting job URLs, managing your master resume, and downloading generated documents
- **Firebase Hosting** — deploys the Next.js app

### Backend
- **Python + FastAPI** — API that orchestrates scraping, AI calls, and document generation
- **Google Cloud Run** — serverless container hosting for the FastAPI app
- **Firebase Auth + Firestore** — user authentication and storing resume data / generation history

### Document Generation
- **docxtpl** (python-docx-template) — fills Jinja2-templated `.docx` files with AI-generated content; design your resume layout in Word once, reuse forever

### Job Research / Scraping
- **Firecrawl** — scrapes job descriptions from dynamic sites (LinkedIn, Indeed, Greenhouse, etc.); handles JS rendering and anti-blocking automatically; outputs clean Markdown for LLMs
- **Tavily** *(optional)* — for discovery/search when you only have a job title, not a direct URL

### AI
- **Claude API (Anthropic)** — generates tailored resume bullet points and cover letter copy from job description + your master resume

---

## Architecture

```
User (Next.js on Firebase Hosting)
        |
        v
FastAPI (Google Cloud Run)
        |
   +---------+----------+
   |                    |
Firecrawl          Claude API
(scrape JD)      (generate content)
        |
   docxtpl
(fill .docx template)
        |
Firestore (store history)
```

---

## Project Structure (planned)

```
/
├── frontend/          # Next.js app
│   └── ...
├── backend/           # FastAPI app
│   ├── main.py
│   ├── scraper.py     # Firecrawl integration
│   ├── generator.py   # Claude API calls
│   ├── docx_builder.py # docxtpl rendering
│   └── templates/     # .docx resume/cover letter templates
└── README.md
```

---

## Key Dependencies

| Layer | Package |
|---|---|
| Backend framework | `fastapi`, `uvicorn` |
| Document generation | `docxtpl` |
| Scraping | `firecrawl-py` |
| AI | `anthropic` |
| Firebase | `firebase-admin` |
| Frontend | `next`, `react` |
