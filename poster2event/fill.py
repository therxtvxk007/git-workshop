"""EventData -> filled OpenOrbit create-event form, via Playwright.

Reuses the authenticated session captured by `python -m poster2event.login`
(openorbit_state.json), so there is no password handling here.

The FIELD_MAP below is intentionally empty: it can only be written accurately
once we've seen OpenOrbit's real create-event form (run login.py, which dumps
form_fields.json). Until then, fill_event() raises a clear, actionable error and
the extract half of the pipeline still works via `--dry-run`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional

from playwright.sync_api import Page, sync_playwright

from .schema import EventData

STATE_PATH = Path("openorbit_state.json")
CREATE_EVENT_URL = "https://openorbit.app/create-event"


# ---------------------------------------------------------------------------
# Field map — FILL THIS IN once form_fields.json is available.
#
# Each entry says: which page control, how to set it, and what value to pull
# from the EventData. `kind` is one of: text, textarea, date, time, select,
# checkbox. Example of the shape (selectors are placeholders):
#
#   Field("input[name='title']",       "text",   lambda e: e.event_name),
#   Field("textarea[name='about']",    "textarea", lambda e: e.description),
#   Field("input[name='prize']",       "text",   lambda e: e.prize_pool_inr),
#   Field("input[name='start_date']",  "date",   lambda e: e.sessions[0].date),
#   Field("input[name='start_time']",  "time",   lambda e: e.sessions[0].start_time),
#   Field("select[name='category']",   "select", lambda e: e.category),
# ---------------------------------------------------------------------------


class Field:
    def __init__(self, selector: str, kind: str, value: Callable[[EventData], object]):
        self.selector = selector
        self.kind = kind
        self.value = value


def build_field_map() -> List[Field]:
    """Return the list of form fields to fill. Empty until OpenOrbit's form is known."""
    return []


SUBMIT_SELECTOR = "button[type='submit']"  # confirm/replace after inspecting the form


def _set(page: Page, field: Field, value: object) -> None:
    if value is None or value == "":
        return
    text = str(value)
    if field.kind in ("text", "textarea", "date", "time"):
        page.fill(field.selector, text)
    elif field.kind == "select":
        page.select_option(field.selector, label=text)
    elif field.kind == "checkbox":
        if value:
            page.check(field.selector)
    else:
        raise ValueError(f"unknown field kind: {field.kind}")


def fill_event(
    event: EventData,
    *,
    submit: bool = False,
    headless: bool = True,
    state_path: str | Path = STATE_PATH,
    url: str = CREATE_EVENT_URL,
) -> None:
    """Open the create-event form (already logged in) and fill it from `event`.

    submit=False fills but does not click the submit button, so you can eyeball
    the form before committing.
    """
    field_map = build_field_map()
    if not field_map:
        raise RuntimeError(
            "The OpenOrbit field map isn't configured yet.\n"
            "Run `python -m poster2event.login`, log in, and share the generated "
            "form_fields.json so fill.py can be wired to the real form.\n"
            "(Use `--dry-run` to test the extraction half in the meantime.)"
        )

    state = Path(state_path)
    if not state.is_file():
        raise FileNotFoundError(
            f"No saved session at {state}. Run `python -m poster2event.login` first."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state))
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        for field in field_map:
            _set(page, field, field.value(event))

        if submit:
            page.click(SUBMIT_SELECTOR)
            page.wait_for_load_state("networkidle")
            print("Submitted.")
        else:
            print("Form filled (not submitted). Review the browser, or pass --submit.")

        browser.close()
