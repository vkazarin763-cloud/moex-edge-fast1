"""Free/public-source scout. Search results are leads, never profitability evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MARKET_QUERIES = {
    "equities": '("equity trading" OR "stock trading") strategy backtest',
    "futures": '("futures trading" OR "commodity futures" OR "index futures") strategy backtest',
    "options": '("options trading" OR "option strategy" OR "option spreads") backtest',
}
USER_AGENT = "MOEX-EDGE-External-Strategy-Research/0.2 (public metadata discovery)"

MARKET_EVIDENCE = {
    "equities": re.compile(r"\\b(equit(y|ies)|stock(s)?|share(s)?|equity index|ticker|NYSE|NASDAQ|S&P ?500|SPY|QQQ)\\b", re.I),
    "futures": re.compile(r"\\b(future(s)?|FORTS|CME|E-mini|ES1!?|NQ1!?|CL1!?|GC1!?)\\b", re.I),
    "options": re.compile(r"\\b(option(s)?|call(s)?|put(s)?|strike(s)?|expiry|expir(y|ation)|implied volatility|option chain)\\b", re.I),
}
INFRA_TERMS = re.compile(r"\\b(framework|backtesting engine|backtest engine|API|SDK|screener|scanner|data provider|library|platform|toolkit|tutorial|course|textbook|chapter)\\b", re.I)
STRATEGY_TERMS = re.compile(r"\\b(strategy|trading system|entry signal|exit signal|mean.reversion|momentum|breakout|reversal|trend.following)\\b", re.I)

def fetch_json(url: str, *, timeout: int = 15, opener=urllib.request.urlopen):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json, application/json"})
    with opener(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} for {urllib.parse.urlsplit(url).netloc}")
        return json.loads(response.read().decode("utf-8"))

def _market_evidence(text: str) -> list[str]:
    return [market for market, pattern in MARKET_EVIDENCE.items() if pattern.search(text or "")]

def _candidate_type(text: str, source_type: str) -> str:
    if source_type == "crossref_publication":
        return "RESEARCH_PUBLICATION"
    if INFRA_TERMS.search(text or "") and not STRATEGY_TERMS.search(text or ""):
        return "INFRASTRUCTURE_OR_EDUCATION"
    if STRATEGY_TERMS.search(text or ""):
        return "POSSIBLE_STRATEGY_IMPLEMENTATION"
    return "UNCLASSIFIED_SOURCE"

def _base_record(source_type: str, title: str, url: str, description: str = "", **extra):
    evidence_text = f"{title} {description}"
    markets = _market_evidence(evidence_text)
    candidate_type = _candidate_type(evidence_text, source_type)
    stable = hashlib.sha256(url.rstrip("/").lower().encode("utf-8")).hexdigest()[:16]
    return {
        "candidate_id": stable,
        "source_type": source_type,
        "title": title,
        "url": url,
        "description": description[:1000],
        "market_tags": markets,
        "market_evidence_text": evidence_text[:1200],
        "candidate_type": candidate_type,
        "query_market": extra.pop("query_market", None),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_version": None,
        "source_version_status": "NOT_PINNED_REQUIRES_COMMIT_OR_DOI_VERSION",
        "evidence_status": "SOURCE_LEAD_ONLY_RULES_NOT_REVIEWED",
        **extra,
    }

def _github_items(query: str, limit: int, fetcher, query_market: str):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": limit})
    payload = fetcher(url)
    items = payload.get("items", []) if isinstance(payload, dict) else []
    results = []
    for item in items:
        if not isinstance(item, dict) or not item.get("html_url"):
            continue
        license_info = item.get("license") or {}
        description = (item.get("description") or "")[:1000]
        results.append(_base_record(
            "github_repository", item.get("full_name") or item.get("name") or "Untitled repository",
            item["html_url"], description, query_market=query_market,
            author=(item.get("owner") or {}).get("login"), updated_at=item.get("updated_at"),
            pushed_at=item.get("pushed_at"), stars=item.get("stargazers_count"),
            topics=item.get("topics") or [],
            license=license_info.get("spdx_id") or license_info.get("name"),
            license_status="DECLARED" if license_info.get("spdx_id") else "UNKNOWN_REQUIRES_REVIEW",
        ))
    return results

def _crossref_items(query: str, limit: int, fetcher, query_market: str):
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
        results.append(_base_record(
            "crossref_publication", title, item["URL"], query_market=query_market,
            doi=item.get("DOI"), author=author or None,
            publication_year=date_parts[0] if date_parts else None,
            publication_type=item.get("type"), container_title=(item.get("container-title") or [None])[0],
            license=None, license_status="UNKNOWN_REQUIRES_REVIEW",
        ))
    return results

def discover(*, limit: int = 5, fetcher=fetch_json, pause_seconds: float = 1.0):
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    candidates, errors = [], []
    for query_market, query in MARKET_QUERIES.items():
        for source_name, collector in (("github", _github_items), ("crossref", _crossref_items)):
            try:
                candidates.extend(collector(query, limit, fetcher, query_market))
            except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
                errors.append({"market_query": query_market, "source": source_name, "error": str(exc)[:300]})
            if pause_seconds:
                time.sleep(pause_seconds)
    seen, unique = set(), []
    for candidate in candidates:
        key = candidate["url"].rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return {
        "schema_version": "1.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "SOURCE_DISCOVERY_COMPLETED" if unique else "NO_SOURCES_FOUND",
        "mode": "METADATA_ONLY_NO_MARKET_DATA_NO_SIGNALS_NO_BACKTEST",
        "markets": list(MARKET_QUERIES),
        "candidate_count": len(unique),
        "candidates": unique,
        "errors": errors,
        "limitations": [
            "query_market records the search that found a result; it is not an asset-class label.",
            "market_tags require explicit instrument or asset-class evidence in returned title/description; missing evidence remains untagged.",
            "Repository metadata is not a README/code review; candidate_type is preliminary and may contain false positives.",
            "Exact entry, exit, invalidation, timeframe, parameters and execution assumptions have not been extracted.",
            "Source-reported performance is not independently reproduced and is never MOEX performance evidence.",
            "Source version and license require review before any code reuse.",
            "No market candles, broker APIs, accounts, orders, signals or backtests are accessed.",
        ],
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default="external_strategy_sources.json")
    args = parser.parse_args(argv)
    report = discover(limit=args.limit)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    print(f"{report['status']}: {report['candidate_count']} unique public source leads; {len(report['errors'])} source errors")
    return 0 if report["candidate_count"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
