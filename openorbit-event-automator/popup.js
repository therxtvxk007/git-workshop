"use strict";

const CREATE_EVENT_URL = "https://openorbit.app/create-event";
const STORAGE_KEY = "openorbit:lastTemplate";

// Every editable field id in popup.html, in display order.
const FIELD_IDS = [
  "title", "description", "startDate", "startTime", "endDate", "endTime",
  "location", "organizer", "category", "registrationUrl", "capacity",
  "prizePool", "entryFee", "contacts", "socialUrl", "tags"
];
const CHECK_IDS = ["isOnline", "isFree"];

const $ = (id) => document.getElementById(id);
const resultEl = () => $("result");

function setResult(message, kind) {
  const el = resultEl();
  el.textContent = message || "";
  el.className = kind || "";
}

/* ------------------------------------------------------------------ *
 *  Reading / writing the review form
 * ------------------------------------------------------------------ */

function collectData() {
  const data = {};
  for (const id of FIELD_IDS) data[id] = $(id).value.trim();
  for (const id of CHECK_IDS) data[id] = $(id).checked;
  data.rawText = $("rawText").value.trim();
  return data;
}

function applyData(data = {}) {
  for (const id of FIELD_IDS) {
    if (id in data && data[id] != null) $(id).value = data[id];
  }
  for (const id of CHECK_IDS) {
    if (id in data) $(id).checked = Boolean(data[id]);
  }
  if ("rawText" in data && data.rawText != null) $("rawText").value = data.rawText;
}

function saveTemplate(data) {
  try {
    chrome.storage?.local?.set({ [STORAGE_KEY]: data });
  } catch (_) { /* storage is best-effort */ }
}

/* ------------------------------------------------------------------ *
 *  Announcement parser
 * ------------------------------------------------------------------ */

const MONTHS = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4,
  may: 5, jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9,
  september: 9, oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12
};

const pad = (n) => String(n).padStart(2, "0");

function parseDate(raw, fallbackYear) {
  if (!raw) return "";
  const s = String(raw).trim();

  let m = s.match(/\b(\d{4})-(\d{1,2})-(\d{1,2})\b/);
  if (m) return `${m[1]}-${pad(m[2])}-${pad(m[3])}`;

  // DD/MM/YYYY or DD-MM-YYYY or DD.MM.YY (day-first, common outside the US)
  m = s.match(/\b(\d{1,2})[\/.\-](\d{1,2})[\/.\-](\d{2,4})\b/);
  if (m) {
    let [, d, mo, y] = m;
    if (y.length === 2) y = "20" + y;
    if (+mo >= 1 && +mo <= 12 && +d >= 1 && +d <= 31) return `${y}-${pad(mo)}-${pad(d)}`;
  }

  // "1st August 2026", "August 1, 2026", "1 Aug 2026"
  const monthMatch = s.toLowerCase().match(
    /\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b/
  );
  if (monthMatch) {
    const mo = MONTHS[monthMatch[1]];
    const yearMatch = s.match(/\b(20\d{2})\b/);
    const year = yearMatch ? yearMatch[1] : String(fallbackYear || new Date().getFullYear());
    const rest = s.replace(/\b20\d{2}\b/, " ");
    const dayMatch = rest.match(/\b(\d{1,2})(?:st|nd|rd|th)?\b/);
    if (dayMatch) return `${year}-${pad(mo)}-${pad(dayMatch[1])}`;
  }
  return "";
}

function parseTime(token) {
  if (!token) return "";
  const m = String(token).match(/\b(\d{1,2})(?::|\.)?(\d{2})?\s*([ap])\.?m\.?/i)
    || String(token).match(/\b(\d{1,2}):(\d{2})\b/);
  if (!m) return "";
  let h = parseInt(m[1], 10);
  const min = m[2] ? m[2] : "00";
  const mer = (m[3] || "").toLowerCase();
  if (mer === "p" && h < 12) h += 12;
  if (mer === "a" && h === 12) h = 0;
  if (h > 23 || +min > 59) return "";
  return `${pad(h)}:${min}`;
}

function timeTokens(raw) {
  return String(raw).match(/\b\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?|\b\d{1,2}:\d{2}\b/gi) || [];
}

// Label -> field, matched against the text before a ":" / "-" separator.
const LABEL_MAP = [
  ["endDate", ["end date", "to date", "ends on"]],
  ["startDate", ["start date", "event date", "date", "when", "on"]],
  ["endTime", ["end time", "ends at"]],
  ["startTime", ["start time", "time", "timing", "timings", "at"]],
  ["location", ["venue", "location", "place", "address", "where", "hall"]],
  ["organizer", ["organizer", "organiser", "organized by", "organised by", "hosted by", "host", "presented by", "club", "conducted by"]],
  ["category", ["category", "event type", "type"]],
  ["registrationUrl", ["registration link", "registration url", "register here", "register", "registration", "rsvp", "form", "apply", "link"]],
  ["capacity", ["capacity", "seats", "seat limit", "limit", "max attendees", "slots"]],
  ["prizePool", ["prize pool", "prize money", "prizes", "prize", "rewards", "reward", "cash prize"]],
  ["entryFee", ["entry fee", "registration fee", "participation fee", "fees", "fee", "price", "cost", "ticket"]],
  ["contacts", ["contact details", "contacts", "contact", "for queries", "queries", "call", "whatsapp", "reach us", "reach out"]],
  ["tags", ["tags", "keywords"]],
  ["title", ["event title", "event name", "title", "event"]]
];

