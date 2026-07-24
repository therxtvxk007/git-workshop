# OpenOrbit Event Automator

A privacy-friendly Chrome/Edge extension that extracts structured event
information from a complete WhatsApp/Instagram announcement and fills the form
at `https://openorbit.app/create-event`.

## Install

1. Extract the ZIP.
2. Open `chrome://extensions` (or `edge://extensions`).
3. Enable **Developer mode**.
4. Choose **Load unpacked** and select the extracted
   `openorbit-event-automator` folder.
5. Pin **OpenOrbit Event Automator** to the browser toolbar.

## Use

1. Sign in to OpenOrbit normally.
2. Open `https://openorbit.app/create-event`.
3. Paste the complete event announcement into the extension and choose
   **Extract every event detail**.
4. Review the extracted title, dates, time, fees, prize, links, contacts,
   organizer, category, and tags.
5. Choose **Fill OpenOrbit form**.
6. Review the green-highlighted fields and fill any fields reported as
   “Not found”.
7. Add the event image manually if required, then publish from OpenOrbit.

Templates are saved only in the browser extension’s local storage. Passwords
are never read or stored. The extension deliberately does not press the final
publish/submit button.

The original announcement is preserved verbatim as the description, so details
that do not have a dedicated OpenOrbit field are not discarded.

## Reusing and sharing templates

Use **Copy JSON** to export an event template and **Import clipboard JSON** to
load one. Supported fields:

```json
{
  "title": "AI Workshop",
  "description": "Hands-on introduction to practical AI.",
  "startDate": "2026-08-01",
  "startTime": "10:00",
  "endDate": "2026-08-01",
  "endTime": "12:00",
  "location": "Seminar Hall",
  "organizer": "Tech Club",
  "category": "Workshop",
  "registrationUrl": "https://example.com/register",
  "capacity": "100",
  "tags": "AI, workshop",
  "isOnline": false,
  "isFree": true
}
```

## Troubleshooting

- If the popup says it cannot detect the page, open the exact create-event URL.
- The **Fill OpenOrbit form** button now injects its page helper on demand, so a
  tab opened before the extension was installed (or reached through in-app
  navigation) is filled without a manual refresh. If a fill still fails, use
  **Open event page** to reload create-event and try again.
- If OpenOrbit renames a field, the extension reports it as “Not found” rather
  than filling the wrong field.
- Browser extensions cannot safely preselect a local image file without a user
  gesture; choose the event image manually on the page.
