import asyncio
import logging
import uuid
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse, urlunparse
from tavily import TavilyClient
from firecrawl import Firecrawl
from config import settings
from db import supabase
from document_engine import (
    build_document_plan,
    normalize_document_sections as _normalize_document_sections,
    render_document,
    serialize_document_plan,
)
from document_filenames import (
    default_generated_document_filename,
    next_versioned_filename,
    semantic_generated_document_filename,
)

logger = logging.getLogger(__name__)

tavily_client = TavilyClient(api_key=settings.tavily_api_key)
firecrawl_client = Firecrawl(api_key=settings.firecrawl_api_key)

AGGREGATOR_DOMAINS = {
    "indeed.com",
    "linkedin.com",
    "glassdoor.com",
    "ziprecruiter.com",
    "monster.com",
    "simplyhired.com",
    "wellfound.com",
    "builtin.com",
    "builtinnyc.com",
    "builtinseattle.com",
    "remote.co",
    "weworkremotely.com",
    "4dayweek.io",
    "crossover.com",
}
ATS_SEARCH_DOMAINS = (
    "jobs.lever.co",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "myworkdaysite.com",
    "jobs.smartrecruiters.com",
)
KNOWN_HTTPS_ONLY_DOMAINS = {
    "jobs.lever.co",
    "boards.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.ashbyhq.com",
    "jobs.smartrecruiters.com",
}
LISTING_TITLE_PATTERNS = (
    "jobs in",
    "all jobs",
    "job openings",
    "remote jobs",
    "work from home",
    "now hiring",
    "careers at",
    "search results",
)
LISTING_MARKDOWN_PATTERNS = (
    "keyword : all jobs",
    "date posted",
    "job type",
    "experience level",
    "distance",
    "encouraged to apply",
)
MISSING_PAGE_PATTERNS = (
    "sorry, but we can't find that page",
    "job is no longer available",
    "job no longer exists",
    "no longer accepting applications",
    "this job has expired",
)
AUTH_WALL_PATTERNS = (
    "sign in",
    "log in",
    "create account",
    "access denied",
    "forbidden",
    "captcha",
    "managed challenge",
)
WORKDAY_UNAVAILABLE_PATTERNS = (
    "workday is currently unavailable",
    "service interruption",
    "your service will be restored as quickly as possible",
)
MIN_ACCEPTABLE_JOB_MARKDOWN = 400

DocumentProgressCallback = Callable[[dict], None]
VARIANT_LABELS = {
    "ats_safe": "ATS-safe",
    "creative_safe": "Creative-safe",
}


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _normalize_job_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = parsed.netloc.lower()
    if not host:
        return url

    host_no_www = host[4:] if host.startswith("www.") else host
    scheme = "https" if host_no_www in KNOWN_HTTPS_ONLY_DOMAINS else (parsed.scheme or "https")

    query = parse_qs(parsed.query, keep_blank_values=False)
    keep_query: dict[str, list[str]] = {}
    if host_no_www == "boards.greenhouse.io" and parsed.path == "/embed/job_app":
        token = query.get("token")
        if token:
            keep_query["token"] = token

    normalized = parsed._replace(
        scheme=scheme,
        query="&".join(
            f"{key}={value}"
            for key, values in keep_query.items()
            for value in values
        ),
        fragment="",
    )
    return urlunparse(normalized)


