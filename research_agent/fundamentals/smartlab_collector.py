"""Read-only discovery of ticker-tagged Smart-Lab Telegram posts."""
from __future__ import annotations
import json, re, time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CHANNEL = "newssmartlab"
FEED_URL = f"https://t.me/s/{CHANNEL}"
OUT = Path("research_agent/fundamentals/data")
UNIVERSE = ["AFKS","AFLT","ALRS","BSPB","CBOM","CHMF","CNRU","DOMRF","ENPG","FLOT","GAZP","GMKN","HEAD","IRAO","LKOH","MAGN","MDMG","MOEX","MTSS","NLMK","NVTK","OZON","PHOR","PLZL","POSI","RAGR","RENI","ROSN","RTKM","RUAL","SBER","SBERP","SNGS","SNGSP","SVCB","T","TATN","TATNP","TRNFP","UGLD","VKCO","VTBR","X5","YDEX"]
REPORT_TERMS = ("отчет","отчёт","отчетность","отчётность","мсфо","рсбу","выручк","ebitda","чистая прибыль","операционная прибыль","финансовые результаты","денежный поток","долг","дивиденд","капитал","рентабельност")

class FeedError(RuntimeError): pass

class PostParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts=[]; self.current=None; self.wrapper_depth=0; self.text_depth=0; self.capture=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs); classes=set(a.get("class","").split())
        if tag=="div" and "tgme_widget_message_wrap" in classes:
            self.current={"post_id":a.get("data-post"),"published_at":None,"post_url":None,"parts":[]}
            self.wrapper_depth=1; return
        if self.current is None: return
        if tag=="div":
            self.wrapper_depth+=1
            if "tgme_widget_message_text" in classes:
                self.text_depth+=1; self.capture=True
        elif tag=="time" and a.get("datetime"): self.current["published_at"]=a["datetime"]
        elif tag=="a" and "tgme_widget_message_date" in classes: self.current["post_url"]=a.get("href")
    def handle_endtag(self, tag):
        if self.current is None or tag!="div": return
        if self.text_depth:
            self.text_depth-=1
            if self.text_depth==0: self.capture=False
        self.wrapper_depth-=1
        if self.wrapper_depth<=0:
            p=self.current; txt=" ".join(p.pop("parts"))
            p["text"]=txt
            p["post_url"]=p["post_url"] or (f"https://t.me/{p['post_id']}" if p["post_id"] else None)
            self.posts.append(p); self.current=None; self.wrapper_depth=self.text_depth=0; self.capture=False
    def handle_data(self, data):
        if self.current is not None and self.capture:
            s=" ".join(data.split())
            if s: self.current["parts"].append(s)

def _fetch_html(url=FEED_URL, timeout=25, retries=3):
    error=None
    for attempt in range(retries):
        try:
            req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; MOEX-EDGE-Research/1.0)","Accept":"text/html"})
            with urlopen(req,timeout=timeout) as response:
                if response.status!=200: raise FeedError(f"Telegram preview HTTP {response.status}")
                return response.read().decode("utf-8",errors="replace")
        except HTTPError as exc:
            if exc.code in (401,403,404): raise FeedError(f"Telegram public preview unavailable: HTTP {exc.code}") from exc
            error=exc
        except (URLError,TimeoutError,OSError) as exc: error=exc
        if attempt+1<retries: time.sleep(min(2**attempt,4))
    raise FeedError(f"Telegram preview request failed: {error}") from error

def matched_tickers(text):
    found=[]
    for ticker in UNIVERSE:
        e=re.escape(ticker)
        patterns=[r"(?<![A-Za-z0-9_])#"+e+r"(?![A-Za-z0-9_])",r"(?<![A-Za-z0-9_])\$"+e+r"(?![A-Za-z0-9_])"]
        if len(ticker)>=3: patterns.append(r"(?<![A-Za-zА-Яа-яЁё0-9_])"+e+r"(?![A-Za-zА-Яа-яЁё0-9_])")
        if any(re.search(p,text,re.IGNORECASE) for p in patterns): found.append(ticker)
    return sorted(found)

def normalize_post(post):
    txt=post.get("text",""); low=txt.lower(); tickers=matched_tickers(txt)
    return {"channel":f"@{CHANNEL}","post_id":post.get("post_id"),"published_at":post.get("published_at"),
      "post_url":post.get("post_url"),"tickers":tickers,
      "reporting_related":any(term in low for term in REPORT_TERMS),"text":txt,
      "verification_status":"unverified_news_lead","primary_document_url":None}

def collect(fetcher=_fetch_html):
    parser=PostParser(); parser.feed(fetcher()); parser.close()
    posts=[normalize_post(p) for p in parser.posts]
    matched=[p for p in posts if p["tickers"]]
    return {"schema_version":1,"collector":"telegram_public_preview_smartlab",
      "collected_at_utc":datetime.now(timezone.utc).isoformat(),
      "source":{"channel":f"@{CHANNEL}","url":FEED_URL,"access_method":"public_web_preview_no_auth"},
      "universe_size":len(UNIVERSE),"preview_posts_seen":len(posts),"ticker_matched_posts":len(matched),
      "reporting_related_posts":sum(p["reporting_related"] for p in matched),"posts":matched,
      "limitations":["Telegram public preview exposes only a recent slice, not a guaranteed complete archive.",
        "Posts are discovery leads, not verified financial statements or issuer disclosures.",
        "Only explicit ticker tags/tokens are mapped; issuer-name fuzzy matching is disabled.",
        "Publication timestamps are preserved as supplied; missing values remain null.",
        "No bot token, Telegram account session, paid API, Finam AI Screener, or broker endpoint is used."]}

def main():
    result=collect(); OUT.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    (OUT/f"smartlab-news-{stamp}.json").write_text(payload,encoding="utf-8")
    (OUT/"smartlab-latest.json").write_text(payload,encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("preview_posts_seen","ticker_matched_posts","reporting_related_posts")},ensure_ascii=False))
    return 0 if result["preview_posts_seen"]>0 else 1
if __name__=="__main__": raise SystemExit(main())
