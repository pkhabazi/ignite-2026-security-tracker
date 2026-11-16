"""Shared definitions for render.py and check.py.

One place for the areas, the statuses, the field list and the voice rules,
so the renderer and the checker can never disagree.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "announcements.yaml"
TEMPLATES = ROOT / "templates"
README = ROOT / "README.md"
INDEX = ROOT / "docs" / "index.html"

TITLE = "Ignite 2026 security tracker"

# Order here is the order of the sections in README.md and docs/index.html.
AREAS = [
    "Agentic SOC and Security Copilot",
    "Project Perception and MDASH",
    "Microsoft Sentinel",
    "Defender XDR",
    "Defender for Endpoint, Identity, Office, Cloud Apps",
    "Defender for Cloud",
    "Security for AI",
    "Entra",
    "Purview",
    "DevSecOps",
    "Other",
]

# Microsoft's own release stages, most mature first.
STATUSES = ["GA", "Public preview", "Preview", "Private preview", "Announced"]

REQUIRED = [
    "id", "area", "title", "status", "available", "source_url", "learn_url",
    "sessions", "what_changes", "do_monday", "verified_at",
]
OPTIONAL = ["example"]
PROSE = ["title", "what_changes", "do_monday"]

# Primary Microsoft sources only. A host matches when it equals an entry or
# ends with "." + entry. GitHub's own blog and docs count for DevSecOps.
SOURCE_HOSTS = [
    "microsoft.com",
    "github.blog",
    "docs.github.com",
]
LEARN_HOSTS = [
    "learn.microsoft.com",
    "docs.github.com",
]

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SESSION_RE = re.compile(r"^[A-Z]{2,8}\d{1,5}[A-Z]?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")

TITLE_MAX = 120
LINE_MAX = 200

# Voice rules (from Pouyan's voice guide). Matched case-insensitively at the
# start of a word, so "leverage" also catches "leveraged".
BANNED = [
    "excited to announce", "incredibly honored", "don't want to miss",
    "couldn't be more", "synergy", "leverage", "innovative", "cutting-edge",
    "cutting edge", "game-changer", "game changer", "robust", "seamless",
    "certainly", "absolutely", "great question", "excellent point",
    "that's fascinating", "best solution", "uniquely positioned", "world-class",
]
DASHES = [
    ("\u2014", "em dash"),
    ("\u2013", "en dash"),
    ("&mdash;", "em dash entity"),
    ("&ndash;", "en dash entity"),
    ("&#8212;", "em dash entity"),
    ("&#8211;", "en dash entity"),
]
SPACED_HYPHEN = re.compile(r"\w - \w")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def voice_problems(text):
    """Return a list of voice-rule breaks in one piece of prose."""
    found = []
    for ch, label in DASHES:
        if ch in text:
            found.append(label)
    if SPACED_HYPHEN.search(text):
        found.append("hyphen used as a dash")
    low = text.lower().replace("\u2019", "'").replace("\u2018", "'")
    for phrase in BANNED:
        if re.search(r"\b" + re.escape(phrase), low):
            found.append(f"banned phrase '{phrase}'")
    return found


def load_rows(path=None):
    """Load a YAML file (default data/announcements.yaml) and return its rows.

    Raises on bad YAML or the wrong shape. An empty file gives no rows.
    """
    import yaml

    path = Path(path) if path else DATA
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    if doc is None:
        return []
    if not isinstance(doc, dict) or "announcements" not in doc:
        raise ValueError(f"{path.name} must be a mapping with an 'announcements' list")
    rows = doc["announcements"] or []
    if not isinstance(rows, list):
        raise ValueError("'announcements' must be a list")
    return rows


def as_text(value):
    """Dates come out of YAML as date objects; everything else as text."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()
