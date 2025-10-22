# build_feed.py
import json, re, os
from datetime import datetime, timedelta, timezone
import feedparser
from urllib.parse import urlparse

NOW = datetime.now(timezone.utc)
WINDOW_DAYS = 30
CUTOFF = NOW - timedelta(days=WINDOW_DAYS)

KW = {
    "Studie": [
        r"\b(randomisiert|kohorte|studie|review|metaanalyse|preprint|placebo)\b",
        r"\b(rct|trial|odds ratio|hazard ratio|p-?wert)\b",
    ],
    "Gesetz": [
        r"\b(gesetz|gesetzesänderung|referentenentwurf|kabinettsbeschluss|verordnung)\b",
        r"\b(bundesrat|bundestag|sgb|richtlinie|beschluss des g\-ba|festbetrag|erstattung)\b",
    ],
    "Wirtschaft": [
        r"\b(umsatz|kosten|ausgaben|finanz|beitragssatz|vergütung|budget|markt|preis|lieferengpass)\b",
        r"\b(investition|gewinn|verlust|prognose|erstattungsbetrag)\b",
    ],
    "Versorgung": [
        r"\b(versorgung|qualitätsbericht|qualitätsindikator|leitlinie|notfall|intensiv|pflege)\b",
        r"\b(krankenhausstruktur|ambulantisierung|wartezeit|kapazität|betten)\b",
    ],
    "Europa": [
        r"\b(europa|eu|european|europaweit|eu-weit)\b"
    ],
}

DOMAIN_HINTS = {
    # DE
    "medrxiv.org": ["Studie"],
    "pubmed.ncbi.nlm.nih.gov": ["Studie"],
    "g-ba.de": ["Gesetz", "Versorgung"],
    "bundesgesundheitsministerium.de": ["Gesetz"],
    "anwendungen.pharmnet-bund.de": ["Wirtschaft"],
    "destatis.de": ["Wirtschaft"],
    "iqtig.org": ["Versorgung"],
    "divi.de": ["Versorgung"],
    # Europa
    "ema.europa.eu": ["Europa"],
    "ecdc.europa.eu": ["Europa"],
    "efsa.europa.eu": ["Europa"],
    "edqm.eu": ["Europa"],
    "ec.europa.eu": ["Europa"],          # Eurostat
    "health.ec.europa.eu": ["Europa"],
    # WHO + UK
    "who.int": ["Europa"],
    "digital.nhs.uk": ["Europa"],
    "gov.uk": ["Europa"],
    "hra.nhs.uk": ["Europa"],
    "nihr.ac.uk": ["Europa"],
}

GENERIC_TITLE_PATTERNS = [
    re.compile(r"^\s*dataset:?\s*updated\s*data\s*$", re.I),
    re.compile(r"^\s*updated\s*data\s*$", re.I),
    re.compile(r"^\s*news\s*$", re.I),
]

def norm_host(h: str) -> str:
    h = (h or "").lower()
    return h[4:] if h.startswith("www.") else h

def clean(text: str) -> str:
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def summarize(txt: str, max_words=60) -> str:
    w = txt.split()
    return txt if len(w) <= max_words else " ".join(w[:max_words]) + " …"

def parse_time(e):
    for k in ["published_parsed", "updated_parsed"]:
        t = getattr(e, k, None)
        if t: return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def to_iso(dt): return dt.astimezone(timezone.utc).isoformat()

def looks_generic(title: str) -> bool:
    t = (title or "").strip()
    if not t: return True
    return any(pat.match(t) for pat in GENERIC_TITLE_PATTERNS)

def better_title(host: str, title: str, summary: str, source_name: str) -> str:
    """
    Ersetzt generische Titel (z. B. Eurostat 'Dataset: updated data') durch
    eine sinnvollere Headline aus der Summary. Fallback mit Source-Präfix.
    """
    if not looks_generic(title):
        return title
    # bevorzugt ersten Satz aus der Summary
    s = (summary or "").strip()
    if s:
        first_sentence = re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0]
        if len(first_sentence) >= 20:
            return first_sentence[:140]
    # letzter Fallback
    host_short = host.split(":")[0]
    return f"{source_name or host_short}: Update"

def classify(title, summary, link):
    txt = f"{title} {summary}".lower()
    host = norm_host(urlparse(link or "").hostname)
    cats = set()
    for suf, vals in DOMAIN_HINTS.items():
        if host and host.endswith(suf):
            cats.update(vals)
    for cat, patterns in KW.items():
        if any(re.search(p, txt, flags=re.I) for p in patterns):
            cats.add(cat)
    if not cats and any(k in (host or "") for k in [
        "aerzteblatt.de","pharmazeutische-zeitung.de","vdek.com",
        "gkv-spitzenverband.de","kbs.de"
    ]):
        cats.add("Wirtschaft")
    order = ["Gesetz","Studie","Versorgung","Wirtschaft","Europa"]
    main = next((c for c in order if c in cats), "News")
    tags = sorted(cats - {main})
    return main, tags

def dedupe(items):
    seen, out = set(), []
    for it in items:
        key = (it["source_url"], it["title"].lower())
        if key in seen: continue
        seen.add(key); out.append(it)
    return out

# Feeds laden
feeds = [l.strip() for l in open("feeds.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
items = []

for url in feeds:
    d = feedparser.parse(url)
    source_name = d.feed.get("title", url)
    for e in d.entries:
        dt = parse_time(e)
        if not dt or dt < CUTOFF: continue
        raw_title = clean(e.get("title",""))[:240]
        link = e.get("link","")
        summary_raw = clean(e.get("summary","") or e.get("description","") or raw_title)
        host = norm_host(urlparse(link or "").hostname or "")
        title = better_title(host, raw_title, summary_raw, source_name)[:240]
        summary = summarize(summary_raw, 60)
        category, tags = classify(title, summary, link)
        items.append({
            "title": title,
            "summary_de": summary,
            "source_name": source_name,
            "source_url": link,
            "published_at": to_iso(dt),
            "category": category,
            "tags": tags,
            "type": "Studie" if category=="Studie" else "News"
        })

items = dedupe(sorted(items, key=lambda x: x["published_at"], reverse=True))

os.makedirs("public", exist_ok=True)
with open("public/health-news.json", "w", encoding="utf-8") as f:
    json.dump({
        "generated_at": to_iso(NOW),
        "window_days": WINDOW_DAYS,
        "count": len(items),
        "items": items
    }, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(items)} items in last {WINDOW_DAYS} days")
