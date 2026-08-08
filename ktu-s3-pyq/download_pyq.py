#!/usr/bin/env python3
"""Download KTU S3 CSE (2024 scheme) previous-year question papers.

Scrapes one page per course code from pyq.ktunotes.live, collects the paper
links (the papers themselves are hosted on Google Drive), and downloads each
one into a per-subject folder.

The site sits behind Cloudflare and will rate-limit an impatient scraper, so
every request goes through a single throttled fetcher with exponential backoff
and Retry-After support. Downloads are resumable: anything already on disk with
a non-zero size is skipped, so re-running after an interruption is cheap.

Usage:
    python3 download_pyq.py                     # everything, into ./papers
    python3 download_pyq.py --dry-run           # list what would be downloaded
    python3 download_pyq.py --codes PCCST303    # one subject
    python3 download_pyq.py --no-labs           # skip the two lab courses
    python3 download_pyq.py --delay 10          # be gentler (default 6s)

Standard library only - no pip install required.
"""

import argparse
import html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar

from subjects import BY_CODE, default_codes

BASE = "https://pyq.ktunotes.live"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Google Drive IDs are long opaque strings; 25 chars is the conventional floor.
DRIVE_ID_RE = re.compile(r"[A-Za-z0-9_-]{25,}")
DRIVE_HOSTS = ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")
RETRY_STATUSES = {403, 408, 425, 429, 500, 502, 503, 504}


