# build_feed.py
import json, re, os
from datetime import datetime, timedelta, timezone
import feedparser
import requests
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

NOW = datetime.now(timezone.utc)
WINDOW_DAYS = 14
CUTOFF = NOW - timedelta(days=WINDOW_DAYS)

# ---------- Heuristiken ----------
KW = {
    "Studie": [
        r"\b(randomisiert|kohorte|studie|review|metaanalyse|preprint|placebo)\b",
        r"\b(rct|trial|odds ratio|hazard ratio|p-?wert)\b",
    ],
    # NEU: Gesundheitspolitik ersetzt "Gesetz"
    "Gesundheitspolitik": [
        r"\b(gesundheitspolitik|gesundheitspolitisch)\b",
        r"\b(gesetz|gesetzesänderung|referentenentwurf|kabinettsbeschluss|verordnung)\b",
        r"\b(bundesrat|bundestag|sgb|richtlinie|verfahrensordnung|g-?ba|iqwig)\b",
        r"\b(gkv|gesetzliche\s+krankenversicherung|beitragssatz|festbetrag|erstattung|erweiterter\s*bewertungsausschuss)\b",
    ],
    "Wirtschaft": [
        r"\b(umsatz|kosten|ausgaben|finanz|beitragssatz|vergütung|budget|markt|preis|lieferengpass)\b",
        r"\b(investition|gewinn|verlust|prognose|erstattungsbetrag|finanzierung)\b",
    ],
    "Versorgung": [
        r"\b(versorgung|qualitätsbericht|qualitätsindikator|leitlinie|notfall|intensiv|pflege)\b",
        r"\b(krankenhausstruktur|ambulantisierung|wartezeit|kapazität|betten)\b",
    ],
    "Radiologie": [
        r"\b(radiolog\w+|imaging|bildgebung|bildgebend|diagnostikbildgebung)\b",
        r"\b(röntgen|roentgen|mammograf\w+)\b",
        r"\b(ct|pet-?ct|spect|cbct)\b",
        r"\b(mr[ -]?t|mri|mr-?tomograph\w+|magnetresonanztomograph\w+)\b",
        r"\b(ultraschall|sonograph\w+|pocus)\b",
        r"\b(nuklearmedizin|radiopharm\w*|radiotracer|szintigraph\w+)\b",
        r"\b(angiograph\w+|interventionelle\s*radiologie|ir)\b",
        r"\b(dicoms?|pacs|ris|kontrastmittel|gadolinium)\b",
        r"\b(strahlen(schutz|therapie)|dosis|dose management)\b",
        r"\b(teleradiologie|befundung|bildarchiv)\b",
    ],
    "Europa": [r"\b(europa|eu|european|europaweit|eu-weit)\b"],
}

# Health-Gate für Google-News/General Media
HEALTH_POS = re.compile(
    r"\b(gesundheit|medizin|krankheit|patient|arzt|ärzt|pflege|krankenhaus|klinik|"
    r"apotheke|pharma|arznei|impf|therap|diagnos|prävent|g-?ba|iqwig|pe[ij]|bfarm|"
    r"gkv|krankenkasse|versorg|leitlinie|infektion|epidemi|public health|"
    r"gesundheitspolitik|radiolog|bildgebung|imaging|mrt|ct|ultraschall|nuklearmedizin|pacs|dicom)\b",
    re.I
)

GENERAL_MEDIA = {"zeit.de","spiegel.de","tagesschau.de","faz.net","sueddeutsche.de","handelsblatt.com"}

