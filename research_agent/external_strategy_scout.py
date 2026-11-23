"""Free/public-source smoke-test scout. Discovers source leads; never evaluates profitability."""
from __future__ import annotations
import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MARKET_QUERIES = {
    "equities": "systematic equity trading strategy backtest",
    "futures": "futures trading strategy backtest",
    "options": "options trading strategy backtest",
}
USER_AGENT = "MOEX-EDGE-External-Strategy-Research/0.1 (public metadata discovery)"

def fetch_json(url: str, *, timeout: int = 15, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json, application/json"})
    with opener(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {urllib.parse.urlsplit(url).netloc}")
        return json.loads(response.read().decode("utf-8"))

def _github_items(query: str, limit: int, fetcher):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": limit})
    payload = fetcher(url)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    results = []
    for item in items:
        if not isinstance(item, dict) or not item.get("html_url"):
            continue
        license_info = item.get("license") or {}
        results.append({
            "source_type": "github_repository",
            "title": item.get("full_name") or item.get("name") or "Untitled repository",
            "url": item["html_url"],
            "description": (item.get("description") or "")[:1000],
            "author": (item.get("owner") or {}).get("login"),
            "updated_at": item.get("updated_at"),
            "stars": item.get("stargazers_count"),
            "license": license_info.get("spdx_id") or license_info.get("name"),
            "license_status": "DECLARED" if license_info.get("spdx_id") else "UNKNOWN_REQUIRES_REVIEW",
            "market_tags": [],
            "evidence_status": "SOURCE_LEAD_ONLY_RULES_NOT_REVIEWED",
        })
    return results

def _crossref_items(query: str, limit: int, fetcher):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode({"query": query, "rows": limit, "select": "DOI,title,author,published,URL,type,container-title"})
    payload = fetcher(url)
    message = (payload.get("message") or {}) if isinstance(payload, dict) else {}
    results = []
    for item in message.get("items", []):
        if not isinstance(item, dict) or not item.get("URL"):
            continue
        authors = item.get("author") or []
        author = ", ".join(" ".join(filter(None, [a.get("given"), a.get("family")])) for a in authors[:3])
        title = (item.get("title") or ["Untitled work"])[0]
        date_parts = ((item.get("published") or {}).get("date-parts") or [[]])[0]
        results.append({
            "source_type": "crossref_publication",
            "title": title,
            "url": item["URL"],
            "doi": item.get("DOI"),
            "author": author or None,
            "publication_year": date_parts[0] if date_parts else None,
            "publication_type": item.get("type"),
            "license": None,
            "license_status": "UNKNOWN_REQUIRES_REVIEW",
            "market_tags": [],
            "evidence_status": "SOURCE_LEAD_ONLY_RULES_NOT_REVIEWED",
        })
    return results

def discover(*, limit: int = 5, fetcher=fetch_json, pause_seconds: float = 1.0):
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    candidates = []
    errors = []
    for market, query in MARKET_QUERIES.items():
        for source_name, collector in (("github", _github_items), ("crossref", _crossref_items)):
            try:
                found = collector(query, limit, fetcher)
                for candidate in found:
                    candidate["market_tags"] = [market]
                    candidates.append(candidate)
            except (OSError, RuntimeError, ValueError, KeyError) as exc:
                errors.append({"market": market, "source": source_name, "error": str(exc)[:300]})
            if pause_seconds:
                time.sleep(pause_seconds)
    seen = set()
    unique = []
    for candidate in candidates:
        key = candidate["url"].rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "SOURCE_DISCOVERY_COMPLETED" if unique else "NO_SOURCES_FOUND",
        "mode": "METADATA_ONLY_NO_MARKET_DATA_NO_SIGNALS_NO_BACKTEST",
        "markets": list(MARKET_QUERIES),
        "candidate_count": len(unique),
        "candidates": unique,
        "errors": errors,
        "limitations": [
            "Search results are leads, not endorsements or evidence of profitability.",
            "Exact strategy rules have not yet been extracted or independently reviewed.",
            "License metadata is incomplete and requires human/legal review before code reuse.",
            "No market candles, broker APIs, accounts, orders, signals or backtests are accessed.",
        ],
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default="external_strategy_sources.json")
    args = parser.parse_args(argv)
    report = discover(limit=args.limit)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {report['candidate_count']} unique public source leads; {len(report['errors'])} source errors")
    return 0 if report["candidate_count"] else 2

if __name__ == "__main__":
    raise SystemExit(main())