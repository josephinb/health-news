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
    "Radiologie": [
        r"\b(radiolog|röntgen|roentgen|bildgebung|bildgebend)\b",
        r"\b(ct|mrt|mr-?tomographie|computertomographie|sonographie|ultraschall|nuklearmedizin|radiopharm)\b",
        r"\b(pet-?ct|pet/mr|angiographie|kontrastmittel)\b",
    ],
}

HEALTH_POS = re.compile(
    r"\b(gesundheit|medizin|krankheit|patient|arzt|ärzt|pflege|krankenhaus|klinik|"
    r"apotheke|pharma|arznei|impf|therap|diagnos|prävent|g-?ba|iqwig|pe[ij]|bfarm|"
    r"gkv|krankenkasse|versorg|leitlinie|infektion|epidemi|public health)\b",
    re.I
)
GENERAL_MEDIA = {"zeit.de","spiegel.de","tagesschau.de","faz.net","sueddeutsche.de","handelsblatt.com"}

DOMAIN_HINTS = {
    "medrxiv.org": ["Studie"], "pubmed.ncbi.nlm.nih.gov": ["Studie"],
    "g-ba.de": ["Gesetz","Versorgung"], "bundesgesundheitsministerium.de": ["Gesetz"],
    "anwendungen.pharmnet-bund.de": ["Wirtschaft"], "destatis.de": ["Wirtschaft"],
    "iqtig.org": ["Versorgung"], "divi.de": ["Versorgung"],
    "ema.europa.eu": ["Europa"], "efsa.europa.eu": ["Europa"],
    "edqm.eu": ["Europa"], "health.ec.europa.eu": ["Europa"],
    "who.int": ["Europa"], "digital.nhs.uk": ["Europa"], "gov.uk": ["Europa"],
    "hra.nhs.u
