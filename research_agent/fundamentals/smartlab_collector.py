"""Read-only Smart-Lab Telegram/news discovery for MOEX fundamentals research.

No Telegram bot token or account session is used. Telegram posts are leads,
not authoritative financial disclosures. Original issuer documents must be
verified separately before extracting financial facts.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

CHANNEL = "newssmartlab"
FEED_URL = f"https://t.me/s/{CHANNEL}"
OUT = Path("research_agent/fundamentals/data")
MAX_PAGES = 5
MAX_ARTICLES = 20
UNIVERSE = [
    "AFKS", "AFLT", "ALRS", "BSPB", "CBOM", "CHMF", "CNRU", "DOMRF",
    "ENPG", "FLOT", "GAZP", "GMKN", "HEAD", "IRAO", "LKOH", "MAGN",
    "MDMG", "MOEX", "MTSS", "NLMK", "NVTK", "OZON", "PHOR", "PLZL",
    "POSI", "RAGR", "RENI", "ROSN", "RTKM", "RUAL", "SBER", "SBERP",
    "SNGS", "SNGSP", "SVCB", "T", "TATN", "TATNP", "TRNFP", "UGLD",
    "VKCO", "VTBR", "X5", "YDEX",
]
TOPIC_TERMS = {
    "financial_report": ("отчет", "отчёт", "отчетность", "отчётность", "мсфо", "рсбу",
                         "финансовые результаты", "годовые результаты", "квартальные результаты"),
    "revenue_profit": ("выручк", "чистая прибыль", "операционная прибыль", "ebitda"),
    "dividends": ("дивиденд", "рекомендация дивиденд", "дата отсечки"),
    "debt": ("чистый долг", "долговая нагрузка", "долг/ebitda", "net debt"),
    "guidance": ("прогноз", "guidance", "прогнозирует", "ожидает по итогам"),
    "ownership_change": ("инсайдер", "право распоряжаться", "доля до", "доля после", "приобрел право", "утратил право"),
}
DOCUMENT_HINTS = ("отчет", "отчёт", "отчетность", "отчётность", "мсфо", "рсбу",
                  "раскрытие", "disclosure", "report", "results", ".pdf", ".xlsx", ".xls")


class FeedError(RuntimeError):
    pass


def _fetch_html(url, timeout=25, retries=3):
    error = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; MOEX-EDGE-Research/1.1)",
                "Accept": "text/html",
            })
            with urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    raise FeedError(f"HTTP {response.status} for {url}")
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            if exc.code in (401, 403, 404):
                raise FeedError(f"Public page unavailable: HTTP {exc.code} ({url})") from exc
            error = exc
        except (URLError, TimeoutError, OSError) as exc:
            error = exc
        if attempt + 1 < retries:
            time.sleep(min(2 ** attempt, 4))
    raise FeedError(f"Request failed for {url}: {error}") from error


class PostParser(HTMLParser):
    """Extract one Telegram public-preview page, preserving message links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = []
        self.current = None
        self.wrapper_depth = 0
        self.text_depth = 0
        self.capture = False
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        if tag == "div" and "tgme_widget_message_wrap" in classes:
            self.current = {
                "post_id": attrs.get("data-post"),
                "published_at": None,
                "post_url": None,
                "parts": [],
                "links": [],
            }
            self.wrapper_depth = 1
            return
        if self.current is None:
            return
        if tag == "div":
            self.wrapper_depth += 1
            if "tgme_widget_message_text" in classes:
                self.text_depth += 1
                self.capture = True
        elif tag == "time" and attrs.get("datetime"):
            self.current["published_at"] = attrs["datetime"]
        elif tag == "a":
            href = attrs.get("href")
            if "tgme_widget_message_date" in classes:
                self.current["post_url"] = href
            elif self.capture and href:
                self.anchor = {"url": href, "text": []}

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag == "a" and self.anchor is not None:
            self.current["links"].append({
                "url": self.anchor["url"],
                "text": " ".join(self.anchor["text"]).strip(),
            })
            self.anchor = None
        if tag != "div":
            return
        if self.text_depth:
            self.text_depth -= 1
            if self.text_depth == 0:
                self.capture = False
        self.wrapper_depth -= 1
        if self.wrapper_depth <= 0:
            post = self.current
            post["text"] = " ".join(post.pop("parts"))
            post["post_url"] = post["post_url"] or (
                f"https://t.me/{post['post_id']}" if post["post_id"] else None
            )
            self.posts.append(post)
            self.current = None
            self.wrapper_depth = self.text_depth = 0
            self.capture = False
            self.anchor = None

    def handle_data(self, data):
        if self.current is None or not self.capture:
            return
        value = " ".join(data.split())
        if value:
            self.current["parts"].append(value)
            if self.anchor is not None:
                self.anchor["text"].append(value)