# Domain-Hinweise → Gesundheitspolitik statt Gesetz
DOMAIN_HINTS = {
    "medrxiv.org": ["Studie"], "pubmed.ncbi.nlm.nih.gov": ["Studie"],
    "g-ba.de": ["Gesundheitspolitik","Versorgung"],
    "bundesgesundheitsministerium.de": ["Gesundheitspolitik"],
    "anwendungen.pharmnet-bund.de": ["Wirtschaft"],
    "destatis.de": ["Wirtschaft"],
    "iqtig.org": ["Versorgung"],
    "divi.de": ["Versorgung"],
    "gkv-spitzenverband.de": ["Gesundheitspolitik","Wirtschaft"],
    "vdek.com": ["Gesundheitspolitik"],
    "kbs.de": ["Gesundheitspolitik"],
    # Europa/UK
    "ema.europa.eu": ["Europa"], "efsa.europa.eu": ["Europa"],
    "edqm.eu": ["Europa"], "health.ec.europa.eu": ["Europa"],
    "digital.nhs.uk": ["Europa"], "gov.uk": ["Europa"],
    "hra.nhs.uk": ["Europa"], "nihr.ac.uk": ["Europa"],
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

def parse_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t: return None
    try:
        from time import struct_time
        if hasattr(t, "tm_year"):
            return datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, tzinfo=timezone.utc)
        return datetime(*t[:6], tzinfo=timezone.utc)
    except Exception:
        return None

def to_iso(dt): return dt.astimezone(timezone.utc).isoformat()

def looks_generic(title: str) -> bool:
    t = (title or "").strip()
    if not t: return True
    return any(pat.match(t) for pat in GENERIC_TITLE_PATTERNS)

def better_title(host: str, title: str, summary: str, source_name: str) -> str:
    if not looks_generic(title):
        return title
    s = (summary or "").strip()
    if s:
        first_sentence = re.split(r"(?<=[.!?])\s", s, maxsplit=1)[0]
        if len(first_sentence) >= 20:
            return first_sentence[:140]
    host_short = (host or "").split(":")[0]
    return f"{source_name or host_short}: Update"

def resolve_google(url: str) -> str:
    if not url or "news.google.com" not in url:
        return url
    try:
        r = requests.get(url, allow_redirects=True, timeout=8, headers={"User-Agent":"Mozilla/5.0"})
        return r.url or url
    except Exception:
        return url

def strip_tracking(url: str) -> str:
    try:
        p = urlparse(url)
        q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid","gclid","mc_cid","mc_eid"}]
        return urlunparse((p.scheme, p.netloc, p.path, p.params, urlencode(q), ""))
    except Exception:
        return url

def classify(title, summary, link):
    txt = f"{title} {summary}".lower()
    host = norm_host(urlparse(link or "").hostname)
    cats = set()
    for suf, vals in DOMAIN_HINTS.items():
        if host and host.endswith(suf): cats.update(vals)
    for cat, patterns in KW.items():
        if any(re.search(p, txt, flags=re.I) for p in patterns): cats.add(cat)
    if not cats and any(k in (host or "") for k in ["aerzteblatt.de","pharmazeutische-zeitung.de","vdek.com","gkv-spitzenverband.de","kbs.de"]):
        cats.add("Wirtschaft")
    # Reihenfolge: Politik klar getrennt von Wirtschaft
    order = ["Gesundheitspolitik","Studie","Radiologie","Versorgung","Wirtschaft","Europa"]
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

# ---------- Pipeline ----------
feeds = [l.strip() for l in open("feeds.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
items = []

for url in feeds:
    d = feedparser.parse(url)
    source_name = d.feed.get("title", url)
    for e in d.entries:
        dt = parse_time(e)
        if not dt or dt < CUTOFF: continue

        raw_title = clean(e.get("title",""))[:240]
        raw_link = e.get("link","")
        is_google_news = "news.google.com" in (raw_link or "")
        link = strip_tracking(resolve_google(raw_link))

        summary_raw = clean(e.get("summary","") or e.get("description","") or raw_title)
        host = norm_host(urlparse(link or "").hostname or "")
        title = better_title(host, raw_title, summary_raw, source_name)[:240]

        # Health-Gate für Google-News + General Media
        haystack = f"{title} {summary_raw}"
        if is_google_news or host in GENERAL_MEDIA:
            if not HEALTH_POS.search(haystack):
                continue

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
