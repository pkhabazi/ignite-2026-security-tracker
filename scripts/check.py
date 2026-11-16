#!/usr/bin/env python3
"""Validate data/announcements.yaml before a render or a release.

Usage:
    python scripts/check.py              schema, voice rules and every link
    python scripts/check.py --offline    schema and voice rules, no network
    python scripts/check.py --examples   also fetch the links of example rows
    python scripts/check.py --offline --extra PATH
                                         also validate rows kept in another file
                                         (for example outside git); never rendered

What it checks:
    schema    required fields, no unknown fields, unique ids, known area,
              status is one of GA / Public preview / Preview / Private preview /
              Announced,
              dates are real dates, URLs are https on a Microsoft host
    voice     title, what_changes, do_monday and the README templates have no
              em or en dash (also as HTML entity), no hyphen used as a dash,
              none of the banned words
    links     every source_url and learn_url answers HTTP 200 (skipped with
              --offline); a redirect or missing status wording is a warning
    outputs   README.md and docs/index.html carry no dashes, match the data,
              and a render that still shows example rows is flagged

Exit 0 = clean (warnings may print), 1 = errors.
"""

import argparse
import datetime as dt
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from schema import (AREAS, DASHES, DATE_RE, ID_RE, INDEX, LEARN_HOSTS, LINE_MAX,
                    MONTH_RE, OPTIONAL, PROSE, README, REQUIRED, SESSION_RE,
                    SOURCE_HOSTS, STATUSES, TEMPLATES, TITLE_MAX, as_text,
                    load_rows, voice_problems)

USER_AGENT = "Mozilla/5.0 (compatible; ignite-2026-security-tracker link check)"
TIMEOUT = 20

# Words that should appear on the source page for a given status. Missing
# wording is a warning only: many pages render their text with JavaScript.
STATUS_WORDING = {
    "GA": ["generally available", "general availability", "now available"],
    "Public preview": ["public preview"],
    "Preview": ["preview"],
    "Private preview": ["private preview", "limited preview"],
}


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def host_allowed(url, hosts):
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in hosts)


def check_url(rep, where, field, value, hosts, required):
    url = as_text(value)
    if not url:
        if required:
            rep.error(where, f"{field} is empty")
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        rep.error(where, f"{field} must be an https URL: {url}")
        return None
    if not host_allowed(url, hosts):
        rep.error(where, f"{field} is not on a primary Microsoft host ({', '.join(hosts)}): {url}")
        return None
    return url


def parse_day(value):
    if isinstance(value, dt.datetime):
        return None
    if isinstance(value, dt.date):
        return value
    text = as_text(value)
    if DATE_RE.match(text):
        try:
            return dt.date.fromisoformat(text)
        except ValueError:
            return None
    return None


def check_line(rep, where, field, value, limit):
    if not isinstance(value, str) or not value.strip():
        rep.error(where, f"{field} must be non-empty text")
        return
    if "\n" in value.strip():
        rep.error(where, f"{field} must be one line")
    if len(value.strip()) > limit:
        rep.error(where, f"{field} is {len(value.strip())} chars, keep it under {limit}")


def check_row(rep, i, row, seen_ids):
    if not isinstance(row, dict):
        rep.error(f"row {i}", "is not a mapping")
        return
    rid = as_text(row.get("id")) or f"row {i}"
    where = rid

    for key in row:
        if key not in REQUIRED and key not in OPTIONAL:
            rep.error(where, f"unknown field '{key}'")
    for key in REQUIRED:
        if key not in row:
            rep.error(where, f"missing field '{key}'")

    if not isinstance(row.get("id"), str) or not ID_RE.match(row.get("id", "")):
        rep.error(where, "id must be a lowercase slug (a-z, 0-9, single hyphens)")
    elif rid in seen_ids:
        rep.error(where, "duplicate id")
    seen_ids.add(rid)

    example = row.get("example", False)
    if not isinstance(example, bool):
        rep.error(where, "example must be true or false")
    elif example != rid.startswith("example-"):
        rep.error(where, "example rows (and only example rows) have an id starting with 'example-'")

    if row.get("area") not in AREAS:
        rep.error(where, f"area '{as_text(row.get('area'))}' is not one of: {'; '.join(AREAS)}")

    status = row.get("status")
    if status not in STATUSES:
        hint = next((s for s in STATUSES if s.lower() == as_text(status).lower()), None)
        extra = f" (did you mean '{hint}'?)" if hint else ""
        rep.error(where, f"status '{as_text(status)}' is not one of: {', '.join(STATUSES)}{extra}")

    check_line(rep, where, "title", row.get("title"), TITLE_MAX)
    check_line(rep, where, "what_changes", row.get("what_changes"), LINE_MAX)
    check_line(rep, where, "do_monday", row.get("do_monday"), LINE_MAX)
    for field in PROSE:
        value = row.get(field)
        if isinstance(value, str):
            for problem in voice_problems(value):
                rep.error(where, f"{field}: {problem}")

    available = row.get("available")
    if available not in (None, ""):
        text = as_text(available)
        ok = parse_day(available) is not None
        if not ok and MONTH_RE.match(text):
            ok = 1 <= int(text[5:7]) <= 12
        if not ok:
            rep.error(where, f"available '{text}' must be YYYY-MM-DD, YYYY-MM or empty")

    verified = parse_day(row.get("verified_at"))
    if verified is None:
        rep.error(where, "verified_at must be a date, YYYY-MM-DD")
    elif verified > dt.date.today():
        rep.error(where, f"verified_at {verified} is in the future")

    sessions = row.get("sessions")
    if sessions is None:
        rep.error(where, "sessions must be a list, use [] for none")
    elif not isinstance(sessions, list):
        rep.error(where, "sessions must be a list of session codes")
    else:
        for code in sessions:
            if not isinstance(code, str) or not SESSION_RE.match(code):
                rep.error(where, f"session code '{as_text(code)}' does not look like BRK123 or LAB456")
        if len(set(map(str, sessions))) != len(sessions):
            rep.error(where, "duplicate session code")

    check_url(rep, where, "source_url", row.get("source_url"), SOURCE_HOSTS, required=True)
    if check_url(rep, where, "learn_url", row.get("learn_url"), LEARN_HOSTS, required=False) is None \
            and not as_text(row.get("learn_url")) and not example:
        rep.warn(where, "no learn_url yet")