def _inspect_job_url(url: str) -> dict[str, Any]:
    normalized_url = _normalize_job_url(url)
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    host_no_www = host[4:] if host.startswith("www.") else host
    path = parsed.path.rstrip("/")
    title_hint = ""

    inspection = {
        "normalized_url": normalized_url,
        "domain": host_no_www,
        "platform": "unknown",
        "url_kind": "unknown",
        "canonical_candidate": False,
    }

    if not host_no_www:
        return inspection

    if any(_host_matches(host_no_www, domain) for domain in AGGREGATOR_DOMAINS):
        inspection["platform"] = "aggregator"
        if (
            "/viewjob" in path
            or "/jobs/view" in path
            or "/job-listing/" in path
        ):
            inspection["url_kind"] = "aggregator_job"
        else:
            inspection["url_kind"] = "aggregator_listing"
        return inspection

    if host_no_www == "jobs.lever.co":
        inspection["platform"] = "lever"
        segments = [segment for segment in path.split("/") if segment]
        inspection["url_kind"] = "direct_job" if len(segments) >= 2 else "listing_page"
        inspection["canonical_candidate"] = inspection["url_kind"] == "direct_job"
        return inspection

    if host_no_www in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        inspection["platform"] = "greenhouse"
        if parsed.path == "/embed/job_app" and parse_qs(parsed.query).get("token"):
            inspection["url_kind"] = "direct_job"
        elif re.match(r"^/[^/]+/jobs/\d+$", path):
            inspection["url_kind"] = "direct_job"
        else:
            inspection["url_kind"] = "listing_page"
        inspection["canonical_candidate"] = inspection["url_kind"] == "direct_job"
        return inspection

    if host_no_www == "jobs.ashbyhq.com":
        inspection["platform"] = "ashby"
        segments = [segment for segment in path.split("/") if segment]
        inspection["url_kind"] = "direct_job" if len(segments) >= 2 else "listing_page"
        inspection["canonical_candidate"] = inspection["url_kind"] == "direct_job"
        return inspection

    if "myworkdayjobs.com" in host_no_www or "myworkdaysite.com" in host_no_www:
        inspection["platform"] = "workday"
        if "/job/" in path:
            inspection["url_kind"] = "direct_job"
            inspection["canonical_candidate"] = True
        else:
            inspection["url_kind"] = "listing_page"
        return inspection

    if host_no_www == "jobs.smartrecruiters.com":
        inspection["platform"] = "smartrecruiters"
        segments = [segment for segment in path.split("/") if segment]
        inspection["url_kind"] = "direct_job" if len(segments) >= 2 else "listing_page"
        inspection["canonical_candidate"] = inspection["url_kind"] == "direct_job"
        return inspection

    if host_no_www.startswith("careers.") or ".careers." in host_no_www:
        inspection["platform"] = "company_careers"
        if any(marker in path.lower() for marker in ("/job/", "/positions/", "/careers/")):
            inspection["url_kind"] = "direct_job"
            inspection["canonical_candidate"] = True
        else:
            inspection["url_kind"] = "listing_page"
        return inspection

    if path.lower().endswith("/jobs") or path.lower().endswith("/careers"):
        inspection["platform"] = "company_careers"
        inspection["url_kind"] = "listing_page"
        return inspection

    if any(marker in path.lower() for marker in ("/job/", "/jobs/", "/positions/")):
        inspection["platform"] = "company_careers"
        inspection["url_kind"] = "direct_job"
        inspection["canonical_candidate"] = True
        return inspection

    return inspection


def _looks_like_listing_title(title: str) -> bool:
    lower = (title or "").strip().lower()
    return any(_contains_phrase(lower, pattern) for pattern in LISTING_TITLE_PATTERNS)


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = r"\b" + re.escape(phrase).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, text) is not None


def _search_result_score(item: dict[str, Any]) -> int:
    score = 0
    url_kind = item.get("url_kind")
    platform = item.get("platform")
    if url_kind == "direct_job":
        score += 100
    elif url_kind == "aggregator_job":
        score += 15
    elif url_kind in {"listing_page", "aggregator_listing"}:
        score -= 120

    if platform in {"lever", "greenhouse", "ashby", "smartrecruiters"}:
        score += 25
    elif platform == "workday":
        score += 10
    elif platform == "company_careers":
        score += 20
    elif platform == "aggregator":
        score -= 30

    if _looks_like_listing_title(item.get("title", "")):
        score -= 45

    if item.get("canonical_candidate"):
        score += 25

    return score


