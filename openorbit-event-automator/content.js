(() => {
  // Guard against double-registration. The popup re-injects this file on demand
  // (see popup.js -> ensureContentScript) so that filling still works when the
  // tab was opened before the extension loaded, or after a client-side SPA
  // navigation. Without this guard, re-injection would attach a second message
  // listener and both would try to answer the same sendResponse.
  if (window.__openOrbitAutomatorLoaded) return;
  window.__openOrbitAutomatorLoaded = true;

  const FIELD_RULES = {
    title: ["event title", "title", "event name", "name of event"],
    description: ["event description", "description", "about event", "details"],
    startDate: ["start date", "event date", "date"],
    startTime: ["start time", "time"],
    endDate: ["end date"],
    endTime: ["end time"],
    location: ["venue", "location", "event venue", "address"],
    organizer: ["organizer", "organiser", "host", "club", "organization"],
    category: ["category", "event category", "type"],
    registrationUrl: ["registration url", "registration link", "event link", "website", "url"],
    capacity: ["capacity", "max attendees", "maximum attendees", "seats"],
    prizePool: ["prize pool", "prize", "prizes"],
    entryFee: ["entry fee", "registration fee", "fee", "price"],
    contacts: ["contacts", "contact", "contact details", "phone", "queries"],
    socialUrl: ["social url", "instagram", "social link", "post url"],
    tags: ["tags", "keywords"],
    isOnline: ["online event", "virtual event", "is online", "online"],
    isFree: ["free event", "is free", "free"]
  };

  const normalize = (value) => String(value || "")
    .toLowerCase()
    .replace(/[*:()[\]_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  // Many apps (OpenOrbit included) render the field label as a separate element
  // sitting just before the input, with no `for`/`id` link and no aria wiring.
  // Walk up a few wrappers and grab the nearest preceding label-like text.
  function nearbyLabelText(el) {
    let node = el;
    for (let depth = 0; depth < 4 && node && node !== document.body; depth++) {
      let sib = node.previousElementSibling;
      let hops = 0;
      while (sib && hops < 3) {
        const lbl = sib.matches?.("label") ? sib : sib.querySelector?.("label");
        if (lbl && lbl.textContent.trim()) return lbl.textContent.trim();
        const text = sib.textContent.trim();
        if (text && text.length <= 60 && !sib.querySelector?.("input, textarea, select")) {
          return text;
        }
        sib = sib.previousElementSibling;
        hops++;
      }
      node = node.parentElement;
    }
    return "";
  }

  function elementText(el) {
    const labels = el.labels ? [...el.labels].map((x) => x.textContent).join(" ") : "";
    const parentText = el.closest("label")?.textContent || "";
    // Also look at a describing element referenced by aria-labelledby, and a
    // preceding label/legend sibling, which many component libraries use.
    const labelledById = el.getAttribute("aria-labelledby");
    const labelledBy = labelledById
      ? labelledById.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" ")
      : "";
    return normalize([
      labels, parentText, labelledBy, nearbyLabelText(el), el.getAttribute("aria-label"),
      el.placeholder, el.name, el.id, el.getAttribute("data-testid")
    ].filter(Boolean).join(" "));
  }

  function score(el, aliases, key) {
    const haystack = elementText(el);
    let best = 0;
    for (const alias of aliases) {
      const needle = normalize(alias);
      if (!needle) continue;
      if (haystack === needle) best = Math.max(best, 100);
      else if (haystack.startsWith(`${needle} `)) best = Math.max(best, 80);
      else if (haystack.includes(needle)) best = Math.max(best, 60);
    }
    const type = (el.type || "").toLowerCase();
    if (key.toLowerCase().includes("date") && type === "date") best += 25;
    if (key.toLowerCase().includes("time") && type === "time") best += 25;
    if (key === "description" && el.tagName === "TEXTAREA") best += 20;
    if ((key === "isOnline" || key === "isFree") && ["checkbox", "radio"].includes(type)) best += 25;
    if (key === "registrationUrl" && type === "url") best += 15;
    if (key === "capacity" && type === "number") best += 15;
    return best;
  }

  function visibleControls() {
    return [...document.querySelectorAll(
      "input:not([type=hidden]):not([type=file]), textarea, select, [contenteditable=true]"
    )].filter((el) => !el.disabled && el.offsetParent !== null);
  }

  function candidatesFor(key, controls) {
    return controls
      .map((el) => ({ el, score: score(el, FIELD_RULES[key], key) }))
      .filter((x) => x.score >= 60)
      .sort((a, b) => b.score - a.score);
  }

  function setNativeValue(el, value) {
    if (el.tagName === "SELECT") {
      const wanted = normalize(value);
      const option = [...el.options].find((o) =>
        normalize(o.value) === wanted || normalize(o.textContent) === wanted
      );
      if (!option) return false;
      el.value = option.value;
    } else if (el.isContentEditable) {
      el.textContent = value;
    } else if (["checkbox", "radio"].includes(el.type)) {
      const checked = Boolean(value);
      const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "checked");
      descriptor?.set?.call(el, checked);
      if (!descriptor?.set) el.checked = checked;
    } else {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
      descriptor?.set?.call(el, String(value));
      if (!descriptor?.set) el.value = String(value);
    }
    // React/Vue-style controlled inputs listen for these to sync their state.
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
    el.style.outline = "3px solid #22c55e";
    el.style.outlineOffset = "2px";
    return true;
  }

  function fill(data) {
    if (data.rawText) data.description = data.rawText;
    const filled = [];
    const missing = [];
    const used = new Set();
    const controls = visibleControls();

    for (const key of Object.keys(FIELD_RULES)) {
      const value = data[key];
      if (value === "" || value == null || (typeof value === "boolean" && value === false)) continue;
      const ranked = candidatesFor(key, controls);
      const choice = ranked.find(({ el }) => !used.has(el));
      if (!choice || !setNativeValue(choice.el, value)) {
        missing.push(key);
        continue;
      }
      used.add(choice.el);
      filled.push(key);
    }

    window.scrollTo({ top: 0, behavior: "smooth" });

    // If we matched nothing, report what the page actually exposes so the field
    // rules can be tuned to this form's real labels.
    const result = { ok: true, filled, missing };
    if (!filled.length) {
      result.pageFields = controls.slice(0, 20).map((el) => {
        const tag = el.tagName.toLowerCase() + (el.type ? `[${el.type}]` : "");
        return `${tag}: "${elementText(el).slice(0, 50) || "(no label)"}"`;
      });
    }
    return result;
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "PING") {
      sendResponse({ ok: true, ready: true });
      return;
    }
    if (message?.type !== "FILL_EVENT") return;
    try {
      sendResponse(fill(message.data || {}));
    } catch (error) {
      sendResponse({ ok: false, error: error?.message || "Unexpected page error." });
    }
  });
})();
