# build_feed.py
import json, re, os
from datetime import datetime, timedelta, timezone
import feedparser
from urllib.parse import urlparse

NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(days=3)

def clean(text):
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def summarize(txt, max_words=60):
    words = txt.split()
    return txt if len(words) <= max_words else " ".join(words[:max_words]) + " …"

def classify(link):
    host = urlparse(link or "").hostname or ""
    return "Studie" if any(k in host for k in ["medrxiv.org","pubmed.ncbi.nlm.nih.gov"]) else "News"

def to_iso(dt): return dt.astimezone(timezone.utc).isoformat()

def parse_time(e):
    for k in ["published_parsed","updated_parsed"]:
        t = getattr(e, k, None)
        if t: return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = (it["source_url"], it["title"].lower())
        if key in seen: continue
        seen.add(key); out.append(it)
    return out

feeds = [l.strip() for l in open("feeds.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
items = []

for url in feeds:
    d = feedparser.parse(url)
    source_name = d.feed.get("title", url)
    for e in d.entries:
        dt = parse_time(e)
        if not dt or dt < CUTOFF: continue
        title = clean(e.get("title",""))[:240]
        link = e.get("link","")
        summary_raw = clean(e.get("summary","") or e.get("description","") or title)
        items.append({
            "title": title,
            "summary_de": summarize(summary_raw, 60),
            "source_name": source_name,
            "source_url": link,
            "published_at": to_iso(dt),
            "type": classify(link)
        })

items = dedupe(sorted(items, key=lambda x: x["published_at"], reverse=True))
os.makedirs("public", exist_ok=True)
with open("public/health-news.json","w",encoding="utf-8") as f:
    json.dump({
        "generated_at": to_iso(NOW),
        "window_days": 3,
        "count": len(items),
        "items": items
    }, f, ensure_ascii=False, indent=2)
print(f"Wrote {len(items)} items")
