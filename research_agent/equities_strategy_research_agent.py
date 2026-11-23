"""Autonomous public-source reader for equities strategies."""
from __future__ import annotations
import argparse, hashlib, json, re, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from research_agent.external_strategy_scout import discover, fetch_json, USER_AGENT

MAX_FILE_BYTES = 180_000
MAX_FILES_PER_REPO = 8
CODE_EXTENSIONS = (".py", ".ipynb", ".md", ".txt", ".pine")
RULE_PATTERNS = {
    "entry": re.compile(r"(?i)(entry|buy|long|enter|breakout|cross(?:es|over)?|signal.{0,30}(?:buy|long))"),
    "exit": re.compile(r"(?i)(exit|sell|close|stop.?loss|take.?profit|trailing stop)"),
    "timeframe": re.compile(r"(?i)\b(daily|weekly|hourly|minute|\d+\s*(?:min|minute|hour|day|week)s?)\b"),
    "indicators": re.compile(r"(?i)\b(ema|sma|rsi|macd|atr|adx|bollinger|donchian|ichimoku|vwap|stochastic)\b"),
    "execution": re.compile(r"(?i)(next.?open|market order|limit order|slippage|commission|transaction cost)"),
}
INFRA = re.compile(r"(?i)\b(backtesting engine|framework|data provider|broker api|screener|scanner|sdk|toolkit)\b")

def _request_text(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json, application/json, text/plain"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(MAX_FILE_BYTES + 1)
    return raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")

def _github_repo_parts(url: str):
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return (parts[0], parts[1]) if len(parts) >= 2 else None

def _read_github_source(url: str):
    parts = _github_repo_parts(url)
    if not parts:
        return "", []
    owner, repo = parts
    metadata = fetch_json(f"https://api.github.com/repos/{owner}/{repo}")
    branch = metadata.get("default_branch") or "main"
    chunks, paths = [], []
    try:
        readme = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/readme")
        if readme.get("download_url"):
            chunks.append(_request_text(readme["download_url"]))
    except Exception:
        pass
    try:
        tree = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(branch)}?recursive=1")
        files = [x for x in tree.get("tree", []) if x.get("type") == "blob" and str(x.get("path", "")).lower().endswith(CODE_EXTENSIONS)]
        files.sort(key=lambda x: (0 if any(k in x["path"].lower() for k in ("strategy", "signal", "trading", "backtest")) else 1, len(x["path"])))
        for item in files[:MAX_FILES_PER_REPO]:
            try:
                raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/" + urllib.parse.quote(item["path"])
                chunks.append(_request_text(raw_url))
                paths.append(item["path"])
            except Exception:
                continue
    except Exception:
        pass
    return "\n\n".join(chunks), paths

def _read_crossref_source(url: str):
    doi = url.rstrip("/").split("/")[-1]
    if not doi or not url.startswith("https://doi.org/"):
        return "", []
    item = fetch_json("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="")).get("message", {})
    abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", "") or "")
    return " ".join(item.get("title", []) or []) + "\n" + abstract, ["Crossref metadata/abstract"]

def _extract(text: str) -> dict:
    evidence = {}
    for field, pattern in RULE_PATTERNS.items():
        matches = []
        for line in text.splitlines():
            if pattern.search(line):
                clean = re.sub(r"\s+", " ", line).strip()
                if clean and clean not in matches:
                    matches.append(clean[:280])
                if len(matches) >= 12:
                    break
        evidence[field] = matches
    return evidence

def inspect_candidate(candidate: dict) -> dict:
    url = candidate.get("url", "")
    content, inspected_paths, errors = "", [], []
    try:
        if candidate.get("source_type") == "github_repository":
            content, inspected_paths = _read_github_source(url)
        elif candidate.get("source_type") == "crossref_publication":
            content, inspected_paths = _read_crossref_source(url)
        else:
            errors.append("Unsupported source type")
    except Exception as exc:
        errors.append(str(exc)[:300])
    rules = _extract(content)
    required = ("entry", "exit", "timeframe", "indicators")
    complete = all(rules.get(k) for k in required)
    infrastructure = bool(INFRA.search((candidate.get("title") or "") + "\n" + content[:5000]))
    if errors or not content:
        status = "SOURCE_READ_FAILED"
    elif infrastructure and not complete:
        status = "REJECTED_INFRASTRUCTURE_OR_EDUCATION"
    elif complete:
        status = "RULE_EVIDENCE_EXTRACTED_REQUIRES_HUMAN_REVIEW"
    else:
        status = "INCOMPLETE_RULES_NEED_REVIEW"
    return {
        **candidate, "inspection_status": status,
        "inspected_at_utc": datetime.now(timezone.utc).isoformat(),
        "inspected_files": inspected_paths, "source_text_chars": len(content),
        "rule_evidence": rules, "missing_rule_fields": [k for k in required if not rules.get(k)],
        "inspection_errors": errors,
        "source_content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
        "profitability_claim": "NOT_ASSESSED", "moex_test_status": "NOT_TESTED",
        "promotion_status": "NOT_ELIGIBLE",
    }

def run(limit: int = 5) -> dict:
    leads = discover(limit=limit)
    reviewed = [inspect_candidate(item) for item in leads.get("candidates", [])]
    counts = {}
    for item in reviewed:
        counts[item["inspection_status"]] = counts.get(item["inspection_status"], 0) + 1
    return {
        "schema_version": "1.0", "agent": "MOEX EDGE Equities Public-Source Research Agent",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {"market": "equities", "universe": "MOEX fixed 44; testing is a separate stage"},
        "status": "SOURCE_INSPECTION_COMPLETED" if reviewed else leads.get("status"),
        "candidate_count": len(reviewed), "status_counts": counts,
        "discovery_errors": leads.get("errors", []), "candidates": reviewed,
        "safety": [
            "Public source text only; no broker credentials, accounts, orders, or live signals.",
            "Rule extraction is evidence collection, not an AI verdict or profitability evidence.",
            "All candidates remain NOT_ELIGIBLE until independent MOEX testing and review.",
            "Source-reported performance is not accepted as independently reproduced evidence.",
        ],
    }

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--output", default="equities_strategy_research.json")
    args = parser.parse_args(argv)
    report = run(args.limit)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {report['candidate_count']} sources inspected; statuses={report['status_counts']}")
    return 0 if report["candidate_count"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
