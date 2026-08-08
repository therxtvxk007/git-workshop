#!/usr/bin/env python3
"""Offline tests for the scraping/download plumbing.

Network access to pyq.ktunotes.live is not required: link extraction runs
against a synthetic page, and the transfer path runs against a throwaway
localhost HTTP server.

Run:  python3 test_download_pyq.py
"""

import http.server
import os
import shutil
import tempfile
import threading
import unittest

from download_pyq import (
    Fetcher,
    FormParser,
    download_direct,
    drive_id_from_url,
    extract_papers,
    filename_from_headers,
    safe_filename,
)

ID_A = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
ID_B = "1ZyXwVuTsRqPoNmLkJiHgFeDcBa987654"
ID_C = "1QqWwEeRrTtYyUuIiOoPpAaSsDdFfGg321"

SAMPLE_PAGE = f"""
<html><body>
  <h1>PCCST303 Data Structures and Algorithms</h1>
  <a href="/">Home</a>
  <a href="https://drive.google.com/file/d/{ID_A}/view?usp=sharing">
     December 2024 Regular
  </a>
  <a href="https://drive.google.com/open?id={ID_B}">May 2025 Supplementary</a>
  <a href="https://example.org/papers/PCCST303-model.pdf">Model Question Paper</a>
  <a href="https://drive.google.com/file/d/{ID_A}/view">December 2024 Regular (dup)</a>
  <script id="__NEXT_DATA__">
    {{"links":[{{"href":"https://drive.google.com/file/d/{ID_C}/view"}}]}}
  </script>
</body></html>
"""


class TestLinkExtraction(unittest.TestCase):
    def setUp(self):
        self.papers = extract_papers(SAMPLE_PAGE, "https://pyq.ktunotes.live/PCCST303")

    def test_finds_every_distinct_paper(self):
        # 2 anchor Drive links + 1 direct PDF + 1 embedded-JSON Drive link.
        self.assertEqual(len(self.papers), 4)

    def test_deduplicates_repeated_drive_id(self):
        ids = [p["id"] for p in self.papers if p["id"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_keeps_year_labels_from_anchor_text(self):
        labels = {p["label"] for p in self.papers}
        self.assertIn("December 2024 Regular", labels)
        self.assertIn("May 2025 Supplementary", labels)

    def test_ignores_navigation_links(self):
        self.assertNotIn("Home", {p["label"] for p in self.papers})

    def test_picks_up_direct_pdf_link(self):
        pdfs = [p for p in self.papers if p["id"] is None]
        self.assertEqual(len(pdfs), 1)
        self.assertTrue(pdfs[0]["url"].endswith("PCCST303-model.pdf"))

    def test_recovers_id_embedded_in_json_blob(self):
        self.assertIn(ID_C, [p["id"] for p in self.papers])

    def test_empty_page_yields_nothing(self):
        self.assertEqual(extract_papers("<html></html>", "https://x/y"), [])


class TestDriveIdParsing(unittest.TestCase):
    def test_file_d_form(self):
        self.assertEqual(
            drive_id_from_url(f"https://drive.google.com/file/d/{ID_A}/view"), ID_A
        )

    def test_open_id_form(self):
        self.assertEqual(drive_id_from_url(f"https://drive.google.com/open?id={ID_A}"), ID_A)

    def test_uc_export_form(self):
        self.assertEqual(
            drive_id_from_url(f"https://drive.google.com/uc?export=download&id={ID_A}"), ID_A
        )

    def test_usercontent_host(self):
        self.assertEqual(
            drive_id_from_url(f"https://drive.usercontent.google.com/download?id={ID_A}"), ID_A
        )

    def test_non_drive_host_returns_none(self):
        self.assertIsNone(drive_id_from_url("https://example.org/file/d/whatever/view"))


class TestFilenames(unittest.TestCase):
    def test_strips_path_separators_and_control_chars(self):
        self.assertEqual(safe_filename('Dec/2024: "reg"?', "fb"), "Dec-2024 reg")

    def test_falls_back_when_empty(self):
        self.assertEqual(safe_filename("   ", "fallback"), "fallback")

    def test_quoted_content_disposition(self):
        headers = {"Content-Disposition": 'attachment; filename="DSA Dec 2024.pdf"'}
        self.assertEqual(filename_from_headers(headers, "fb"), "DSA Dec 2024.pdf")

    def test_utf8_content_disposition(self):
        headers = {"Content-Disposition": "attachment; filename*=UTF-8''DSA%20Dec%202024.pdf"}
        self.assertEqual(filename_from_headers(headers, "fb"), "DSA Dec 2024.pdf")

    def test_missing_disposition_uses_fallback(self):
        self.assertEqual(filename_from_headers({}, "fb.pdf"), "fb.pdf")


class TestDriveConfirmForm(unittest.TestCase):
    """Drive answers large files with an interstitial form instead of bytes."""

    FORM = """
    <html><body><form id="download-form"
        action="https://drive.usercontent.google.com/download" method="get">
      <input type="hidden" name="id" value="ABC123">
      <input type="hidden" name="export" value="download">
      <input type="hidden" name="confirm" value="t">
      <input type="hidden" name="uuid" value="xyz-789">
    </form></body></html>
    """

    def test_parses_action_and_fields(self):
        parser = FormParser()
        parser.feed(self.FORM)
        self.assertEqual(parser.action, "https://drive.usercontent.google.com/download")
        self.assertEqual(parser.fields["id"], "ABC123")
        self.assertEqual(parser.fields["confirm"], "t")
        self.assertEqual(parser.fields["uuid"], "xyz-789")


PDF_BYTES = b"%PDF-1.4\n" + b"x" * 4096 + b"\n%%EOF\n"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/paper.pdf"):
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="Dec 2024.pdf"')
            self.send_header("Content-Length", str(len(PDF_BYTES)))
            self.end_headers()
            self.wfile.write(PDF_BYTES)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass


class TestTransfer(unittest.TestCase):
    """Exercises the real socket path: fetch -> stream -> disk -> resume."""

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.fetcher = Fetcher(delay=0, max_retries=1, verbose=False)
        self.url = f"http://127.0.0.1:{self.port}/paper.pdf"

    def test_downloads_and_names_from_header(self):
        path, size, cached = download_direct(self.fetcher, self.url, self.tmp, "label")
        self.assertEqual(os.path.basename(path), "Dec 2024.pdf")
        self.assertEqual(size, len(PDF_BYTES))
        self.assertFalse(cached)
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), PDF_BYTES)

    def test_second_run_is_skipped_not_refetched(self):
        download_direct(self.fetcher, self.url, self.tmp, "label")
        _, _, cached = download_direct(self.fetcher, self.url, self.tmp, "label")
        self.assertTrue(cached)

    def test_no_partial_file_left_behind(self):
        download_direct(self.fetcher, self.url, self.tmp, "label")
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".part")], [])


class TestRetry(unittest.TestCase):
    def test_gives_up_and_raises_after_retries(self):
        from download_pyq import RateLimited

        fetcher = Fetcher(delay=0, max_retries=2, timeout=2, verbose=False)
        # Port 9 (discard) refuses fast; exercises the URLError retry branch.
        with self.assertRaises(RateLimited):
            fetcher.get_text("http://127.0.0.1:9/nope")


if __name__ == "__main__":
    unittest.main(verbosity=2)