def _normalize_search_result(raw: dict[str, Any], *, search_pass: str) -> dict[str, Any]:
    inspection = _inspect_job_url(raw.get("url", ""))
    item = {
        "title": raw.get("title", "").strip(),
        "url": inspection["normalized_url"],
        "snippet": (raw.get("content") or raw.get("snippet") or "").strip()[:240],
        "domain": inspection["domain"],
        "platform": inspection["platform"],
        "url_kind": inspection["url_kind"],
        "canonical_candidate": inspection["canonical_candidate"],
        "search_pass": search_pass,
    }
    item["score"] = _search_result_score(item)
    return item


def _metadata_to_dict(metadata: Any) -> dict[str, Any]:
    if metadata is None:
        return {}
    if hasattr(metadata, "model_dump"):
        return metadata.model_dump(exclude_none=True)
    if isinstance(metadata, dict):
        return {k: v for k, v in metadata.items() if v is not None}
    return {
        key: value
        for key, value in vars(metadata).items()
        if value is not None and not key.startswith("_")
    }


def _extract_heading_title(markdown: str) -> str | None:
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        if stripped.startswith("## "):
            return stripped[3:].strip()
    return None


def _scrape_title(markdown: str, metadata: dict[str, Any]) -> str:
    heading_title = _extract_heading_title(markdown)
    if heading_title:
        return heading_title
    title = str(metadata.get("title") or metadata.get("og_title") or "").strip()
    title = re.sub(r"^Job Application for\s+", "", title, flags=re.IGNORECASE)
    if " at " in title:
        title = title.split(" at ", 1)[0].strip()
    if " - " in title and not title.lower().startswith("sr. "):
        left, right = title.split(" - ", 1)
        if len(right.split()) <= len(left.split()) + 2:
            title = right.strip()
    return title or "Job Posting"