class ArticleParser(HTMLParser):
    """Extract public article title/description and outbound link evidence."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.description = None
        self.links = []
        self.current_link = None
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag == "meta" and attrs.get("name", "").lower() in ("description", "og:description"):
            self.description = attrs.get("content")
        elif tag == "meta" and attrs.get("property") == "og:title":
            if not self.title and attrs.get("content"):
                self.title.append(attrs["content"])
        elif tag == "a" and attrs.get("href"):
            self.current_link = {"url": attrs["href"], "text": []}

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "a" and self.current_link is not None:
            self.links.append({
                "url": self.current_link["url"],
                "text": " ".join(self.current_link["text"]).strip(),
            })
            self.current_link = None

    def handle_data(self, data):
        value = " ".join(data.split())
        if not value:
            return
        if self.in_title:
            self.title.append(value)
        if self.current_link is not None:
            self.current_link["text"].append(value)


def matched_tickers(text):
    found = []
    for ticker in UNIVERSE:
        escaped = re.escape(ticker)
        patterns = [
            rf"(?<![A-Za-z0-9_])#{escaped}(?![A-Za-z0-9_])",
            rf"(?<![A-Za-z0-9_])\${escaped}(?![A-Za-z0-9_])",
        ]
        if len(ticker) >= 3:
            patterns.append(
                rf"(?<![A-Za-zА-Яа-яЁё0-9_]){escaped}(?![A-Za-zА-Яа-яЁё0-9_])"
            )
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            found.append(ticker)
    return sorted(found)


def topic_tags(text):
    lower = text.lower()
    return sorted(tag for tag, terms in TOPIC_TERMS.items()
                  if any(term in lower for term in terms))


def normalize_post(post):
    text = post.get("text", "")
    tags = topic_tags(text)
    return {
        "channel": f"@{CHANNEL}",
        "post_id": post.get("post_id"),
        "published_at": post.get("published_at"),
        "post_url": post.get("post_url"),
        "tickers": matched_tickers(text),
        "topic_tags": tags,
        "reporting_related": bool(set(tags) & {"financial_report", "revenue_profit", "dividends"}),
        "text": text,
        "linked_articles": [
            link for link in post.get("links", [])
            if urlparse(link.get("url", "")).netloc.lower().endswith("smartlab.news")
        ],
        "verification_status": "unverified_news_lead",
        "primary_document_url": None,
    }


def _post_number(post):
    value = post.get("post_id") or ""
    match = re.search(r"/(\d+)$", value)
    if match:
        return int(match.group(1))
    url_match = re.search(r"/(\d+)(?:\?|$)", post.get("post_url") or "")
    return int(url_match.group(1)) if url_match else None


def _resolve_smartlab_redirect(url):
    """Unwrap Smart-Lab redirect links without following arbitrary destinations."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"smart-lab.ru", "www.smart-lab.ru"} or parsed.path != "/r.php":
        return url
    target = parse_qs(parsed.query).get("u", [None])[0]
    if not target:
        return url
    target_parsed = urlparse(target)
    if target_parsed.scheme != "https" or not target_parsed.hostname:
        return url
    return target


def _source_domain_classification(url):
    host = (urlparse(url).hostname or "").lower()
    if host == "e-disclosure.ru" or host.endswith(".e-disclosure.ru"):
        return "known_disclosure_operator_domain"
    if host == "cbr.ru" or host.endswith(".cbr.ru"):
        return "known_regulator_domain"
    return "unverified_domain"