const stripDecor = (line) => line
  .replace(/[\p{Extended_Pictographic}\u{FE0F}]/gu, "") // drop emojis first
  .replace(/^[\s•‣●▪■□◆▶►–—\-*·>]+/, "")               // leading bullets / *bold*
  .replace(/[\s*_~]+$/, "")                             // trailing markdown emphasis
  .trim();

const labelKey = (s) => s.toLowerCase().replace(/[^a-z\s]/g, " ").replace(/\s+/g, " ").trim();

function matchLabel(labelPart) {
  const key = labelKey(labelPart);
  if (!key) return null;
  for (const [field, aliases] of LABEL_MAP) {
    for (const alias of aliases) {
      if (key === alias || key.startsWith(alias + " ") || key.endsWith(" " + alias) || key === alias) {
        return field;
      }
    }
  }
  // looser containment pass
  for (const [field, aliases] of LABEL_MAP) {
    if (aliases.some((alias) => key.includes(alias))) return field;
  }
  return null;
}

function parseAnnouncement(text) {
  const out = {};
  const rawLines = text.split(/\r?\n/);
  const cleanLines = rawLines.map(stripDecor).filter((l) => l.length);

  // 1) Label: value lines
  for (const line of cleanLines) {
    const sep = line.match(/^([^:]{1,40}?)\s*[:–—-]\s+(.+)$/);
    if (!sep) continue;
    const field = matchLabel(sep[1]);
    const value = sep[2].trim();
    if (field && !out[field]) out[field] = value;
  }

  // 2) Title fallback: first decorated heading line that isn't a label line.
  if (!out.title) {
    const heading = rawLines.map(stripDecor).find((l) =>
      l.length >= 3 && l.length <= 90 && !/^[^:]{1,40}?\s*[:–—-]\s+/.test(l) && !/^https?:\/\//i.test(l)
    );
    if (heading) out.title = heading;
  }

  // 3) Dates
  const year = new Date().getFullYear();
  if (out.startDate) out.startDate = parseDate(out.startDate, year) || "";
  if (out.endDate) out.endDate = parseDate(out.endDate, year) || "";
  if (!out.startDate) {
    for (const line of cleanLines) {
      const d = parseDate(line, year);
      if (d) { out.startDate = d; break; }
    }
  }

  // 4) Times — a single "time" field may hold a range like "10 AM - 12 PM".
  const timeSource = out.startTime || cleanLines.find((l) => /\d\s*[ap]\.?m\.?|\d{1,2}:\d{2}/i.test(l)) || "";
  const tokens = timeTokens(timeSource);
  if (tokens.length) {
    out.startTime = parseTime(tokens[0]) || "";
    if (tokens.length > 1 && !out.endTime) out.endTime = parseTime(tokens[1]) || "";
  }
  if (out.endTime && !/\d/.test(out.endTime)) out.endTime = parseTime(out.endTime) || "";
  if (out.endTime) out.endTime = parseTime(out.endTime) || out.endTime;

  // 5) URLs — classify social vs registration.
  const urls = text.match(/https?:\/\/[^\s)]+/gi) || [];
  for (const url of urls) {
    const clean = url.replace(/[.,)]+$/, "");
    if (/instagram\.com|facebook\.com|fb\.me|twitter\.com|x\.com|linkedin\.com|youtu/i.test(clean)) {
      if (!out.socialUrl) out.socialUrl = clean;
    } else if (!out.registrationUrl) {
      out.registrationUrl = clean;
    }
  }
  // If registration was captured as a label with the URL inside, extract just the URL.
  if (out.registrationUrl && !/^https?:\/\//i.test(out.registrationUrl)) {
    const u = out.registrationUrl.match(/https?:\/\/[^\s)]+/i);
    out.registrationUrl = u ? u[0].replace(/[.,)]+$/, "") : "";
  }

  // 6) Capacity -> digits only
  if (out.capacity) {
    const n = out.capacity.match(/\d+/);
    out.capacity = n ? n[0] : "";
  }

  // 7) Tags from hashtags (fallback / supplement)
  if (!out.tags) {
    const hashtags = text.match(/#([\p{L}0-9_]+)/gu) || [];
    if (hashtags.length) out.tags = hashtags.map((h) => h.slice(1)).join(", ");
  }

  // 8) Contacts fallback: lines carrying a phone number.
  if (!out.contacts) {
    const phones = cleanLines.filter((l) => /(?:\+?\d[\d\s-]{7,}\d)/.test(l));
    if (phones.length) out.contacts = phones.join("\n");
  }

  // 9) Online / free flags
  const lower = text.toLowerCase();
  out.isOnline = /\b(online|virtual|webinar|zoom|google meet|meet\.google|ms teams|microsoft teams)\b/.test(lower);
  const feeText = (out.entryFee || "").toLowerCase();
  out.isFree = /\bfree\b|no fee|no charge|free entry|free of cost/.test(feeText) ||
    (/\bfree\b/.test(lower) && !/\d\s*(?:₹|rs|inr|\$)/i.test(feeText));

  // 10) Description is always the verbatim announcement.
  out.description = text.trim();

  return out;
}

