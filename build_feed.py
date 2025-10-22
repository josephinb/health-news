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
    "Europa": [r"\b(europa|eu|european|europaweit|eu-weit)\b"],
}

# Health-Positivliste (muss matchen für Google-News & General-Media)
HEALTH_POS = re.compile(
    r"\b("
    r"gesundheit|medizin|krankheit|patient|arzt|ärzt|pflege|krankenhaus|klinik|"
    r"apotheke|pharma|arznei|impf|therap|diagnos|prävent|g-?ba|iqwig|pe[ij]|bfarm|"
    r"gkv|krankenkasse|versorg|leitlinie|infektion|epidemi|public health"
    r")\b",
    re.I
)

# Allgemeine Medien-Domains: nur behalten, wenn HEALTH_POS greift
GENERAL_MEDIA = {
    "zeit.de", "spiegel.de", "tagesschau.de", "faz.net", "sueddeutsche.de",
    "handelsblatt.com"
}

# Domain-Hinweise (Suffix-Matching)
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
    "efsa.europa.eu": ["Europa"],
    "edqm.eu": ["Europa"],
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

# ---------- Utils ----------
def norm_host(h: str) -> str:
    h = (h or "").lower()
    return h[4:] if h.startswith("www.") else h

def clean(text: str) -> str:
    if not text: return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def summarize(txt: str, m
