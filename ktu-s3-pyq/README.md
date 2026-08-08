# KTU S3 CSE (2024 scheme) — previous-year question paper downloader

Downloads the previous-year question papers for every S3 CSE subject from
`pyq.ktunotes.live`, which hosts one page per course code and serves the papers
themselves from Google Drive.

## Why this is a script and not a folder of PDFs

The papers could not be downloaded from the Claude Code session that wrote
this. That session's egress proxy enforces a narrow allowlist — GitHub and a
few package registries — and every other host is refused at the gateway:

```
pyq.ktunotes.live:443   gateway answered 403 to CONNECT
drive.google.com:443    gateway answered 403 to CONNECT
www.ktunotes.in:443     blocked by the network egress proxy
ktuspecial.in:443       blocked by the network egress proxy
```

This is a policy denial, not rate limiting — slower pacing, retries, and
alternate mirrors all fail the same way, because the connection never leaves
the sandbox. Run this script anywhere with ordinary internet access and it will
fetch the papers.

## Usage

Python 3.8+, standard library only. No `pip install`.

```bash
python3 download_pyq.py                  # all subjects -> ./papers
python3 download_pyq.py --dry-run        # list what it would fetch, download nothing
python3 download_pyq.py --codes PCCST303 # a single subject
python3 download_pyq.py --no-labs        # skip the two lab courses
python3 download_pyq.py --delay 10       # slower pacing if you get throttled
python3 download_pyq.py --out ~/ktu/s3   # somewhere other than ./papers
```

Start with `--dry-run`. It performs one request per subject and prints the
paper links it found, which confirms the site's markup still matches what the
extractor expects before you pull a few hundred megabytes.

Output layout:

```
papers/
├── manifest.json
├── GAMAT301 - Mathematics for Computer and Information Science-3/
│   └── December 2024.pdf
├── PCCST302 - Theory of Computation/
└── ...
```

### Behaviour worth knowing

- **Throttled by default.** One request every ~6s plus jitter, from a single
  shared client. The site is behind Cloudflare and *will* rate-limit a fast
  scraper.
- **Backs off and retries.** 429/403/5xx trigger exponential backoff (4s, 8s,
  16s, …) and `Retry-After` is honoured when sent. Five attempts, then that one
  item is recorded as a failure and the run continues.
- **Resumable.** Files already on disk with a non-zero size are skipped, so
  re-running after an interruption costs only the page fetches. Partial
  downloads are written to `.part` and renamed on completion, so an interrupted
  transfer is never mistaken for a finished one.
- **Handles Drive's large-file interstitial.** Files big enough to skip virus
  scanning return an HTML form instead of bytes; the script submits it and
  follows through to the real download.
- **One bad paper doesn't stop the run.** Failures are collected and printed as
  a summary at the end; exit status is 1 if anything failed.

## Subjects covered

From the official curriculum table (page 4 of the curriculum PDF),
cross-checked against the detailed syllabus.

| Slot | Code | Subject | CIE/ESE | Credits |
|---|---|---|---|---|
| A | GAMAT301 | Mathematics for Computer and Information Science-3 | 40/60 | 3 |
| B | PCCST302 | Theory of Computation | 40/60 | 4 |
| C | PCCST303 | Data Structures and Algorithms | 40/60 | 4 |
| D | PBCST304 | Object Oriented Programming (PBL) | **60/40** | 4 |
| F | GAEST305 | Digital Electronics and Logic Design | 40/60 | 4 |
| G | UCHUT346 *or* UCHUT347 | Economics for Engineers *or* Engineering Ethics and Sustainable Development | 50/50 | 2 |
| L | PCCSL307 | Data Structures Lab | 50/50 | 2 |
| Q | PCCSL308 | Digital Lab | 50/50 | 2 |

**25 credits, 27 hrs/week** (29 and 31 with a Minor).

Notes:

- **PBCST304 is the only inverted one** — 60 CIE / 40 ESE, because it is the
  project-based-learning course. Every other theory subject is 40/60.
- **Slot G is a choice.** You take one of UCHUT346 / UCHUT347, in S3 or S4. The
  script tries both codes; the one you aren't registered for costs a single
  extra page fetch. Use `--codes` to narrow it.
- **The labs may have no papers.** `PCCSL307` / `PCCSL308` are internally
  evaluated, so their pages may not exist or may be empty. A 404 is reported
  and skipped, not treated as an error. `--no-labs` skips them outright.
- **Search by course code, not title.** Titles vary between sources: GAMAT301
  appears as "Mathematics for Information Science-3" in the curriculum table
  and "Mathematics for Computer and Information Science - 3" in the detailed
  syllabus; UCHUT347 appears as "Ethics and Sustainable Engineering" on note
  sites, though the official title is "Engineering Ethics and Sustainable
  Development".

## If the site changes

`extract_papers()` in `download_pyq.py` reads `<a>` tags first (they carry the
year labels), then falls back to scanning the raw markup for Google Drive file
IDs, which catches pages that build their links from an embedded JSON blob.

If a subject page reports "no paper links found", the page is likely rendered
client-side after load. Save the fully-rendered HTML from your browser's
devtools and the same extractor logic will work against it — or fetch it with a
headless browser and feed the HTML to `extract_papers()`.

## Tests

```bash
python3 test_download_pyq.py
```

22 tests, no network required: link extraction runs against a synthetic page,
and the transfer path (streaming, header-derived filenames, resume, `.part`
cleanup, retry exhaustion) runs against a throwaway localhost HTTP server.
