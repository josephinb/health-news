# build_feed.py
import json, re, os
from datetime import datetime, timedelta, timezone
import feedparser
from urllib.parse import urlparse

NOW = datetime.now(timezone.utc)
WINDOW_DAYS = 14
CUTOFF = NOW - timedelta(days=WINDOW_DAYS)

# Schlüsselwörter für grobe Klassifikation
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

# Domain-Hinweise (überstimmen oft die KW)
DOMAIN_HINTS = {
    # DE
    "medrxiv.org": ["Studie"], "pubmed.ncbi.nlm.nih.gov": ["Studie"],
    "g-ba.de": ["Gesetz","Versorgung"],
    "bundesgesundheitsministerium.de": ["Gesetz"],
    "anwendungen.pharmnet-bund.de": ["Wirtschaft"],
    "destatis.de": ["Wirtschaft"],
    "iqtig.org": ["Versorgung"],
    "divi.de": ["Versorgung"],
    # EU/Europa
    "ema.europa.eu": ["Europa"],
    "ecdc.europa.eu": ["Europa"],
    "efsa.europa.eu": ["Europa"],
    "edqm.eu": ["Europa"],
    "ec.europa.eu": ["Europa"],
    "health.ec.europa.eu": ["Europa"],
    # WHO + UK-Öffentlich
    "who.int": ["Europa"],  # global, aber für EU-Relevanz ok
    "digital.nhs.uk": ["Europa"],
    "gov.uk": ["Europa"],
    "hra.nhs.uk": ["Europa"],
    "nihr.ac.uk": ["Europa"],
}

def clean(text):
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def summarize(txt, max_words=60):
    w = txt.split()
    return txt if len(w) <= max_words else " ".join(w[:max_words]) + " …"

def parse_time(e):
    for k in ["published_parsed", "updated_parsed"]:
        t = getattr(e, k, None)
        if t: return datetime(*t[:6], tzinfo=timezone.utc)
    return None

def to_iso(dt): return dt.astimezone(timezone.utc).isoformat()

def classify(title, summary, link):
    txt = f"{title} {summary}".lower()
    host = urlparse(link or "").hostname or ""
    cats = set(DOMAIN_HINTS.get(host, []))
    for cat, patterns in KW.items():
        if any(re.search(p, txt, flags=re.I) for p in patterns):
            cats.add(cat)
    # Fallback Heuristik
    if not cats and any(k in host for k in [
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
        title = clean(e.get("title",""))[:240]
        link = e.get("link","")
        summary_raw = clean(e.get("summary","") or e.get("description","") or title)
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

# Sortieren und Duplikate raus
items = dedupe(sorted(items, key=lambda x: x["published_at"], reverse=True))

# Schreiben
os.makedirs("public", exist_ok=True)
with open("public/health-news.json", "w", encoding="utf-8") as f:
    json.dump({
        "generated_at": to_iso(NOW),
        "window_days": WINDOW_DAYS,
        "count": len(items),
        "items": items
    }, f, ensure_ascii=False, indent=2)

print(f"Wrote {len(items)} items in last {WINDOW_DAYS} days")
