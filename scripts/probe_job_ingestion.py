#!/usr/bin/env python3
"""Probe job-search and job-scrape behavior against real providers.

Examples:
  python3 scripts/probe_job_ingestion.py
  python3 scripts/probe_job_ingestion.py --query "product designer" --location remote
  python3 scripts/probe_job_ingestion.py --url "https://jobs.lever.co/inkitt/3d466a0d-1de6-40c6-ade9-9aec2b14c71e"
  python3 scripts/probe_job_ingestion.py --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import tools  # noqa: E402


DEFAULT_QUERIES = [
    ("software engineer remote", None),
    ("product designer", "remote"),
]
DEFAULT_URLS = [
    "https://jobs.lever.co/viget/c1d00dd1-a38d-4302-a046-df3995a712e6",
    "https://job-boards.greenhouse.io/xapo61/jobs/7572065003",
    "https://jobs.ashbyhq.com/office-hours/0f894e8b-836a-4ef8-ab30-894270c49c11",
    "https://www.indeed.com/q-software-engineer-remote-jobs.html",
    "https://transunion.wd5.myworkdayjobs.com/wday/cxs/transunion/transunion/jobs",
]


async def probe_query(query: str, location: str | None) -> dict[str, Any]:
    results = await tools.search_jobs(query, location)
    canonical = next(
        (
            item
            for item in results
            if isinstance(item, dict) and item.get("canonical_candidate") and item.get("url")
        ),
        None,
    )
    scraped = await tools.scrape_job(canonical["url"]) if canonical else None
    return {
        "query": query,
        "location": location,
        "results": results,
        "canonical_probe": scraped,
    }


async def probe_url(url: str) -> dict[str, Any]:
    inspection = tools._inspect_job_url(url)
    scrape = await tools.scrape_job(url)
    return {
        "url": url,
        "inspection": inspection,
        "scrape": scrape,
    }


def _print_query_probe(payload: dict[str, Any]) -> None:
    query = payload["query"]
    location = payload["location"]
    print(f"\n=== QUERY {query!r} location={location!r} ===")
    for index, item in enumerate(payload["results"], 1):
        if "error" in item:
            print(f"{index}. ERROR {item['error']}")
            continue
        print(
            f"{index}. [{item.get('platform')}/{item.get('url_kind')}] "
            f"canonical={item.get('canonical_candidate')} "
            f"{item.get('title')} :: {item.get('url')}"
        )
    scraped = payload.get("canonical_probe")
    if scraped:
        if scraped.get("error"):
            print(
                f"canonical scrape -> ERROR {scraped.get('error_code')}: {scraped.get('error')}"
            )
        else:
            print(
                f"canonical scrape -> OK {scraped.get('platform')}/{scraped.get('quality')} "
                f"title={scraped.get('title')!r} md_len={len(scraped.get('description_md', ''))}"
            )


def _print_url_probe(payload: dict[str, Any]) -> None:
    print(f"\n=== URL {payload['url']} ===")
    inspection = payload["inspection"]
    print(
        f"inspection -> platform={inspection.get('platform')} "
        f"kind={inspection.get('url_kind')} canonical={inspection.get('canonical_candidate')}"
    )
    scrape = payload["scrape"]
    if scrape.get("error"):
        print(
            f"scrape -> ERROR {scrape.get('error_code')}: {scrape.get('error')} "
            f"blockers={scrape.get('blockers')}"
        )
    else:
        print(
            f"scrape -> OK {scrape.get('platform')}/{scrape.get('quality')} "
            f"title={scrape.get('title')!r} md_len={len(scrape.get('description_md', ''))} "
            f"blockers={scrape.get('blockers')}"
        )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", action="append", help="Job query to search for")
    parser.add_argument("--location", help="Optional location used for all provided queries")
    parser.add_argument("--url", action="append", help="Specific URL to inspect and scrape")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    query_inputs = (
        [(query, args.location) for query in args.query]
        if args.query
        else DEFAULT_QUERIES
    )
    url_inputs = args.url or DEFAULT_URLS

    query_payloads = [await probe_query(query, location) for query, location in query_inputs]
    url_payloads = [await probe_url(url) for url in url_inputs]

    payload = {
        "queries": query_payloads,
        "urls": url_payloads,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    for item in query_payloads:
        _print_query_probe(item)
    for item in url_payloads:
        _print_url_probe(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
