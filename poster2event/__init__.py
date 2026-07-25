"""poster2event — turn an event poster image into an OpenOrbit event.

Two halves:
  * extract.py — Claude vision + QR decode → structured EventData (the "smart" part)
  * fill.py    — Playwright drives openorbit.app/create-event from EventData (the "reliable" part)

See README.md for the workflow.
"""

from .schema import Contact, EventData, Session

__all__ = ["EventData", "Session", "Contact"]
__version__ = "0.1.0"
