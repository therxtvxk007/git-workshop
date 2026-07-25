"""One-time setup: open a real browser, let you log into OpenOrbit yourself,
then (1) save the authenticated session so the headless filler can reuse it, and
(2) dump the create-event form's fields so the filler can be wired to them.

Run:  python -m poster2event.login

Your password is never read by this script or stored anywhere — you type it into
the browser window, and only the resulting session cookies are saved locally to
a gitignored file.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CREATE_EVENT_URL = "https://openorbit.app/create-event"
STATE_PATH = Path("openorbit_state.json")
FIELDS_PATH = Path("form_fields.json")

# JS that walks the live create-event form and reports every field it can drive,
# with the label text a human would read next to it. Send the resulting
# form_fields.json back so the field map in fill.py can be finalized.
_DUMP_JS = r"""
() => {
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    return null;
  };
  const out = [];
  document.querySelectorAll('input, textarea, select, [contenteditable="true"]').forEach((el) => {
    const rec = {
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || null,
      name: el.getAttribute('name') || null,
      id: el.id || null,
      placeholder: el.getAttribute('placeholder') || null,
      label: labelFor(el),
      required: el.hasAttribute('required'),
    };
    if (el.tagName.toLowerCase() === 'select') {
      rec.options = Array.from(el.options).map((o) => ({ value: o.value, text: o.text.trim() }));
    }
    out.push(rec);
  });
  const buttons = Array.from(document.querySelectorAll('button, [type=submit]')).map((b) => ({
    text: (b.innerText || b.value || '').trim(),
    type: b.getAttribute('type') || null,
    id: b.id || null,
  }));
  return { url: location.href, fields: out, buttons };
}
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(CREATE_EVENT_URL, wait_until="domcontentloaded")

        print("\n" + "=" * 68)
        print("A browser window is open.")
        print("  1. Log into OpenOrbit.")
        print(f"  2. Navigate to the create-event page ({CREATE_EVENT_URL}).")
        print("  3. Come back here and press Enter.")
        print("=" * 68)
        input("\nPress Enter once the create-event form is on screen... ")

        try:
            dump = page.evaluate(_DUMP_JS)
            FIELDS_PATH.write_text(json.dumps(dump, indent=2))
            n = len(dump.get("fields", []))
            print(f"\nSaved {n} form field(s) -> {FIELDS_PATH}")
            print("Send that file back to finalize the field map in fill.py.")
        except Exception as exc:  # pragma: no cover - best effort dump
            print(f"\nCould not dump form fields ({exc}).")
            print("You can still save the session below and paste the fields manually.")

        context.storage_state(path=str(STATE_PATH))
        print(f"Saved authenticated session -> {STATE_PATH} (gitignored)")
        browser.close()


if __name__ == "__main__":
    main()
