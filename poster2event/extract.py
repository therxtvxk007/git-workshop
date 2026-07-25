"""Poster image -> EventData, using Claude vision + a QR decode for the link.

This is the half where an LLM genuinely earns its place: every poster is laid
out differently, so a deterministic parser can't read them. The registration
URL is the one thing vision can't read reliably, so we decode the QR code
ourselves and treat that as authoritative.
"""

from __future__ import annotations

import base64
import os
from datetime import date
from pathlib import Path
from typing import Optional

import anthropic

from .schema import EventData

DEFAULT_MODEL = os.environ.get("POSTER2EVENT_MODEL", "claude-opus-5")

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_PROMPT = """You are reading an event poster to create the event on a registration platform.

Extract the details into the required structure. Rules:
- Use null for anything not shown. Do NOT invent values.
- Dates: output ISO YYYY-MM-DD. Posters usually omit the year — infer it from the
  fest name (e.g. "KRANTHI'26" -> 2026) or, failing that, choose the next
  occurrence of that date on/after today's date, which is {today}.
- Times: 24-hour HH:MM (e.g. "4:30 PM" -> "16:30").
- prize_pool_inr: whole rupees as an integer ("1.5K" -> 1500, "₹2,000" -> 2000).
- A multi-day event has one `sessions` entry per day/round. Capture any gating
  note between rounds (e.g. "qualify from Day 1").
- Capture every contact (name + phone) and both the organizing club and the
  institution if shown.
- Leave registration_url null; it is filled separately from the QR code.
Return only the structured data."""


def _media_type(path: Path) -> str:
    return _MEDIA_TYPES.get(path.suffix.lower(), "image/jpeg")


def decode_qr(image_path: str | Path) -> Optional[str]:
    """Best-effort QR decode -> the registration URL. Returns None if unreadable
    or if OpenCV isn't installed (extraction still works without it)."""
    try:
        import cv2  # imported lazily so the extractor degrades gracefully
    except ImportError:
        return None
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    data, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return data or None


def extract_event(
    image_path: str | Path,
    *,
    model: str = DEFAULT_MODEL,
    client: Optional[anthropic.Anthropic] = None,
) -> EventData:
    """Read a poster image into an EventData."""
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    client = client or anthropic.Anthropic()

    response = client.messages.parse(
        model=model,
        max_tokens=8192,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _media_type(path),
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT.format(today=date.today().isoformat())},
                ],
            }
        ],
        output_format=EventData,
    )

    event = response.parsed_output
    if event is None:
        raise RuntimeError(
            f"Model did not return structured data (stop_reason={response.stop_reason}). "
            "Try a clearer/larger image."
        )

    # The QR code is the source of truth for the registration link.
    qr_url = decode_qr(path)
    if qr_url:
        event.registration_url = qr_url

    return event
