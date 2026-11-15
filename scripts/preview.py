#!/usr/bin/env python3
"""Local preview of the tracker page: edit the YAML, refresh the browser.

Usage:
    python scripts/preview.py                 tracked rows plus the example rows
    python scripts/preview.py --no-examples   exactly what the published page shows
    python scripts/preview.py --extra PATH    also rows from another YAML file
                                              (repeatable), for rows kept outside git
    python scripts/preview.py --port 8791 --no-open

Writes nothing. Every refresh re-reads the YAML and the templates and renders
the page in memory, so README.md and docs/ never change and rows from --extra
never reach a tracked file. Listens on 127.0.0.1 only. Anything check.py would
flag (offline checks) shows in a banner at the top of the page and in the
terminal. A change to the Python scripts needs a restart.
"""

import argparse
import html
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import check
import render
from schema import AREAS, DATA, REQUIRED, STATUSES, load_rows


def build(extras, examples):
    """Return (page html, one-line summary, list of problems)."""
    rep = check.Report()
    tracked, extra_rows = [], []
    for path in [DATA] + extras:
        try:
            got = load_rows(path)
        except Exception as exc:
            rep.error(path.name, f"cannot read: {exc}")
            continue
        (tracked if path == DATA else extra_rows).extend(got)

    seen = set()
    for i, row in enumerate(tracked + extra_rows, 1):
        check.check_row(rep, i, row, seen)
    check.check_templates(rep)

    def renderable(r):
        return (isinstance(r, dict) and all(k in r for k in REQUIRED)
                and r.get("area") in AREAS and r.get("status") in STATUSES)

    shown = [r for r in tracked + extra_rows if renderable(r) and (examples or not r.get("example"))]
    page = render.index_html(sorted(shown, key=render.sort_key), examples)

    n_examples = sum(1 for r in tracked if isinstance(r, dict) and r.get("example"))
    parts = [f"{len(tracked) - n_examples} tracked",
             f"{n_examples} example{' (hidden)' if not examples else ''}"]
    if extras:
        names = ", ".join(p.name for p in extras)
        parts.append(f"{len(extra_rows)} from {names} (not in git)")
    summary = f"Local preview, not published. Rows shown: {len(shown)} ({', '.join(parts)})"

    problems = [f"ERROR {m}" for m in rep.errors] + [f"warn {m}" for m in rep.warnings]
    bar = ('<div style="font:13px/1.4 system-ui,sans-serif;background:#1f2937;color:#f9fafb;'
           'padding:6px 16px">' + html.escape(summary) + "</div>")
    if problems:
        bg, fg = ("#fde2e2", "#7f1d1d") if rep.errors else ("#fff4d6", "#6b4500")
        items = "".join(f"<li>{html.escape(p)}</li>" for p in problems)
        bar += (f'<div role="alert" style="font:14px/1.45 system-ui,sans-serif;background:{bg};'
                f'color:{fg};padding:8px 16px"><strong>{len(rep.errors)} error(s), '
                f'{len(rep.warnings)} warning(s)</strong><ul style="margin:4px 0 0;padding-left:20px">'
                f"{items}</ul></div>")
    page = page.replace("<body>\n", "<body>\n" + bar + "\n", 1)
    return page, summary, problems


def main():
    ap = argparse.ArgumentParser(description="Serve a live local preview of the tracker page")
    ap.add_argument("--no-examples", action="store_true", help="hide example rows, as published")
    ap.add_argument("--extra", action="append", default=[], metavar="PATH",
                    help="also show rows from another YAML file (repeatable)")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = ap.parse_args()

    extras = [Path(os.path.expanduser(p)).resolve() for p in args.extra]
    for path in extras:
        if not path.exists():
            print(f"preview: {path} does not exist", file=sys.stderr)
            return 1
    examples = not args.no_examples

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            page, summary, problems = build(extras, examples)
            body = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            print(summary + (f"; {len(problems)} problem(s)" if problems else "; clean"), flush=True)
            for p in problems:
                print("  " + p, flush=True)

        def log_message(self, *a):
            pass

    server = None
    for port in range(args.port, args.port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    if server is None:
        print(f"preview: no free port in {args.port}..{args.port + 9}", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"preview: {url}  (edit data/ or templates/, then refresh; Ctrl+C stops)", flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