class RateLimited(Exception):
    """Raised when the server keeps refusing after every retry is spent."""


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class Fetcher:
    """Single throttled HTTP client shared by scraping and downloading."""

    def __init__(self, delay=6.0, max_retries=5, timeout=60, verbose=True):
        self.delay = delay
        self.max_retries = max_retries
        self.timeout = timeout
        self.verbose = verbose
        self._last_request = 0.0
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def _log(self, msg):
        if self.verbose:
            print(msg, file=sys.stderr, flush=True)

    def _throttle(self):
        # Jitter keeps a burst of requests from looking metronomic to Cloudflare.
        wait = self.delay + random.uniform(0, self.delay * 0.3)
        elapsed = time.monotonic() - self._last_request
        if elapsed < wait:
            time.sleep(wait - elapsed)
        self._last_request = time.monotonic()

    def open(self, url, headers=None):
        """Return an open response. Caller is responsible for closing it."""
        request_headers = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            request_headers.update(headers)

        backoff = 4.0
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            req = urllib.request.Request(url, headers=request_headers)
            try:
                return self.opener.open(req, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUSES:
                    raise
                sleep_for = backoff
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after and retry_after.strip().isdigit():
                    sleep_for = max(sleep_for, float(retry_after.strip()))
                self._log(
                    f"    HTTP {exc.code} on attempt {attempt}/{self.max_retries}, "
                    f"backing off {sleep_for:.0f}s"
                )
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                sleep_for = backoff
                self._log(
                    f"    network error on attempt {attempt}/{self.max_retries} "
                    f"({exc}), backing off {sleep_for:.0f}s"
                )
            if attempt < self.max_retries:
                time.sleep(sleep_for)
                backoff *= 2
        raise RateLimited(f"gave up on {url} after {self.max_retries} attempts: {last_error}")

    def get_text(self, url):
        with self.open(url) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


class AnchorParser(HTMLParser):
    """Collects (href, link_text) pairs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            self._href = attrs.get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.anchors.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


class FormParser(HTMLParser):
    """Pulls the action + hidden inputs out of Drive's virus-scan warning form."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.action = None
        self.fields = {}
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self._in_form = True
            self.action = attrs.get("action")
        elif tag == "input" and self._in_form:
            name = attrs.get("name")
            if name:
                self.fields[name] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._in_form = False


def drive_id_from_url(url):
    """Extract a Drive file ID from any of the URL shapes Drive uses."""
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname not in DRIVE_HOSTS:
        return None
    qs = urllib.parse.parse_qs(parsed.query)
    if "id" in qs and qs["id"]:
        return qs["id"][0]
    # /file/d/<ID>/view, /document/d/<ID>/edit, ...
    parts = [p for p in parsed.path.split("/") if p]
    if "d" in parts:
        idx = parts.index("d")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def extract_papers(page_html, page_url):
    """Return [{'id'|'url', 'label'}] for every paper link on a subject page.

    Anchors are the primary source because they carry the year label. A raw
    scan for Drive IDs runs afterwards as a safety net for pages that render
    their links from an embedded JSON blob rather than plain <a> tags.
    """
    papers = []
    seen = set()

    parser = AnchorParser()
    parser.feed(page_html)
    for href, text in parser.anchors:
        if not href:
            continue
        absolute = urllib.parse.urljoin(page_url, html.unescape(href))
        file_id = drive_id_from_url(absolute)
        if file_id:
            if file_id in seen:
                continue
            seen.add(file_id)
            papers.append({"id": file_id, "url": absolute, "label": text})
        elif absolute.lower().split("?")[0].endswith(".pdf"):
            if absolute in seen:
                continue
            seen.add(absolute)
            papers.append({"id": None, "url": absolute, "label": text})

    # Fallback: Drive IDs embedded anywhere in the markup (e.g. __NEXT_DATA__).
    for match in DRIVE_ID_RE.findall(page_html):
        if match in seen:
            continue
        # Only trust a bare ID if it appears in something Drive-shaped.
        window_start = max(0, page_html.find(match) - 80)
        window = page_html[window_start : page_html.find(match) + len(match)]
        if "drive.google.com" in window or "docs.google.com" in window:
            seen.add(match)
            papers.append(
                {
                    "id": match,
                    "url": f"https://drive.google.com/file/d/{match}/view",
                    "label": "",
                }
            )

    return papers


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #


def safe_filename(name, fallback):
    name = (name or "").strip().replace("/", "-").replace("\\", "-")
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or fallback


def filename_from_headers(headers, fallback):
    disposition = headers.get("Content-Disposition", "") if headers else ""
    match = re.search(r"filename\*=UTF-8''([^;\r\n]+)", disposition, re.IGNORECASE)
    if match:
        return safe_filename(urllib.parse.unquote(match.group(1)), fallback)
    match = re.search(r'filename="([^"]+)"', disposition)
    if match:
        return safe_filename(match.group(1), fallback)
    return fallback


def download_drive_file(fetcher, file_id, dest_dir, label):
    """Download one Drive file, handling the large-file confirmation form."""
    url = (
        "https://drive.usercontent.google.com/download"
        f"?id={urllib.parse.quote(file_id)}&export=download&confirm=t"
    )
    resp = fetcher.open(url)
    content_type = (resp.headers.get("Content-Type") or "").lower()

    if "text/html" in content_type:
        # Virus-scan interstitial: re-submit the form it hands back.
        body = resp.read().decode("utf-8", errors="replace")
        resp.close()
        form = FormParser()
        form.feed(body)
        if not form.action:
            raise RuntimeError("Drive returned an HTML page with no download form")
        query = urllib.parse.urlencode(form.fields)
        resp = fetcher.open(f"{form.action}?{query}" if query else form.action)

    fallback = safe_filename(label, file_id) + ".pdf"
    filename = filename_from_headers(resp.headers, fallback)
    return _stream_to_disk(resp, os.path.join(dest_dir, filename))


def download_direct(fetcher, url, dest_dir, label):
    resp = fetcher.open(url)
    fallback = safe_filename(label, os.path.basename(urllib.parse.urlparse(url).path))
    filename = filename_from_headers(resp.headers, fallback or "paper.pdf")
    return _stream_to_disk(resp, os.path.join(dest_dir, filename))


def _stream_to_disk(resp, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        resp.close()
        return path, os.path.getsize(path), True

    tmp = path + ".part"
    total = 0
    try:
        with resp, open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                total += len(chunk)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path, total, False


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="papers", help="output directory (default: papers)")
    ap.add_argument("--codes", nargs="+", help="course codes (default: all S3 CSE subjects)")
    ap.add_argument("--no-labs", action="store_true", help="skip PCCSL307 / PCCSL308")
    ap.add_argument("--delay", type=float, default=6.0, help="seconds between requests (default: 6)")
    ap.add_argument("--max-retries", type=int, default=5, help="retries per request (default: 5)")
    ap.add_argument("--dry-run", action="store_true", help="list papers, download nothing")
    args = ap.parse_args(argv)

    codes = args.codes or default_codes(include_labs=not args.no_labs)
    fetcher = Fetcher(delay=args.delay, max_retries=args.max_retries)
    os.makedirs(args.out, exist_ok=True)

    manifest = []
    failures = []

    for code in codes:
        subject = BY_CODE.get(code, {"code": code, "name": code, "kind": "theory"})
        print(f"\n=== {code} - {subject['name']} ===", flush=True)
        page_url = f"{BASE}/{code}"

        try:
            page = fetcher.get_text(page_url)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"  no page for {code} (404) - skipping", flush=True)
                continue
            failures.append((code, None, f"page fetch: HTTP {exc.code}"))
            print(f"  ! could not fetch page: HTTP {exc.code}", flush=True)
            continue
        except (RateLimited, urllib.error.URLError) as exc:
            failures.append((code, None, f"page fetch: {exc}"))
            print(f"  ! could not fetch page: {exc}", flush=True)
            continue

        papers = extract_papers(page, page_url)
        if not papers:
            print("  no paper links found on the page", flush=True)
            continue
        print(f"  found {len(papers)} paper link(s)", flush=True)

        subject_dir = os.path.join(args.out, safe_filename(f"{code} - {subject['name']}", code))
        if not args.dry_run:
            os.makedirs(subject_dir, exist_ok=True)

        for paper in papers:
            label = paper["label"] or paper["id"] or paper["url"]
            if args.dry_run:
                print(f"    [dry-run] {label}  <-  {paper['url']}", flush=True)
                manifest.append({"code": code, "label": paper["label"], "url": paper["url"]})
                continue
            try:
                if paper["id"]:
                    path, size, cached = download_drive_file(
                        fetcher, paper["id"], subject_dir, paper["label"]
                    )
                else:
                    path, size, cached = download_direct(
                        fetcher, paper["url"], subject_dir, paper["label"]
                    )
                status = "cached" if cached else f"{size / 1024:.0f} KB"
                print(f"    ok  {os.path.basename(path)}  ({status})", flush=True)
                manifest.append(
                    {
                        "code": code,
                        "label": paper["label"],
                        "url": paper["url"],
                        "path": os.path.relpath(path, args.out),
                        "bytes": size,
                    }
                )
            except Exception as exc:  # keep going; one bad paper shouldn't stop the run
                failures.append((code, label, str(exc)))
                print(f"    !   {label}: {exc}", flush=True)

    if not args.dry_run and manifest:
        manifest_path = os.path.join(args.out, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        print(f"\nmanifest written to {manifest_path}", flush=True)

    print(f"\n{len(manifest)} paper(s) processed, {len(failures)} failure(s)", flush=True)
    for code, label, err in failures:
        print(f"  FAILED {code} {label or ''}: {err}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
