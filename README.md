# poster2event

Hand it an event poster, get the event created on
[openorbit.app/create-event](https://openorbit.app/create-event) — minimal effort.

The work is split into the two things each half is good at:

- **Reading the poster** (every layout is different) → Claude vision + a QR decode.
  This is the part where an LLM genuinely belongs.
- **Filling the form** (same fields every time) → a deterministic Playwright script,
  so it's fast and never misclicks.

```
poster.jpg ──▶ extract.py ──▶ EventData (JSON) ──▶ fill.py ──▶ OpenOrbit form
              (Claude vision            (structured)         (Playwright,
               + QR decode)                                   reuses your login)
```

## Setup

```bash
pip install -r requirements.txt
playwright install chromium

cp .env.example .env      # then add your ANTHROPIC_API_KEY
```

## One-time login (captures your session, no password stored)

```bash
python -m poster2event.login
```

A real browser opens. **You** log into OpenOrbit and go to the create-event page,
then press Enter. Two files are written (both gitignored):

- `openorbit_state.json` — your authenticated session, reused by the headless filler.
  Your password is only ever typed into the browser, never read or stored by the tool.
- `form_fields.json` — a dump of the create-event form's fields.

> **Wiring the form:** `fill.py`'s field map starts empty on purpose — it can only be
> written accurately against OpenOrbit's real form. Share `form_fields.json` after this
> step and the map gets finalized. Until then, `--dry-run` exercises the whole
> poster-reading half.

Re-run this whenever the saved session expires.

## Use it

```bash
poster2event poster.jpg              # read poster + fill the form (stops before submit)
poster2event poster.jpg --dry-run    # just print the extracted JSON
poster2event poster.jpg --submit     # fill AND submit
poster2event poster.jpg --show       # run the browser visibly
```

(Equivalently: `python -m poster2event.cli poster.jpg`.)

## What it pulls off a poster

Example (`--dry-run` on the VERTEXA poster):

```json
{
  "event_name": "VERTEXA",
  "fest": "KRANTHI'26",
  "tagline": "Debate x Design Dilemma",
  "slogan": "Think. Argue. Design. Build.",
  "organizer": "ISTE GECT Students' Chapter, Mech Forum — Govt. Engineering College Thrissur",
  "prize_pool_inr": 1500,
  "entry_fee_note": "GECians free; others INR 30",
  "registration_url": "<decoded from the QR code>",
  "contacts": [
    { "name": "Sai Krishna", "phone": "+91 7994414003" },
    { "name": "Udith K", "phone": "+91 7736222844" }
  ],
  "sessions": [
    { "day": 1, "title": "Debate",         "date": "2026-07-27", "start_time": "16:30", "venue": "Room 105, ME Dept" },
    { "day": 2, "title": "Design Dilemma", "date": "2026-07-28", "start_time": "16:30", "venue": "Room 109, Main Block", "note": "qualify from Day 1" }
  ]
}
```

It handles the tricky bits: multi-day structure, the qualify-to-advance gate,
GECians-free-vs-₹30, both organizing bodies, and it decodes the QR to get the real
registration link.

## Layout

| File | Role |
|------|------|
| `poster2event/schema.py`  | `EventData` — the structured shape a poster becomes |
| `poster2event/extract.py` | poster image + QR → `EventData` (Claude vision) |
| `poster2event/login.py`   | one-time: capture session + dump the form's fields |
| `poster2event/fill.py`    | `EventData` → OpenOrbit form (Playwright) — field map filled in after login |
| `poster2event/cli.py`     | the `poster2event` command |
