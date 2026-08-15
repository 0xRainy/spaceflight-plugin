// Spaceflight Omarchy panel helpers (Power of Ten — small, bounded).
.pragma library

var MAX_UPCOMING = 8
var MAX_TEXT = 80

function clampInt(n, lo, hi, fallback) {
  var x = Number(n)
  if (!isFinite(x))
    return fallback
  if (x < lo)
    return lo
  if (x > hi)
    return hi
  return Math.floor(x)
}

function clip(s, n) {
  var t = String(s || "")
  var lim = clampInt(n, 1, MAX_TEXT, 40)
  if (t.length <= lim)
    return t
  return t.slice(0, lim - 1) + "…"
}

function emptyPanel() {
  return {
    ok: false,
    onboard: true,
    featured: {},
    upcoming: [],
    age_sec: null,
    text: "🚀  …",
    klass: "pending",
    bar_style: "text",
    wizard_needed: true
  }
}

function parseCache(raw) {
  if (!raw)
    return emptyPanel()
  var data
  try {
    data = JSON.parse(String(raw))
  } catch (e) {
    return emptyPanel()
  }
  if (!data || typeof data !== "object")
    return emptyPanel()
  var panel = data.panel
  if (!panel || typeof panel !== "object")
    panel = { ok: false, onboard: true, featured: {}, upcoming: [] }
  var up = []
  var src = panel.upcoming
  if (Array.isArray(src)) {
    var i
    for (i = 0; i < src.length && i < MAX_UPCOMING; i++) {
      if (src[i] && typeof src[i] === "object")
        up.push(src[i])
    }
  }
  var style = String(panel.bar_style || "text")
  if (style !== "icon" && style !== "text")
    style = "text"
  return {
    ok: panel.ok === true,
    onboard: panel.onboard === true || !panel.ok,
    featured: (panel.featured && typeof panel.featured === "object") ? panel.featured : {},
    upcoming: up,
    age_sec: panel.age_sec,
    text: String(data.text || "🚀  …"),
    klass: String(data["class"] || data.alt || "unknown"),
    bar_style: style,
    wizard_needed: panel.wizard_needed === true
  }
}

function ageLabel(age) {
  var n = Number(age)
  if (!isFinite(n) || n < 0)
    return "—"
  if (n < 90)
    return Math.floor(n) + "s"
  if (n < 3600)
    return Math.floor(n / 60) + "m"
  return (n / 3600).toFixed(1) + "h"
}

function featuredName(f) {
  if (!f)
    return "No upcoming launches"
  return clip(f.name || "Unknown mission", 40)
}

function locationLine(f) {
  if (!f)
    return ""
  var parts = []
  if (f.pad)
    parts.push(String(f.pad))
  if (f.location)
    parts.push(String(f.location))
  return clip(parts.join(", "), 56)
}
