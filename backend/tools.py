import os
import uuid
import io
from datetime import datetime, timezone
from tavily import TavilyClient
from firecrawl import Firecrawl
from docxtpl import DocxTemplate
from config import settings
from db import supabase


tavily_client = TavilyClient(api_key=settings.tavily_api_key)
firecrawl_client = Firecrawl(api_key=settings.firecrawl_api_key)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


async def search_jobs(query: str, location: str | None = None) -> list[dict]:
    """Search for job postings using Tavily."""
    search_query = f"{query} job posting"
    if location:
        search_query += f" {location}"
    try:
        results = tavily_client.search(
            query=search_query,
            max_results=5,
            search_depth="basic",
        )
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "")[:200],
            }
            for r in results.get("results", [])
        ]
    except Exception as e:
        return [{"error": f"Search failed: {str(e)}"}]


async def scrape_job(url: str) -> dict:
    """Scrape a job posting URL using Firecrawl."""
    try:
        result = firecrawl_client.scrape(url, formats=["markdown"])
        markdown = result.markdown or ""
        return {
            "description_md": markdown,
            "url": url,
        }
    except Exception as e:
        return {"error": f"Scraping failed: {str(e)}"}


async def generate_document(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
) -> dict:
    """Generate a .docx document from template and upload to Supabase Storage."""
    template_path = os.path.join(TEMPLATE_DIR, f"{doc_type}.docx")
    try:
        doc = DocxTemplate(template_path)
        doc.render(sections)

        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        doc_id = str(uuid.uuid4())
        storage_path = f"{user_id}/{doc_id}.docx"

        supabase.storage.from_("documents").upload(
            path=storage_path,
            file=buffer.getvalue(),
            file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
        )

        signed_url = supabase.storage.from_("documents").create_signed_url(
            storage_path, 3600
        )

        # Save document record
        supabase.table("generated_documents").insert({
            "id": doc_id,
            "job_id": job_id,
            "user_id": user_id,
            "doc_type": doc_type,
            "file_url": storage_path,
        }).execute()

        return {
            "document_id": doc_id,
            "download_url": signed_url.get("signedURL", ""),
        }
    except Exception as e:
        return {"error": f"Document generation failed: {str(e)}"}


async def save_user_context(
    user_id: str,
    category: str,
    content: dict,
    conversation_id: str | None = None,
) -> dict:
    """Save or update user context in Supabase."""
    try:
        existing = (
            supabase.table("user_context")
            .select("id")
            .eq("user_id", user_id)
            .eq("category", category)
            .execute()
        )

        if existing.data:
            supabase.table("user_context").update({
                "content": content,
                "source_conversation_id": conversation_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("user_context").insert({
                "user_id": user_id,
                "category": category,
                "content": content,
                "source_conversation_id": conversation_id,
            }).execute()

        return {"status": "saved", "category": category}
    except Exception as e:
        return {"error": f"Context save failed: {str(e)}"}