def _scrape_blockers(inspection: dict[str, Any], markdown: str, metadata: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    lower = (markdown or "").lower()
    status_code = metadata.get("status_code")
    error = metadata.get("error")

    if inspection["url_kind"] in {"listing_page", "aggregator_listing"}:
        blockers.append("non_specific_job_page")

    if status_code and int(status_code) >= 400:
        blockers.append(f"upstream_http_{status_code}")

    if error:
        blockers.append("provider_error")

    if any(_contains_phrase(lower, pattern) for pattern in MISSING_PAGE_PATTERNS):
        blockers.append("job_not_found")

    if any(_contains_phrase(lower, pattern) for pattern in AUTH_WALL_PATTERNS):
        blockers.append("access_wall")

    if any(_contains_phrase(lower, pattern) for pattern in LISTING_MARKDOWN_PATTERNS):
        blockers.append("listing_page_content")

    if inspection["platform"] == "workday" and (
        "errorcode" in lower or (status_code and int(status_code) >= 400)
    ):
        blockers.append("workday_access_issue")
    if inspection["platform"] == "workday" and any(
        _contains_phrase(lower, pattern) for pattern in WORKDAY_UNAVAILABLE_PATTERNS
    ):
        blockers.append("workday_unavailable")

    if len((markdown or "").strip()) < MIN_ACCEPTABLE_JOB_MARKDOWN:
        blockers.append("insufficient_content")

    deduped: list[str] = []
    for blocker in blockers:
        if blocker not in deduped:
            deduped.append(blocker)
    return deduped


def _scrape_error_response(
    *,
    message: str,
    code: str,
    inspection: dict[str, Any],
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "error": message,
        "error_code": code,
        "url": inspection["normalized_url"],
        "platform": inspection["platform"],
        "url_kind": inspection["url_kind"],
        "canonical_candidate": inspection["canonical_candidate"],
        "blockers": blockers or [],
    }

def _canonicalize_for_merge(value):
    if isinstance(value, dict):
        return {
            key: _canonicalize_for_merge(val)
            for key, val in sorted(value.items())
        }
    if isinstance(value, list):
        return [_canonicalize_for_merge(item) for item in value]
    return value


def _merge_context_content(existing, incoming):
    """Merge progressively learned user context instead of overwriting it."""
    if existing in (None, {}, [], ""):
        return incoming
    if incoming in (None, {}, [], ""):
        return existing

    if isinstance(existing, dict) and isinstance(incoming, dict):
        merged = dict(existing)
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _merge_context_content(merged[key], value)
            else:
                merged[key] = value
        return merged

    if isinstance(existing, list) and isinstance(incoming, list):
        merged = list(existing)
        seen = {
            json.dumps(_canonicalize_for_merge(item), sort_keys=True, default=str)
            for item in existing
        }
        for item in incoming:
            key = json.dumps(_canonicalize_for_merge(item), sort_keys=True, default=str)
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
        return merged

    return incoming


def _search_jobs_sync(query: str, location: str | None = None) -> list[dict]:
    """Search for direct job postings using Tavily."""
    search_query = f"{query} job posting"
    if location:
        search_query += f" {location}"
    logger.info("search_jobs query=%s", search_query)

    search_passes = [
        (
            "ats_canonical",
            {
                "query": search_query,
                "max_results": 10,
                "search_depth": "advanced",
                "include_domains": ATS_SEARCH_DOMAINS,
                "timeout": 20,
            },
        ),
        (
            "broad_filtered",
            {
                "query": search_query,
                "max_results": 10,
                "search_depth": "advanced",
                "exclude_domains": sorted(AGGREGATOR_DOMAINS),
                "timeout": 20,
            },
        ),
        (
            "broad_fallback",
            {
                "query": search_query,
                "max_results": 5,
                "search_depth": "basic",
                "timeout": 20,
            },
        ),
    ]
    try:
        deduped: dict[str, dict[str, Any]] = {}
        for search_pass, kwargs in search_passes:
            results = tavily_client.search(**kwargs)
            for raw in results.get("results", []):
                normalized = _normalize_search_result(raw, search_pass=search_pass)
                if not normalized["url"]:
                    continue
                existing = deduped.get(normalized["url"])
                if existing is None or normalized["score"] > existing["score"]:
                    deduped[normalized["url"]] = normalized

            if any(item["canonical_candidate"] for item in deduped.values()):
                break

        ranked = sorted(
            deduped.values(),
            key=lambda item: (
                item["score"],
                item["canonical_candidate"],
                len(item.get("snippet", "")),
            ),
            reverse=True,
        )
        filtered = [item for item in ranked if item["score"] > -100] or ranked
        items = [
            {
                "title": item["title"],
                "url": item["url"],
                "snippet": item["snippet"],
                "domain": item["domain"],
                "platform": item["platform"],
                "url_kind": item["url_kind"],
                "canonical_candidate": item["canonical_candidate"],
            }
            for item in filtered[:6]
        ]
        logger.info(
            "search_jobs found %d results canonical=%d",
            len(items),
            sum(1 for item in items if item.get("canonical_candidate")),
        )
        if items:
            return items
        return [{"error": "No job postings found. Try a more specific role or company."}]
    except Exception as e:
        logger.error("search_jobs failed: %s", e)
        return [{"error": f"Search failed: {str(e)}"}]


async def search_jobs(query: str, location: str | None = None) -> list[dict]:
    return await asyncio.to_thread(_search_jobs_sync, query, location)


def _scrape_job_sync(url: str) -> dict:
    """Scrape a job posting URL using Firecrawl with quality checks."""
    inspection = _inspect_job_url(url)
    normalized_url = inspection["normalized_url"]
    logger.info(
        "scrape_job url=%s platform=%s kind=%s",
        normalized_url,
        inspection["platform"],
        inspection["url_kind"],
    )

    if inspection["url_kind"] in {"listing_page", "aggregator_listing"}:
        return _scrape_error_response(
            message="This URL looks like a job board or search results page, not a specific job posting.",
            code="non_specific_job_url",
            inspection=inspection,
            blockers=["non_specific_job_page"],
        )

    try:
        result = firecrawl_client.scrape(
            normalized_url,
            formats=["markdown", "html", "links"],
            only_main_content=True,
            timeout=30000,
            wait_for=1500,
            block_ads=True,
        )
        markdown = result.markdown or ""
        metadata = _metadata_to_dict(getattr(result, "metadata", None))
        blockers = _scrape_blockers(inspection, markdown, metadata)
        title = _scrape_title(markdown, metadata)

        failure_blockers = [
            blocker
            for blocker in blockers
            if blocker
            in {
                "non_specific_job_page",
                "upstream_http_400",
                "upstream_http_401",
                "upstream_http_403",
                "upstream_http_404",
                "upstream_http_429",
                "upstream_http_500",
                "provider_error",
                "job_not_found",
                "access_wall",
                "workday_access_issue",
                "workday_unavailable",
                "insufficient_content",
            }
        ]
        if failure_blockers:
            primary = failure_blockers[0]
            message_map = {
                "job_not_found": "That job posting appears to be unavailable or expired.",
                "access_wall": "That page appears to require sign-in or anti-bot clearance before it can be read.",
                "workday_access_issue": "That Workday URL could not be read as a direct job posting. Workday board URLs often need a specific job page.",
                "workday_unavailable": "That Workday job page is currently returning a Workday outage or maintenance screen instead of the job description.",
                "insufficient_content": "I could reach the page, but it did not expose enough job-description content to use reliably.",
                "non_specific_job_page": "This URL does not point to a specific job posting.",
            }
            default_message = f"Job scraping failed because of {primary.replace('_', ' ')}."
            return _scrape_error_response(
                message=message_map.get(primary, default_message),
                code=primary,
                inspection=inspection,
                blockers=blockers,
            )

        quality = "high" if inspection["canonical_candidate"] else "medium"
        logger.info(
            "scrape_job success md_len=%d quality=%s blockers=%s",
            len(markdown),
            quality,
            ",".join(blockers) if blockers else "none",
        )
        return {
            "description_md": markdown,
            "url": normalized_url,
            "canonical_url": metadata.get("og_url") or metadata.get("url") or normalized_url,
            "title": title,
            "platform": inspection["platform"],
            "url_kind": inspection["url_kind"],
            "canonical_candidate": inspection["canonical_candidate"],
            "quality": quality,
            "blockers": blockers,
            "metadata": {
                "status_code": metadata.get("status_code"),
                "title": metadata.get("title"),
                "og_title": metadata.get("og_title"),
                "error": metadata.get("error"),
                "scrape_id": metadata.get("scrape_id"),
            },
        }
    except Exception as e:
        logger.error("scrape_job failed: %s", e)
        return _scrape_error_response(
            message=f"Scraping failed: {str(e)}",
            code="scrape_exception",
            inspection=inspection,
        )


async def scrape_job(url: str) -> dict:
    return await asyncio.to_thread(_scrape_job_sync, url)


def _emit_document_progress(
    progress_callback: DocumentProgressCallback | None,
    *,
    phase: str,
    state: str,
    detail: str | None = None,
    meta: dict | None = None,
) -> None:
    if not progress_callback:
        return
    payload = {
        "phase": phase,
        "state": state,
    }
    if detail:
        payload["detail"] = detail
    if meta:
        payload["meta"] = meta
    try:
        progress_callback(payload)
    except Exception as error:
        logger.warning("document progress callback failed for %s/%s: %s", phase, state, error)


def _summarize_repair_actions(repair_history: list[dict]) -> str:
    labels = {
        "switch_theme": "switched to a denser theme",
        "tighten_text_budgets": "tightened summary and skills budgets",
        "reduce_bullets": "reduced experience bullets",
        "drop_low_priority_experience": "trimmed lower-priority experience",
        "tighten_cover_letter_budgets": "tightened paragraph budgets",
        "reduce_cover_letter_paragraphs": "reduced paragraph count",
        "tighten_cover_letter_text": "tightened cover letter text",
    }
    actions = [
        labels.get(str(item.get("action")), str(item.get("action", "")).replace("_", " "))
        for item in repair_history
        if item.get("action")
    ]
    if not actions:
        return ""
    if len(actions) == 1:
        return actions[0].capitalize() + "."
    if len(actions) == 2:
        return f"{actions[0].capitalize()} and {actions[1]}."
    return f"{actions[0].capitalize()}, {actions[1]}, and more."


def _variant_label(variant_key: str | None) -> str | None:
    return VARIANT_LABELS.get(str(variant_key or "").strip().lower())


def _is_dual_variant_resume_plan(doc_type: str, plan) -> bool:
    return doc_type == "resume" and getattr(plan, "theme_id", "") == "modern_minimal"


def _build_document_variants(doc_type: str, sections: dict) -> list[dict[str, Any]]:
    primary_plan = build_document_plan(doc_type, sections)
    variants: list[dict[str, Any]] = [
        {
            "plan": primary_plan,
            "variant_key": None,
            "variant_label": None,
        }
    ]

    if not _is_dual_variant_resume_plan(doc_type, primary_plan):
        return variants

    alternate_sections = dict(primary_plan.normalized_sections)
    alternate_sections.pop("theme_id", None)
    alternate_sections["layout_strategy"] = "ats_safe"
    alternate_plan = build_document_plan(doc_type, alternate_sections)
    if alternate_plan.theme_id == primary_plan.theme_id:
        return variants

    variants[0]["variant_key"] = "creative_safe"
    variants[0]["variant_label"] = _variant_label("creative_safe")
    variants.append(
        {
            "plan": alternate_plan,
            "variant_key": "ats_safe",
            "variant_label": _variant_label("ats_safe"),
        }
    )
    return variants


def _build_document_variants_for_request(
    doc_type: str,
    sections: dict,
    *,
    force_variant_key: str | None = None,
) -> list[dict[str, Any]]:
    normalized_force = str(force_variant_key or "").strip().lower() or None
    if normalized_force == "ats_safe":
        forced_sections = dict(sections)
        forced_sections.pop("theme_id", None)
        forced_sections["layout_strategy"] = "ats_safe"
        forced_plan = build_document_plan(doc_type, forced_sections)
        return [
            {
                "plan": forced_plan,
                "variant_key": "ats_safe",
                "variant_label": _variant_label("ats_safe"),
            }
        ]
    if normalized_force == "creative_safe":
        forced_sections = dict(sections)
        forced_sections.pop("theme_id", None)
        forced_sections["layout_strategy"] = "creative_safe"
        forced_plan = build_document_plan(doc_type, forced_sections)
        return [
            {
                "plan": forced_plan,
                "variant_key": "creative_safe",
                "variant_label": _variant_label("creative_safe"),
            }
        ]
    return _build_document_variants(doc_type, sections)


def _document_variant_summary(variants: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    labels = [
        variant["variant_label"]
        for variant in variants
        if variant.get("variant_label")
    ]
    primary_plan = variants[0]["plan"]
    meta = {
        "theme_id": primary_plan.theme_id,
        "density": primary_plan.density,
        "attempt_count": primary_plan.attempt_count,
        "variant_count": len(variants),
    }
    if labels:
        meta["variant_labels"] = labels
    if len(labels) >= 2:
        return (
            f"Prepared {', '.join(labels[:-1])} and {labels[-1]} variants.",
            meta,
        )
    return (
        f"Selected {primary_plan.theme_id.replace('_', ' ')} theme.",
        meta,
    )


def _resolve_generated_document_filename(
    *,
    doc_type: str,
    sections: dict,
    user_id: str,
    variant_key: str | None = None,
) -> str:
    base_filename = semantic_generated_document_filename(
        doc_type,
        sections,
        variant_key=variant_key,
    )
    try:
        existing = (
            supabase.table("generated_documents")
            .select("filename")
            .eq("user_id", user_id)
            .execute()
        )
        existing_filenames = [
            row.get("filename")
            for row in (existing.data or [])
            if row.get("filename")
        ]
    except Exception as error:
        logger.warning("failed to load existing generated filenames: %s", error)
        existing_filenames = []

    return next_versioned_filename(base_filename, existing_filenames)


def _generate_document_sync(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
    progress_callback: DocumentProgressCallback | None = None,
    conversation_id: str | None = None,
    force_variant_key: str | None = None,
    variant_group_id: str | None = None,
) -> dict:
    """Generate a .docx document from template and upload to Supabase Storage."""
    logger.info("generate_document type=%s job_id=%s", doc_type, job_id[:8])
    active_phase = "plan"
    generated_at = datetime.now(timezone.utc)
    try:
        _emit_document_progress(
            progress_callback,
            phase="plan",
            state="running",
        )
        variants = _build_document_variants_for_request(
            doc_type,
            sections,
            force_variant_key=force_variant_key,
        )
        plan = variants[0]["plan"]
        plan_detail, plan_meta = _document_variant_summary(variants)
        _emit_document_progress(
            progress_callback,
            phase="plan",
            state="done",
            detail=plan_detail,
            meta=plan_meta,
        )
        if plan.repair_history:
            _emit_document_progress(
                progress_callback,
                phase="repair",
                state="done",
                detail=_summarize_repair_actions(plan.repair_history),
                meta={
                    "repair_actions": [item.get("action") for item in plan.repair_history],
                    "attempt_count": plan.attempt_count,
                },
            )
        verification = plan.verification or {}
        verification_status = verification.get("status", "passed")
        verification_issues = verification.get("issues") or []
        verification_detail = (
            f"Fits the {plan.page_budget}-page budget."
            if verification_status == "passed"
            else (verification_issues[0].get("message") if verification_issues else "Layout verification failed.")
        )
        _emit_document_progress(
            progress_callback,
            phase="verify",
            state="done" if verification_status == "passed" else "failed",
            detail=verification_detail,
            meta={
                "verification_status": verification_status,
                "page_budget": plan.page_budget,
            },
        )

        _emit_document_progress(
            progress_callback,
            phase="render",
            state="running",
            detail=(
                "Building resume variants."
                if len(variants) > 1
                else None
            ),
        )
        active_phase = "render"
        rendered_documents: list[dict[str, Any]] = []
        for variant in variants:
            rendered_documents.append(
                {
                    **variant,
                    "document_bytes": render_document(variant["plan"]),
                }
            )
        _emit_document_progress(
            progress_callback,
            phase="render",
            state="done",
            detail=(
                f"Built {len(rendered_documents)} DOCX resume variants."
                if len(rendered_documents) > 1
                else "Built the DOCX document."
            ),
        )

        _emit_document_progress(
            progress_callback,
            phase="save",
            state="running",
            detail=(
                "Saving both resume variants."
                if len(rendered_documents) > 1
                else None
            ),
        )
        active_phase = "save"
        active_variant_group_id = (
            variant_group_id
            or (str(uuid.uuid4()) if len(rendered_documents) > 1 else None)
        )
        saved_documents: list[dict[str, Any]] = []
        for rendered in rendered_documents:
            variant_key = rendered.get("variant_key")
            variant_label = rendered.get("variant_label")
            variant_plan = rendered["plan"]
            filename = _resolve_generated_document_filename(
                doc_type=doc_type,
                sections=sections,
                user_id=user_id,
                variant_key=variant_key,
            )
            doc_id = str(uuid.uuid4())
            storage_path = f"{user_id}/{doc_id}.docx"

            supabase.storage.from_("documents").upload(
                path=storage_path,
                file=rendered["document_bytes"],
                file_options={"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            )

            signed_url = supabase.storage.from_("documents").create_signed_url(
                storage_path, 3600
            )

            supabase.table("generated_documents").insert({
                "id": doc_id,
                "job_id": job_id,
                "user_id": user_id,
                "doc_type": doc_type,
                "filename": filename,
                "file_url": storage_path,
                "theme_id": variant_plan.theme_id,
                "variant_key": variant_key,
                "variant_label": variant_label,
                "variant_group_id": active_variant_group_id,
                "source_sections": sections,
                "source_conversation_id": conversation_id,
            }).execute()
            saved_documents.append(
                {
                    "document_id": doc_id,
                    "doc_type": doc_type,
                    "filename": filename or default_generated_document_filename(doc_type, generated_at),
                    "download_url": signed_url.get("signedURL", ""),
                    "theme_id": variant_plan.theme_id,
                    "page_budget": variant_plan.page_budget,
                    "document_plan": serialize_document_plan(variant_plan),
                    "variant_key": variant_key,
                    "variant_label": variant_label,
                    "variant_group_id": active_variant_group_id,
                    "can_regenerate": bool(sections),
                }
            )
        _emit_document_progress(
            progress_callback,
            phase="save",
            state="done",
            detail=(
                "Stored both variants and generated download links."
                if len(saved_documents) > 1
                else "Stored the document and generated a download link."
            ),
        )

        primary_document = saved_documents[0]
        logger.info(
            "generate_document success doc_id=%s count=%d",
            primary_document["document_id"][:8],
            len(saved_documents),
        )
        return {
            **primary_document,
            "documents": saved_documents,
            "variant_count": len(saved_documents),
            "variant_group_id": active_variant_group_id,
        }
    except Exception as e:
        logger.error("generate_document failed: %s", e)
        _emit_document_progress(
            progress_callback,
            phase=active_phase,
            state="failed",
            detail=f"{str(e)}",
        )
        return {"error": f"Document generation failed: {str(e)}"}


async def generate_document(
    doc_type: str,
    sections: dict,
    user_id: str,
    job_id: str,
    progress_callback: DocumentProgressCallback | None = None,
    conversation_id: str | None = None,
    force_variant_key: str | None = None,
    variant_group_id: str | None = None,
) -> dict:
    return await asyncio.to_thread(
        _generate_document_sync,
        doc_type,
        sections,
        user_id,
        job_id,
        progress_callback,
        conversation_id,
        force_variant_key,
        variant_group_id,
    )


def _save_user_context_sync(
    user_id: str,
    category: str,
    content: dict,
    conversation_id: str | None = None,
) -> dict:
    """Save or update user context in Supabase."""
    logger.info("save_user_context category=%s", category)
    try:
        existing = (
            supabase.table("user_context")
            .select("id, content")
            .eq("user_id", user_id)
            .eq("category", category)
            .execute()
        )

        if existing.data:
            merged_content = _merge_context_content(
                existing.data[0].get("content"),
                content,
            )
            supabase.table("user_context").update({
                "content": merged_content,
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

        logger.info("save_user_context saved category=%s", category)
        return {"status": "saved", "category": category}
    except Exception as e:
        logger.error("save_user_context failed: %s", e)
        return {"error": f"Context save failed: {str(e)}"}


async def save_user_context(
    user_id: str,
    category: str,
    content: dict,
    conversation_id: str | None = None,
) -> dict:
    return await asyncio.to_thread(
        _save_user_context_sync,
        user_id,
        category,
        content,
        conversation_id,
    )
