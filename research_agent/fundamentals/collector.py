"""Free, read-only discovery of MOEX corporate-report metadata.

This collector deliberately does not call paid CCI financial-statement datasets,
Finam, broker endpoints, or AI services. It discovers public report metadata,
preserves source rows verbatim, and never treats a reporting-period end as a
publication timestamp.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ISS = "https://iss.moex.com/iss"
OUT = Path("research_agent/fundamentals/data")
UNIVERSE = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]


class FundamentalsSourceError(RuntimeError):
    pass


def _request_json(url: str, timeout: int = 25, retries: int = 3) -> dict:
    last_error = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": "MOEX-EDGE-Fundamentals-Research/1.0"})
            with urlopen(req, timeout=timeout) as response:
                if response.status != 200:
                    raise FundamentalsSourceError(f"HTTP {response.status}: {url}")
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload, dict):
                    raise FundamentalsSourceError("MOEX ISS returned a non-object JSON payload")
                return payload
        except HTTPError as exc:
            # Do not retry access-denied responses; report them as a source limitation.
            if exc.code in (401, 403, 404):
                raise FundamentalsSourceError(f"MOEX ISS access/status {exc.code}: {url}") from exc
            last_error = exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt + 1 < retries:
            time.sleep(min(2 ** attempt, 4))
    raise FundamentalsSourceError(f"MOEX ISS request failed: {last_error}") from last_error


def _blocks(payload: dict) -> dict[str, list[dict]]:
    """Convert MOEX's standard {block: {columns, data}} form into row objects."""
    result = {}
    for name, value in payload.items():
        if not isinstance(value, dict):
            continue
        columns, rows = value.get("columns"), value.get("data")
        if isinstance(columns, list) and isinstance(rows, list):
            result[name] = [
                {str(columns[i]): row[i] for i in range(min(len(columns), len(row)))}
                for row in rows if isinstance(row, list)
            ]
    return result


def _first(row: dict, candidates: tuple[str, ...]):
    lowered = {str(k).lower(): v for k, v in row.items()}
    for key in candidates:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def normalize_report(row: dict) -> dict:
    """Keep raw metadata and expose only explicit source fields; no inferred dates."""
    published = _first(row, (
        "publish_date", "published_at", "publication_date", "disclosure_date",
        "date", "event_date", "created_at", "report_date",
    ))
    period_end = _first(row, (
        "period_end", "report_period_end", "period", "reporting_period",
        "end_date", "date_end",
    ))
    return {
        "company_id": _first(row, ("basis_company_id", "company_id", "issuer_id")),
        "ticker": _first(row, ("secid", "ticker", "security", "ticker_code")),
        "report_type": _first(row, ("report_type", "type", "document_type", "name", "title")),
        "publication_timestamp": published,
        "reporting_period_end": period_end,
        "document_url": _first(row, ("url", "document_url", "file_url", "href", "link")),
        "raw": row,
    }


def collect(getter=_request_json) -> dict:
    endpoints = {
        "companies": f"{ISS}/cci/info/companies.json",
        "reports": f"{ISS}/cci/reporting/corp-info/reports.json",
    }
    raw, blocks, errors = {}, {}, {}
    for key, url in endpoints.items():
        try:
            raw[key] = getter(url)
            blocks[key] = _blocks(raw[key])
        except Exception as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"

    company_rows = [row for rows in blocks.get("companies", {}).values() for row in rows]
    report_rows = [row for rows in blocks.get("reports", {}).values() for row in rows]
    normalized = [normalize_report(row) for row in report_rows]

    # Keep all source rows, including rows that cannot yet be linked to a ticker.
    # Never guess ticker/company matches from fuzzy company-name similarity.
    by_ticker = {ticker: [] for ticker in UNIVERSE}
    unmatched = []
    for item in normalized:
        ticker = str(item["ticker"] or "").upper()
        if ticker in by_ticker:
            by_ticker[ticker].append(item)
        else:
            unmatched.append(item)

    return {
        "schema_version": 1,
        "collector": "moex_iss_cci_public_report_metadata",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "universe": UNIVERSE,
        "source_endpoints": endpoints,
        "source_access": {
            "companies": "ok" if "companies" in raw else "unavailable",
            "reports": "ok" if "reports" in raw else "unavailable",
            "errors": errors,
        },
        "coverage": {
            "universe_size": len(UNIVERSE),
            "company_reference_rows": len(company_rows),
            "report_rows": len(normalized),
            "tickers_with_direct_report_mapping": sum(bool(v) for v in by_ticker.values()),
            "unmatched_report_rows": len(unmatched),
        },
        "reports_by_ticker": by_ticker,
        "unmatched_reports": unmatched,
        "company_reference_raw": company_rows,
        "limitations": [
            "This free collector retrieves report-discovery metadata only; it does not claim access to paid MOEX CCI IFRS/RAS structured financial datasets.",
            "A report period end is not a publication date. Historical signal tests must use an explicit publication timestamp from the source.",
            "Ticker/company links are populated only when the source row explicitly supplies a ticker/security identifier; fuzzy name matching is prohibited.",
            "No financial metric is inferred from document titles or unparsed PDF text.",
            "If source access is denied or a dataset is subscription-only, the report records the limitation instead of substituting invented values.",
            "Restatements and historical document versions require separate version tracking before point-in-time backtests."
        ],
    }


def main() -> int:
    result = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = OUT / f"moex-report-discovery-{stamp}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = OUT / "latest.json"
    latest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(path), "coverage": result["coverage"],
                      "source_access": result["source_access"]}, ensure_ascii=False))
    # A source failure is a failed collection, not an empty successful dataset.
    return 0 if any(v == "ok" for v in result["source_access"].values() if isinstance(v, str)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