def _article_details(url, fetcher):
    try:
        parser = ArticleParser()
        parser.feed(fetcher(url))
        parser.close()
    except FeedError as exc:
        return {"url": url, "fetch_status": "unavailable", "error": str(exc),
                "title": None, "description": None, "candidate_primary_document_links": []}
    host = (urlparse(url).hostname or "").lower()
    outbound = []
    candidates = []
    for link in parser.links:
        target = link.get("url", "")
        parsed = urlparse(target)
        target_host = (parsed.hostname or "").lower()
        if not target_host or target_host == host or target_host.endswith(".smartlab.news"):
            continue
        resolved = _resolve_smartlab_redirect(target)
        item = {
            "url": target,
            "resolved_url": resolved,
            "anchor_text": link.get("text", ""),
            "source_domain_classification": _source_domain_classification(resolved),
            "content_verification_status": "not_fetched",
        }
        outbound.append(item)
        evidence = (target + " " + resolved + " " + link.get("text", "")).lower()
        if any(hint in evidence for hint in DOCUMENT_HINTS):
            candidates.append(item)
    return {
        "url": url,
        "fetch_status": "ok",
        "title": " ".join(parser.title).strip() or None,
        "description": parser.description,
        "outbound_links": outbound[:30],
        "candidate_primary_document_links": candidates[:20],
        "verification_status": "article_not_primary_source",
    }


def collect(fetcher=_fetch_html, max_pages=MAX_PAGES, max_articles=MAX_ARTICLES):
    all_posts = []
    seen_ids = set()
    page_urls = []
    cursor = None
    pages_fetched = 0
    for _ in range(max_pages):
        page_url = FEED_URL if cursor is None else f"{FEED_URL}?before={cursor}"
        html = fetcher(page_url)
        parser = PostParser()
        parser.feed(html)
        parser.close()
        page_urls.append(page_url)
        pages_fetched += 1
        new_posts = []
        for post in parser.posts:
            key = post.get("post_id") or post.get("post_url")
            if key and key not in seen_ids:
                seen_ids.add(key)
                new_posts.append(post)
        all_posts.extend(new_posts)
        numbers = [number for number in (_post_number(post) for post in new_posts)
                   if number is not None]
        if not numbers or len(new_posts) == 0:
            break
        next_cursor = min(numbers) - 1
        if cursor is not None and next_cursor >= cursor:
            break
        cursor = next_cursor
        if len(parser.posts) == 0:
            break

    normalized = [normalize_post(post) for post in all_posts]
    matched = [post for post in normalized if post["tickers"]]
    article_urls = []
    for post in matched:
        for link in post["linked_articles"]:
            url = link["url"]
            if url not in article_urls:
                article_urls.append(url)
    articles = [_article_details(url, fetcher)
                for url in article_urls[:max_articles]]
    article_by_url = {article["url"]: article for article in articles}
    for post in matched:
        post["article_details"] = [
            article_by_url[link["url"]] for link in post["linked_articles"]
            if link["url"] in article_by_url
        ]

    return {
        "schema_version": 2,
        "collector": "telegram_public_preview_smartlab",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "channel": f"@{CHANNEL}",
            "url": FEED_URL,
            "access_method": "public_web_preview_no_auth",
        },
        "pagination": {
            "pages_fetched": pages_fetched,
            "max_pages": max_pages,
            "page_urls": page_urls,
            "unique_posts_seen": len(all_posts),
        },
        "universe_size": len(UNIVERSE),
        "preview_posts_seen": len(all_posts),
        "ticker_matched_posts": len(matched),
        "reporting_related_posts": sum(post["reporting_related"] for post in matched),
        "linked_articles_checked": len(articles),
        "articles_with_candidate_document_links": sum(
            bool(article.get("candidate_primary_document_links")) for article in articles
        ),
        "posts": matched,
        "articles": articles,
        "limitations": [
            "Telegram public preview pagination is best-effort and not a guaranteed complete archive.",
            "Ticker matching uses explicit tags/tokens only; company-name fuzzy matching is disabled.",
            "Smart-Lab article pages and outbound links are discovery evidence, not proof of issuer authenticity.",
            "Candidate links are unwrapped and classified by known disclosure-operator/regulator domain; page content and issuer identity are not verified by this collector.",
            "Missing publication timestamps and document fields remain null.",
            "No bot token, account session, paid API, Finam AI Screener, or broker endpoint is used.",
        ],
    }


def main():
    result = collect()
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    (OUT / f"smartlab-news-{stamp}.json").write_text(payload, encoding="utf-8")
    (OUT / "smartlab-latest.json").write_text(payload, encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "pagination", "ticker_matched_posts", "reporting_related_posts",
        "linked_articles_checked", "articles_with_candidate_document_links"
    )}, ensure_ascii=False))
    return 0 if result["preview_posts_seen"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