/* ------------------------------------------------------------------ *
 *  Talking to the page (the actual fix)
 * ------------------------------------------------------------------ */

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function onCreateEventPage(url) {
  return typeof url === "string" && url.startsWith(CREATE_EVENT_URL);
}

// Guarantees content.js is present before we message it. The manifest only
// injects it at page load, so a tab opened before install — or reached via a
// client-side SPA navigation — would have no receiver and the fill would
// silently do nothing. Injecting here (idempotent thanks to the guard flag in
// content.js) makes the fill reliable.
async function ensureContentScript(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
}

async function sendToPage(tabId, message) {
  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (_) {
    await ensureContentScript(tabId);
    return await chrome.tabs.sendMessage(tabId, message);
  }
}

async function handleFill() {
  const tab = await getActiveTab();
  if (!tab || !onCreateEventPage(tab.url)) {
    setResult("Open https://openorbit.app/create-event in the active tab, then try again.", "error");
    return;
  }
  if (!$("title").value.trim()) {
    setResult("Add an event title before filling.", "error");
    return;
  }

  const data = collectData();
  saveTemplate(data);

  setResult("Filling…");
  try {
    const res = await sendToPage(tab.id, { type: "FILL_EVENT", data });
    if (!res || !res.ok) {
      setResult(res?.error || "The page reported no fillable fields.", "error");
      return;
    }
    const lines = [`Filled ${res.filled.length} field${res.filled.length === 1 ? "" : "s"}: ${res.filled.join(", ") || "—"}`];
    if (res.missing.length) {
      lines.push(`Not found on this step (fill manually or advance the wizard): ${res.missing.join(", ")}`);
    }
    if (res.pageFields && res.pageFields.length) {
      lines.push("", "Fields the extension can see on this page:", ...res.pageFields);
    }
    setResult(lines.join("\n"), res.filled.length && !res.missing.length ? "ok" : "");
  } catch (err) {
    setResult(
      "Couldn't reach the OpenOrbit page. Refresh the create-event tab and try again.\n" +
      (err?.message || ""),
      "error"
    );
  }
}

/* ------------------------------------------------------------------ *
 *  Wiring
 * ------------------------------------------------------------------ */

async function refreshStatus() {
  const dot = $("statusDot");
  try {
    const tab = await getActiveTab();
    dot.classList.toggle("ready", onCreateEventPage(tab?.url));
    dot.title = onCreateEventPage(tab?.url)
      ? "OpenOrbit create-event page detected"
      : "Open the OpenOrbit create-event page";
  } catch (_) {
    dot.classList.remove("ready");
  }
}

function wire() {
  $("parse").addEventListener("click", () => {
    const text = $("rawText").value.trim();
    if (!text) {
      setResult("Paste the event announcement first.", "error");
      return;
    }
    const parsed = parseAnnouncement(text);
    applyData({ ...parsed, rawText: text });
    const found = FIELD_IDS.filter((id) => $(id).value.trim()).length;
    setResult(`Extracted ${found} field${found === 1 ? "" : "s"}. Review, then Fill OpenOrbit form.`, "ok");
  });

  $("fill").addEventListener("click", handleFill);

  $("openPage").addEventListener("click", async () => {
    const tab = await getActiveTab();
    if (onCreateEventPage(tab?.url)) {
      chrome.tabs.reload(tab.id);
    } else {
      chrome.tabs.create({ url: CREATE_EVENT_URL });
    }
  });

  $("copyJson").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(collectData(), null, 2));
      setResult("Template copied to clipboard as JSON.", "ok");
    } catch (_) {
      setResult("Clipboard write was blocked by the browser.", "error");
    }
  });

  $("pasteJson").addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      applyData(JSON.parse(text));
      setResult("Imported template from clipboard.", "ok");
    } catch (_) {
      setResult("Clipboard did not contain valid template JSON.", "error");
    }
  });

  $("clear").addEventListener("click", () => {
    for (const id of [...FIELD_IDS, "rawText"]) $(id).value = "";
    for (const id of CHECK_IDS) $(id).checked = false;
    setResult("Cleared.", "");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wire();
  refreshStatus();
  try {
    chrome.storage?.local?.get(STORAGE_KEY, (stored) => {
      if (stored && stored[STORAGE_KEY]) applyData(stored[STORAGE_KEY]);
    });
  } catch (_) { /* ignore */ }
});
