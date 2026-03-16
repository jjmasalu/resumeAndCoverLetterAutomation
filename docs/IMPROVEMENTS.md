# Known Issues & Future Improvements

## Bugs to Fix

### 1. ~~Document type missing from download card~~ (Fixed)
Fixed in UI redesign — DownloadCard now receives `doc_type` from the document SSE event.

### 2. ~~Long URLs overflow chat bubbles~~ (Fixed)
Fixed in UI redesign — `overflow-wrap: anywhere` added to ChatMessage.

### 3. AI dumps raw download URLs in messages
The AI pastes the full Supabase signed URL (with JWT token) into the chat message text. This is redundant since the `DownloadCard` component already provides the download link. Fix: instruct the system prompt to not include download links in its text.

### 4. ~~Status pills and download cards lost on page reload~~ (Partially fixed)
Documents now persist via the conversation API endpoint (`/conversations/{id}` returns `documents`). Status pills are still ephemeral SSE state and only show during active streaming.

### 5. ~~All conversations titled "New conversation"~~ (Fixed)
Fixed — auto-titling implemented in a prior commit.

---

## UX Improvements

### 6. User profile / memory system
Currently the AI asks questions each conversation to learn about the user. The `user_context` table stores what it learns, but users have no way to view or edit it. This is the biggest UX gap.

**Recommended approach:**
- Add a **"My Profile"** page showing all saved context (work experience, skills, education, preferences) in an editable form
- Let users paste an existing resume to bootstrap their profile (parse with Gemini or a dedicated parser)
- The AI should check existing context before asking questions it already has answers to
- Show a "the AI knows this about you" summary at the start of each new conversation
- Allow users to mark certain info as "always include" vs "available if relevant"

**Why this matters:** The best UX is when the AI already knows the user after 1-2 conversations and can generate documents with minimal questions. The profile page gives users control and transparency over what the AI remembers.

### 7. Resume upload / import
Let users upload an existing resume (PDF or .docx) and auto-extract their profile info. This eliminates the cold-start problem where the AI has to ask 10+ questions before it can generate anything useful.

### 8. ATS score / keyword matching
After generating a resume, show an ATS compatibility score comparing the resume keywords against the job description. Highlight missing keywords the user might want to add.

### 9. Multiple document versions
Let users generate multiple resume versions for the same job with different emphasis (e.g., "highlight leadership" vs "highlight technical depth"). Store and compare versions.

### 10. PDF export
Add PDF export alongside .docx. Many job applications require PDF. Can be done via `python-docx` → PDF conversion or a dedicated library like WeasyPrint.

### 11. ~~Markdown rendering in chat~~ (Fixed)
Fixed in UI redesign — `react-markdown` with theme-aware prose styling in ChatMessage.

### 12. ~~Conversation search and filtering~~ (Fixed)
Fixed in UI redesign — SearchOverlay (Cmd+K) with mode filters, plus History page with mode and status filter pills.

---

## Architecture Improvements

### 13. Alternative scraping providers
Firecrawl works well for individual job URLs but struggles with heavily protected sites (LinkedIn, Indeed). Consider:
- **Crawl4AI** — open-source, free, good for LLM pipelines
- **Scrape.do** — 98% success on protected sites
- Or a fallback chain: try Firecrawl first, fall back to alternative if it fails

### 14. Better job search
Tavily is a general web search API, not specialized for jobs. For better job-specific results:
- **Exa** — semantic search with 1B+ LinkedIn profiles indexed, supports role/location filters
- **Direct job board APIs** — LinkedIn, Indeed, Greenhouse have APIs (with varying access requirements)

### 15. Streaming optimization
Currently the full conversation history is sent to Gemini on every message. For long conversations, this gets expensive. Consider:
- Summarizing older messages
- Truncating history beyond a window
- Caching the Gemini session

### 16. Background job processing
Long operations (scraping, document generation) block the SSE stream. Consider using background tasks with progress updates for better UX on slow scrapes.

### 17. Rate limiting
No rate limiting on API endpoints. Add per-user rate limits to prevent abuse, especially on expensive operations (Gemini calls, Firecrawl scrapes).

### 18. Template management
Currently two fixed templates (resume, cover letter). Allow users to upload their own .docx templates or choose from a library of designs.

---

## Deployment TODO

- [ ] Deploy backend to Google Cloud Run
- [ ] Deploy frontend to Vercel
- [ ] Set up production environment variables
- [ ] Configure production CORS origins
- [ ] Set up Supabase production project (or use existing)
- [ ] Add monitoring / error tracking (Sentry or similar)
- [ ] Set up CI/CD pipeline