def strip_code(md):
    md = re.sub(r"```.*?```", "", md, flags=re.S)
    return re.sub(r"`[^`]*`", "", md)


def check_templates(rep):
    for path in sorted(TEMPLATES.glob("*.md")):
        text = strip_code(path.read_text(encoding="utf-8"))
        for n, line in enumerate(text.splitlines(), 1):
            for problem in voice_problems(line):
                rep.error(f"templates/{path.name}:{n}", problem)


def check_outputs(rep, rows):
    """Generated files: no dashes, in sync with the data, examples flagged."""
    import render  # same folder; imported late so a broken schema fails first

    for path, name, marker in ((README, "README.md", r"examples: (yes|no)"),
                               (INDEX, "docs/index.html", r'name="tracker-examples" content="(yes|no)"')):
        if not path.exists():
            rep.warn(name, "not rendered yet, run scripts/render.py")
            continue
        text = path.read_text(encoding="utf-8")
        for ch, label in DASHES:
            if ch in text:
                rep.error(name, f"contains an {label}")
        m = re.search(marker, text)
        examples = bool(m and m.group(1) == "yes")
        if examples:
            rep.warn(name, "rendered WITH example rows; run scripts/render.py without --examples before a release")
        shown = sorted((r for r in rows if examples or not r.get("example")), key=render.sort_key)
        expected = render.readme(shown, examples) if path == README else render.index_html(shown, examples)
        if text != expected:
            rep.warn(name, "out of date with the data, run scripts/render.py")


def tls_context():
    """python.org builds on macOS ship without a CA bundle; find one."""
    if os.environ.get("SSL_CERT_FILE"):
        return ssl.create_default_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


TLS = tls_context()


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "text/html,application/xhtml+xml,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=TLS) as resp:
            body = resp.read(800_000).decode("utf-8", errors="replace")
            return resp.status, resp.geturl(), body, ""
    except urllib.error.HTTPError as exc:
        return exc.code, url, "", ""
    except Exception as exc:  # DNS, TLS, timeout
        return None, url, "", str(getattr(exc, "reason", exc))


def same_page(a, b):
    pa, pb = urlparse(a), urlparse(b)
    return (pa.hostname, pa.path.rstrip("/").lower()) == (pb.hostname, pb.path.rstrip("/").lower())


def check_links(rep, rows, include_examples):
    targets = {}
    for row in rows:
        if not isinstance(row, dict) or (row.get("example") and not include_examples):
            continue
        for field in ("source_url", "learn_url"):
            url = as_text(row.get(field))
            if url.startswith("https://"):
                targets.setdefault(url, []).append((as_text(row.get("id")), field, row.get("status")))
    if not targets:
        return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = dict(zip(targets, pool.map(fetch, targets)))
    for url, (code, final, body, err) in results.items():
        for rid, field, status in targets[url]:
            if code != 200:
                rep.error(rid, f"{field} answered {code or err or 'nothing'}: {url}")
                continue
            if not same_page(url, final):
                rep.warn(rid, f"{field} redirects to {final}")
            if field == "source_url" and status in STATUS_WORDING:
                text = re.sub(r"<[^>]+>", " ", body).lower()
                if not any(w in text for w in STATUS_WORDING[status]):
                    rep.warn(rid, f"'{status}' wording not found on the source page, check it by hand")
    return len(targets)


def main():
    ap = argparse.ArgumentParser(description="Validate data/announcements.yaml")
    ap.add_argument("--offline", action="store_true", help="skip the HTTP checks")
    ap.add_argument("--examples", action="store_true", help="also fetch links of example rows")
    ap.add_argument("--extra", action="append", default=[], metavar="PATH",
                    help="also validate rows from another YAML file (repeatable); "
                         "these rows are never rendered into README.md or docs/")
    args = ap.parse_args()

    rep = Report()
    try:
        rows = load_rows()
        extra_rows = []
        for path in args.extra:
            extra_rows += load_rows(os.path.expanduser(path))
    except Exception as exc:
        print(f"check: cannot read the data: {exc}")
        return 1

    seen = set()
    for i, row in enumerate(rows + extra_rows, 1):
        check_row(rep, i, row, seen)
    check_templates(rep)
    if not rep.errors:
        check_outputs(rep, rows)  # tracked rows only: extra rows never reach the outputs

    if args.offline:
        links = "links skipped (--offline)"
    elif rep.errors:
        links = "links skipped (fix the errors first)"
    else:
        links = f"{check_links(rep, rows + extra_rows, args.examples)} link(s) fetched"

    real = sum(1 for r in rows if isinstance(r, dict) and not r.get("example"))
    extra = f", {len(extra_rows)} extra" if args.extra else ""
    print(f"check: {len(rows)} row(s), {real} real, {len(rows) - real} example{extra}; {links}")
    for msg in rep.errors:
        print(f"  ERROR  {msg}")
    for msg in rep.warnings:
        print(f"  warn   {msg}")
    print("  clean" if not rep.errors else f"  {len(rep.errors)} error(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
