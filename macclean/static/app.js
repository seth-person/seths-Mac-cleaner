"use strict";

// ---------------------------------------------------------------- helpers
const TOKEN = window.MACCLEAN_TOKEN;
const $ = (s) => document.querySelector(s);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v; // only ever used with static strings
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function get(url) {
  const r = await fetch(url);
  const data = await r.json();
  if (data.error && !data.roots) throw new Error(data.error);
  return data;
}
async function post(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Macclean-Token": TOKEN },
    body: JSON.stringify(body || {}),
  });
  if (r.status === 403) throw new Error("Session expired: reload the page");
  const data = await r.json();
  if (data.error && data.ok === undefined) throw new Error(data.error);
  return data;
}

const fmt = {
  size(n) {
    n = Number(n) || 0;
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (Math.abs(n) >= 1000 && i < u.length - 1) { n /= 1000; i++; }
    return i === 0 ? `${n} B` : `${n >= 100 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`;
  },
  count: (n) => Number(n || 0).toLocaleString(),
  age(days) {
    if (days < 1) return "today";
    if (days < 2) return "yesterday";
    if (days < 45) return `${Math.floor(days)}d`;
    if (days < 545) return `${Math.round(days / 30)}mo`;
    return `${(days / 365).toFixed(1)}y`;
  },
  ago: (ts) => (ts ? fmt.age((Date.now() / 1000 - ts) / 86400) : "—"),
  pct: (a, b) => (b ? `${((100 * a) / b).toFixed(a / b < 0.1 ? 1 : 0)}%` : "—"),
};

let HOME = "";
const short = (p) => (p && HOME && p.startsWith(HOME) ? "~" + p.slice(HOME.length) : p || "");
const ICLOUD_REL = "/Library/Mobile Documents/com~apple~CloudDocs";
const pretty = (p) => short(p).replace("~" + ICLOUD_REL, "iCloud Drive");
const whereName = (p) => (p === HOME ? "your home folder" : p === "/" ? "the whole disk" : pretty(p));

// Category groups. Order = colour order; colour follows the group, never rank.
const GROUPS = [
  { id: "music", label: "Music & Ableton", cats: ["audio", "ableton", "plugin"], color: "var(--c1)" },
  { id: "video", label: "Video", cats: ["video"], color: "var(--c2)" },
  { id: "image", label: "Images", cats: ["image"], color: "var(--c3)" },
  { id: "document", label: "Documents", cats: ["document"], color: "var(--c4)" },
  { id: "apps", label: "Apps & installers", cats: ["app", "installer"], color: "var(--c5)" },
  { id: "archive", label: "Archives", cats: ["archive"], color: "var(--c6)" },
  { id: "code", label: "Code", cats: ["code"], color: "var(--c7)" },
  { id: "appdata", label: "App data (~/Library)", cats: ["library"], color: "var(--c8)" },
  { id: "system", label: "macOS & system", cats: ["system"], color: "var(--c-system)" },
  { id: "other", label: "Other", cats: ["other", "folder"], color: "var(--c-other)" },
];
const groupOf = (cat) => GROUPS.find((g) => g.cats.includes(cat)) || GROUPS[GROUPS.length - 1];
const CAT_LABEL = { audio: "Audio", ableton: "Ableton", plugin: "Plugin", video: "Video", image: "Image",
  document: "Document", app: "App", installer: "Installer", archive: "Archive", code: "Code",
  library: "App data", system: "System", other: "Other", folder: "Folder" };

function toast(msg, ms = 4000) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

const tip = {
  show(e, lines) {
    const t = $("#tooltip");
    t.replaceChildren(...lines.map((l, i) => h("div", { class: i ? "ink2" : "" }, l)));
    t.hidden = false;
    tip.move(e);
  },
  move(e) {
    const t = $("#tooltip");
    const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 8);
    const y = Math.min(e.clientY + 14, window.innerHeight - t.offsetHeight - 8);
    t.style.left = x + "px";
    t.style.top = y + "px";
  },
  hide() { $("#tooltip").hidden = true; },
};

function modal(title, body, buttons) {
  return new Promise((resolve) => {
    const d = $("#modal");
    const close = (v) => { d.close(); resolve(v); };
    $("#modal-body").replaceChildren(
      h("h2", {}, title), body,
      h("div", { class: "toolbar", style: { marginTop: "14px", justifyContent: "flex-end" } },
        (buttons || [{ label: "Close", value: false }]).map((b) =>
          h("button", { class: "btn " + (b.cls || ""), onclick: () => close(b.value) }, b.label))));
    d.onclose = () => resolve(false);
    d.showModal();
  });
}

// "Safe" = rebuilt automatically or provably redundant; anything else is "Check first".
function riskPill(risk) {
  return risk === "safe"
    ? h("span", { class: "status good", title: "Rebuilt automatically, or an exact copy of something you keep" }, h("span", { class: "dot" }), "Safe")
    : h("span", { class: "status warning", title: "Probably not needed, but only you can tell" }, h("span", { class: "dot" }), "Check first");
}

// items: [{label, detail, group?, why?}] - grouped by `group` when given.
function confirmItems(title, items, okLabel, warning) {
  const byGroup = new Map();
  for (const it of items.slice(0, 300)) {
    const g = it.group || "";
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(it);
  }
  const list = h("div", {}, [...byGroup].map(([g, its]) => h("div", { style: { marginBottom: "10px" } },
    g ? h("h3", { style: { margin: "6px 0 2px" } }, g) : null,
    its[0].why ? h("div", { class: "ink2", style: { fontSize: "12px", marginBottom: "4px" } }, its[0].why) : null,
    h("table", {}, h("tbody", {}, its.map((it) =>
      h("tr", {}, h("td", { class: "name" }, h("span", { class: "trunc" }, it.label)),
        h("td", { class: "ink2", style: { width: "45%" } }, h("span", { class: "trunc" }, it.detail || "")))))))));
  const body = h("div", {},
    [].concat(warning || []).map((w) => h("div", { class: "warn" }, w)),
    h("p", { class: "ink2" }, "Nothing is deleted yet: trashed items go to your Trash, and everything can be undone from History until you empty it."),
    h("div", { style: { maxHeight: "50vh", overflow: "auto" } }, list),
    items.length > 300 ? h("p", { class: "muted" }, `…and ${items.length - 300} more`) : null);
  return modal(title, body, [{ label: "Cancel", value: false }, { label: okLabel, value: true, cls: "primary" }]);
}

// items may carry `bytes` (not sent to the server's logic) so we can say how much went to the Trash.
async function runActions(items) {
  const res = await post("/api/apply", { items });
  const okPaths = new Set(res.results.filter((r) => r.ok).map((r) => r.path));
  const ok = okPaths.size;
  const bad = res.results.filter((r) => !r.ok);
  const trashed = items.filter((i) => i.action !== "move" && okPaths.has(i.path));
  const trashedBytes = trashed.reduce((a, i) => a + (i.bytes || 0), 0);
  const parts = [];
  if (trashed.length) {
    parts.push(h("p", {}, `${trashed.length} item${trashed.length === 1 ? "" : "s"}${trashedBytes ? ` (${fmt.size(trashedBytes)})` : ""} moved to the Trash. `,
      h("b", {}, "The space comes back when you empty the Trash"), " (Finder → Empty Trash). Until then, you can undo any of it from History."));
  } else if (ok) {
    parts.push(h("p", {}, `${ok} item${ok === 1 ? "" : "s"} moved. Undo from History if needed.`));
  }
  if (bad.length) {
    parts.push(h("p", {}, `${bad.length} skipped:`), h("ul", {}, bad.map((b) => h("li", {}, `${short(b.path)}: ${b.error}`))));
  }
  if (trashed.length || bad.length) {
    const v = await modal(bad.length && !ok ? "Nothing was changed" : "Done", h("div", {}, parts),
      trashed.length ? [{ label: "Open Trash", value: "trash" }, { label: "OK", value: false, cls: "primary" }] : undefined);
    if (v === "trash") post("/api/open-trash").then((r) => { if (!r.ok) toast(r.error); });
  } else {
    toast(`${ok} item${ok === 1 ? "" : "s"} moved. Undo from History if needed.`);
  }
  return res;
}

function reveal(path) {
  post("/api/reveal", { path }).then((r) => { if (!r.ok) toast(r.error); }).catch((e) => toast(e.message));
}

// ------------------------------------------------------------ action bar
const actionbar = {
  set(count, label, buttons) {
    const bar = $("#actionbar");
    if (!count) { bar.hidden = true; return; }
    bar.replaceChildren(h("span", {}, label), ...buttons);
    bar.hidden = false;
  },
  clear() { $("#actionbar").hidden = true; },
};

// ------------------------------------------------------------------ chrome
let STATUS = null;
let wasRunning = false;

async function refreshStatus() {
  try {
    STATUS = await get("/api/status");
  } catch (e) {
    return;
  }
  HOME = STATUS.home;
  renderDisk();
  renderScan();
  if (wasRunning && !STATUS.scan.running) {
    if (STATUS.scan.error) toast("Scan stopped: " + STATUS.scan.error);
    else toast("Scan finished.");
    route();
  }
  wasRunning = STATUS.scan.running;
  setTimeout(refreshStatus, STATUS.scan.running ? 1000 : 15000);
}

function renderDisk() {
  const d = STATUS.disk;
  $("#disk").replaceChildren(
    h("div", { class: "label" },
      h("span", {}, h("b", {}, fmt.size(d.used)), " used of ", fmt.size(d.total)),
      h("span", { class: "ink2" }, fmt.size(d.free), " free")),
    h("div", { class: "bar", title: `${fmt.pct(d.used, d.total)} full` },
      h("span", { style: { width: fmt.pct(d.used, d.total) } })));
  const m = STATUS.meta;
  $("#nav-foot").replaceChildren(
    h("div", {}, m.scanned_at ? `Last scan ${m.scanned_at}` : "Not scanned yet"),
    h("a", { href: "#", onclick: (e) => { e.preventDefault(); showAbout(); } }, `Version ${STATUS.version} · Updates`));
}

function renderScan() {
  const s = STATUS.scan;
  const el = $("#scan");
  if (s.running) {
    el.replaceChildren(
      h("span", { class: "ink2" }, `${s.phase}… `, h("span", { class: "num" }, fmt.count(s.files)), " files · ", fmt.size(s.bytes)),
      h("button", { class: "btn small", onclick: () => post("/api/scan/cancel") }, "Cancel"));
    return;
  }
  const where = h("select", { "aria-label": "What to scan" },
    h("option", { value: "" }, "Home folder"),
    h("option", { value: "/" }, "Entire disk"));
  el.replaceChildren(where, h("button", {
    class: "btn primary",
    onclick: async () => {
      const r = await post("/api/scan", { roots: where.value ? [where.value] : null });
      if (!r.ok) toast(r.error);
      wasRunning = true;
      refreshStatus();
    },
  }, STATUS.has_scan ? "Rescan" : "Scan now"));
}

// ------------------------------------------------------------------ router
const VIEWS = {};
function route() {
  const view = (location.hash || "#overview").slice(1).split("?")[0];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  actionbar.clear();
  tip.hide();
  const root = $("#view");
  root.replaceChildren(h("p", { class: "muted" }, "Loading…"));
  (VIEWS[view] || VIEWS.overview)(root).catch((e) => {
    root.replaceChildren(h("div", { class: "empty" }, h("h2", {}, "Something went wrong"), h("p", {}, e.message)));
  });
}
window.addEventListener("hashchange", route);

function noScan(root) {
  root.replaceChildren(h("div", { class: "card empty" },
    h("h2", {}, "No scan yet"),
    h("p", {}, "Press ", h("b", {}, "Scan now"), " (top right) to measure your home folder. Choose ",
      h("b", {}, "Entire disk"), " to include apps and macOS."),
    h("p", { class: "ink2" }, "For the full picture, give ", h("b", {}, "Full Disk Access"),
      " to Mac Cleaner (or to Terminal, if you run it from there) in System Settings → Privacy & Security, then quit and reopen it.")));
}

function tile(k, v, d, onclick) {
  return h("div", { class: "card tile" + (onclick ? " link" : ""), onclick }, h("div", { class: "k" }, k),
    h("div", { class: "v" }, v), h("div", { class: "d" }, d));
}

// ---------------------------------------------------------------- overview
VIEWS.overview = async (root) => {
  const [ov, inbox, purge, abl] = await Promise.all([
    get("/api/overview"), get("/api/inbox"), get("/api/purge"), get("/api/ableton")]);
  if (!ov.has_scan) return noScan(root);
  updateBadges(inbox, purge);
  const m = ov.meta;

  const ibCount = inbox.inboxes.reduce((a, b) => a + b.count, 0);
  const ibSize = inbox.inboxes.reduce((a, b) => a + b.size, 0);
  const ibStale = inbox.inboxes.reduce((a, b) => a + b.stale, 0);
  const safe = purge.findings.filter((f) => f.risk === "safe" && f.action).reduce((a, f) => a + f.alloc, 0);
  const review = purge.findings.filter((f) => f.risk === "review" && f.action).reduce((a, f) => a + f.alloc, 0);
  const t = abl.totals;

  const hero = h("div", { class: "card hero" },
    h("p", { class: "lead" },
      safe ? [h("b", {}, fmt.size(safe)), " is ready to clean up"] : "Nothing is ready to clean up right away",
      review ? [", and ", h("b", {}, fmt.size(review)), " more is worth a look"] : "",
      ". ", h("b", {}, `${ibCount} item${ibCount === 1 ? "" : "s"}`), " are sitting in Downloads and Desktop",
      ibStale ? [`, ${ibStale} of them untouched for ${inbox.stale_days}+ days`] : "", "."),
    h("div", { class: "toolbar", style: { margin: 0 } },
      h("a", { class: "btn primary", href: "#cleanup" }, "Start cleanup"),
      h("a", { class: "btn", href: "#inbox" }, "Sort Downloads & Desktop"),
      t.needs_collect || t.outside_library ? h("a", { class: "btn", href: "#music" }, "Tidy Ableton projects") : null));

  const tiles = h("div", { class: "grid tiles" },
    tile("Space used by your files", fmt.size(m.total_alloc), `${fmt.count(m.total_files)} files`),
    tile("Catch-alls", `${ibCount} items`, `${fmt.size(ibSize)} · ${ibStale} untouched ${inbox.stale_days}+ days`, () => (location.hash = "#inbox")),
    tile("Ready to clean", fmt.size(safe), `+ ${fmt.size(review)} to check first`, () => (location.hash = "#cleanup")),
    tile("Ableton projects", fmt.count(t.projects),
      `${t.outside_library} outside your projects folder · ${t.needs_collect} need Collect All`, () => (location.hash = "#music")),
    ov.cloud ? tile("iCloud Drive", fmt.size(ov.cloud.size), `${fmt.size(ov.cloud.alloc)} downloaded to this Mac`) : null);

  // share of space by group
  const byGroup = new Map(GROUPS.map((g) => [g.id, { g, alloc: 0, count: 0 }]));
  for (const c of ov.categories) {
    const e = byGroup.get(groupOf(c.category).id);
    e.alloc += c.alloc;
    e.count += c.count;
  }
  const total = [...byGroup.values()].reduce((a, b) => a + b.alloc, 0);
  const rows = [...byGroup.values()].filter((r) => r.alloc > 0);
  const share = h("div", { class: "share", role: "img", "aria-label": "Space by type" },
    rows.map((r) => h("span", {
      style: { width: `${(100 * r.alloc) / total}%`, background: r.g.color },
      onmousemove: (e) => tip.show(e, [r.g.label, `${fmt.size(r.alloc)} · ${fmt.pct(r.alloc, total)} · ${fmt.count(r.count)} files`]),
      onmouseleave: tip.hide,
    })));
  const legend = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Type"), h("th", { class: "num" }, "On disk"),
    h("th", { class: "num" }, "Share"), h("th", { class: "num" }, "Files"))),
  h("tbody", {}, rows.sort((a, b) => b.alloc - a.alloc).map((r) => h("tr", {},
    h("td", {}, h("i", { class: "sw", style: { background: r.g.color } }), r.g.label),
    h("td", { class: "num" }, fmt.size(r.alloc)), h("td", { class: "num ink2" }, fmt.pct(r.alloc, total)),
    h("td", { class: "num ink2" }, fmt.count(r.count))))));

  const maxDir = Math.max(1, ...ov.top_dirs.map((d) => d.alloc));
  const dirs = h("table", {}, h("tbody", {}, ov.top_dirs.map((d) => h("tr", {
    class: "rowlink", onclick: () => (location.hash = "#explore?" + encodeURIComponent(d.path)),
  }, h("td", { class: "name" }, h("span", { class: "trunc" }, d.name),
    h("div", { class: "inbar" }, h("span", { style: { width: `${(100 * d.alloc) / maxDir}%` } }))),
  h("td", { class: "num" }, fmt.size(d.alloc)), h("td", { class: "num muted" }, fmt.count(d.files) + " files")))));

  const files = h("table", {}, h("tbody", {}, ov.big_files.map((f) => h("tr", {},
    h("td", { class: "name" }, h("span", { class: "trunc", title: f.path }, f.name),
      h("span", { class: "trunc path" }, pretty(f.path))),
    h("td", {}, h("span", { class: "chip" }, h("i", { class: "sw", style: { background: groupOf(f.category).color } }), CAT_LABEL[f.category] || f.category)),
    h("td", { class: "num" }, fmt.size(f.alloc)),
    h("td", {}, h("button", { class: "btn small", onclick: () => reveal(f.path) }, "Show"))))));

  const exts = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Extension"), h("th", {}, "Type"),
    h("th", { class: "num" }, "Files"), h("th", { class: "num" }, "On disk"))),
  h("tbody", {}, ov.extensions.slice(0, 15).map((e) => h("tr", {},
    h("td", { class: "mono" }, e.ext || "(none)"), h("td", { class: "ink2" }, CAT_LABEL[e.category] || e.category),
    h("td", { class: "num ink2" }, fmt.count(e.count)), h("td", { class: "num" }, fmt.size(e.alloc))))));

  const errors = ov.errors.length ? h("div", { class: "warn" },
    `${m.errors} folders couldn't be read (e.g. ${short(ov.errors[0].path)}). To include them, add Mac Cleaner under `,
    "System Settings → Privacy & Security → Full Disk Access, then rescan.") : null;

  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Overview"),
      h("div", { class: "ink2" }, `Scanned ${JSON.parse(m.roots || "[]").map(whereName).join(", ")} on ${m.scanned_at}`)),
    h("div", { class: "spacer" }), h("button", { class: "btn", onclick: showSurvey }, "Survey report")),
    errors || "", hero, tiles,
    h("div", { class: "card", style: { marginBottom: "14px" } }, h("h2", {}, "Where the space goes"), share, legend),
    h("div", { class: "grid cols-2" },
      h("div", { class: "card" }, h("h2", {}, "Biggest folders in your home"), dirs),
      h("div", { class: "card" }, h("h2", {}, "Biggest files"), files),
      h("div", { class: "card" }, h("h2", {}, "Top file types"), exts)));
};

async function showSurvey() {
  const s = await get("/api/survey");
  const pre = h("pre", { class: "survey" }, s.text);
  modal("Survey report", h("div", {},
    h("p", { class: "ink2" }, "A text summary of your files (names and sizes only). Saved to ", h("span", { class: "mono" }, short(s.path)),
      ". Paste it to Claude to get folder structures and rules tailored to what's actually on your Mac."), pre),
  [{ label: "Copy", value: "copy" }, { label: "Close", value: false, cls: "primary" }]).then((v) => {
    if (v === "copy") navigator.clipboard.writeText(s.text).then(() => toast("Copied."));
  });
}

function updateBadges(inbox, purge) {
  if (inbox) $("#badge-inbox").textContent = inbox.inboxes.reduce((a, b) => a + b.count, 0) || "";
  if (purge && purge.findings) {
    const n = purge.findings.filter((f) => f.action && f.risk === "safe").reduce((a, f) => a + f.alloc, 0);
    $("#badge-cleanup").textContent = n ? fmt.size(n) : "";
    $("#badge-cleanup").title = "Ready to clean";
  }
}

// ----------------------------------------------------------------- explore
function squarify(items, x, y, w, h) {
  const out = [];
  let rest = items.slice();
  const worst = (row, side) => {
    const s = row.reduce((a, b) => a + b.area, 0);
    const mx = Math.max(...row.map((r) => r.area));
    const mn = Math.min(...row.map((r) => r.area));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  while (rest.length && w > 0 && h > 0) {
    const side = Math.min(w, h);
    let row = [];
    let best = Infinity;
    for (const it of rest) {
      const r = worst([...row, it], side);
      if (r > best) break;
      row.push(it);
      best = r;
    }
    const s = row.reduce((a, b) => a + b.area, 0);
    if (w >= h) {
      const cw = s / h;
      let yy = y;
      for (const it of row) { const hh = it.area / cw; out.push({ ...it, x, y: yy, w: cw, h: hh }); yy += hh; }
      x += cw; w -= cw;
    } else {
      const rh = s / w;
      let xx = x;
      for (const it of row) { const ww = it.area / rh; out.push({ ...it, x: xx, y, w: ww, h: rh }); xx += ww; }
      y += rh; h -= rh;
    }
    rest = rest.slice(row.length);
  }
  return out;
}

function nodeColor(n) {
  if (n.kind === "file") return groupOf(n.category).color;
  if (n.kind === "ableton-project") return "var(--c1)";
  if (n.kind === "package") return "var(--c5)";
  if (n.zone === "library") return "var(--c8)";
  if (n.zone === "system") return "var(--c-system)";
  return "var(--c-dir)";
}
const cssColor = (v) => (v.startsWith("var(") ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim() : v);
function isLight(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) return false;
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.32;
}

let exploreMeasure = "alloc";
VIEWS.explore = async (root) => {
  const q = decodeURIComponent((location.hash.split("?")[1] || ""));
  const data = await get("/api/tree" + (q ? "?path=" + encodeURIComponent(q) : ""));
  if (data.has_scan === false) return noScan(root);
  if (data.error) {
    root.replaceChildren(h("div", { class: "empty" }, h("p", {}, data.error),
      h("a", { href: "#explore" }, "Back to the top")));
    return;
  }
  const go = (p) => (location.hash = "#explore?" + encodeURIComponent(p));
  const meas = exploreMeasure;
  const nodes = [...data.children, ...data.files].filter((n) => n[meas] > 0).sort((a, b) => b[meas] - a[meas]);
  const total = data.node[meas] || 1;

  const crumbs = h("div", { class: "crumbs" }, data.crumbs.map((c, i) => [
    i ? h("span", { class: "sep" }, "›") : null,
    i === data.crumbs.length - 1 ? h("b", {}, i ? c.split("/").pop() : pretty(c))
      : h("a", { href: "#", onclick: (e) => { e.preventDefault(); go(c); } }, i ? c.split("/").pop() : pretty(c))]));

  const seg = h("div", { class: "seg" },
    [["alloc", "On this Mac"], ["size", "Including iCloud-only"]].map(([k, l]) =>
      h("button", { class: meas === k ? "on" : "", onclick: () => { exploreMeasure = k; route(); } }, l)));

  // Treemap: top 60 items, the rest folded into one block.
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.id = "treemap";
  const wrap = h("div", { class: "card" }, svg);
  const legendItems = new Map();

  const tbl = h("tbody", {});
  const selected = new Map();
  const updateBar = () => {
    actionbar.set(selected.size, `${selected.size} selected · ${fmt.size([...selected.values()].reduce((a, n) => a + n.alloc, 0))}`, [
      h("button", { class: "btn", onclick: () => moveSelected([...selected.values()]) }, "Move to…"),
      h("button", { class: "btn primary", onclick: () => trashSelected([...selected.values()]) }, "Move to Trash…"),
    ]);
  };
  for (const n of nodes.slice(0, 300)) {
    const isDir = n.kind !== "file";
    const cb = h("input", { type: "checkbox", "aria-label": "Select " + n.name, onchange: () => {
      if (cb.checked) selected.set(n.path, n); else selected.delete(n.path);
      updateBar();
    } });
    tbl.append(h("tr", {},
      h("td", { class: "check" }, cb),
      h("td", { class: "name" },
        h("span", { class: "trunc" + (isDir && n.kind !== "package" ? " rowlink" : ""), style: isDir && n.kind !== "package" ? { color: "var(--accent)" } : {},
          onclick: isDir && n.kind !== "package" ? () => go(n.path) : null },
        h("i", { class: "sw", style: { background: nodeColor(n) } }), n.name + (isDir && n.kind !== "package" ? "/" : "")),
        h("div", { class: "inbar" }, h("span", { style: { width: `${(100 * n[meas]) / total}%` } }))),
      h("td", { class: "num" }, fmt.size(n[meas])),
      h("td", { class: "num muted" }, isDir ? fmt.count(n.files) : n.dataless ? "iCloud" : ""),
      h("td", { class: "num muted" }, fmt.ago(n.mtime)),
      h("td", {}, h("button", { class: "btn small", onclick: () => reveal(n.path) }, "Show"))));
  }

  root.replaceChildren(
    h("div", { class: "toolbar" }, h("h1", {}, "Explore"), h("div", { class: "spacer" }), seg),
    crumbs,
    h("div", { class: "explore" },
      h("div", { class: "stack" }, wrap, h("div", { class: "legend", id: "tm-legend" })),
      h("div", { class: "card" },
        h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, fmt.size(data.node[meas])),
          h("span", { class: "ink2" }, `${fmt.count(data.node.files)} files`)),
        h("div", { style: { maxHeight: "560px", overflow: "auto" } },
          h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", {}, "Name"),
            h("th", { class: "num" }, "Size"), h("th", { class: "num" }, "Files"), h("th", { class: "num" }, "Modified"), h("th", {}))), tbl)))));

  // Draw after layout so we know the width.
  const W = svg.clientWidth || 800;
  const H = svg.clientHeight || 520;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const top = nodes.slice(0, 60);
  const restSum = nodes.slice(60).reduce((a, n) => a + n[meas], 0);
  const items = top.map((n) => ({ n, v: n[meas] }));
  if (restSum > 0) items.push({ n: { name: `${nodes.length - 60} smaller items`, kind: "rest", [meas]: restSum }, v: restSum });
  const sum = items.reduce((a, b) => a + b.v, 0) || 1;
  items.forEach((it) => (it.area = (it.v / sum) * W * H));
  const NS = "http://www.w3.org/2000/svg";
  for (const r of squarify(items.filter((i) => i.area > 0), 0, 0, W, H)) {
    const n = r.n;
    const color = n.kind === "rest" ? "var(--c-other)" : nodeColor(n);
    const label = n.kind === "file" ? groupOf(n.category).label
      : n.kind === "ableton-project" ? GROUPS[0].label : n.kind === "package" ? "Apps & packages"
      : n.zone === "library" ? GROUPS[7].label : n.zone === "system" ? GROUPS[8].label : n.kind === "rest" ? "Smaller items" : "Folders";
    legendItems.set(label, color);
    const rect = document.createElementNS(NS, "rect");
    Object.entries({ x: r.x, y: r.y, width: Math.max(0, r.w), height: Math.max(0, r.h), rx: 4, fill: color })
      .forEach(([k, v]) => rect.setAttribute(k, v));
    rect.addEventListener("mousemove", (e) => tip.show(e, [n.name, `${fmt.size(n[meas])} · ${fmt.pct(n[meas], total)}` +
      (n.files ? ` · ${fmt.count(n.files)} files` : "") + (n.mtime ? ` · modified ${fmt.ago(n.mtime)} ago` : ""), n.path ? pretty(n.path) : ""]));
    rect.addEventListener("mouseleave", tip.hide);
    if (n.kind !== "file" && n.kind !== "rest" && n.kind !== "package") rect.addEventListener("click", () => { tip.hide(); go(n.path); });
    else if (n.path) rect.addEventListener("click", () => reveal(n.path));
    svg.append(rect);
    if (r.w > 60 && r.h > 30) {
      const dark = isLight(cssColor(color));
      for (const [i, txt] of [n.name, fmt.size(n[meas])].entries()) {
        const t = document.createElementNS(NS, "text");
        t.setAttribute("x", r.x + 7);
        t.setAttribute("y", r.y + 16 + i * 14);
        if (dark) t.setAttribute("class", "dark");
        if (i === 0) t.setAttribute("font-weight", "600");
        const maxChars = Math.floor((r.w - 12) / 6.5);
        t.textContent = txt.length > maxChars ? txt.slice(0, Math.max(1, maxChars - 1)) + "…" : txt;
        svg.append(t);
      }
    }
  }
  $("#tm-legend").replaceChildren(...[...legendItems].map(([l, c]) => h("span", {}, h("i", { style: { background: c } }), l)));
};

async function moveSelected(nodes) {
  const { destinations } = await get("/api/destinations");
  const input = h("input", { type: "text", list: "dest-list", placeholder: "Folder path", style: { width: "100%" } });
  const body = h("div", {}, h("p", { class: "ink2" }, `Move ${nodes.length} item(s) to:`), input,
    h("datalist", { id: "dest-list" }, destinations.map((d) => h("option", { value: pretty(d) }))));
  const ok = await modal("Move to…", body, [{ label: "Cancel", value: false }, { label: "Move", value: true, cls: "primary" }]);
  if (!ok || !input.value.trim()) return;
  await runActions(nodes.map((n) => ({ path: n.path, action: "move", dest: input.value.trim() })));
  route();
}

async function trashSelected(nodes) {
  const warnings = [];
  if (nodes.some((n) => n.path.startsWith(HOME + "/Library/") && !n.path.includes(CLOUD_MARK))) {
    warnings.push("Some of these are inside your Library folder, where apps keep their settings and data. Only trash them if you know what they are; Cleanup lists the ones that are safe.");
  }
  if (nodes.some((n) => n.path.includes(CLOUD_MARK))) {
    warnings.push("Some of these are in iCloud Drive. Trashing them removes them from your other devices too.");
  }
  const ok = await confirmItems(`Move ${nodes.length} item${nodes.length === 1 ? "" : "s"} to the Trash?`,
    nodes.map((n) => ({ label: n.name, detail: fmt.size(n.alloc) })), "Move to Trash", warnings);
  if (!ok) return;
  await runActions(nodes.map((n) => ({ path: n.path, action: "trash", bytes: n.alloc })));
  route();
}

// ------------------------------------------------------------------ inbox
let inboxFilter = "all";
VIEWS.inbox = async (root) => {
  const data = await get("/api/inbox");
  updateBadges(data, null);
  const plan = new Map(); // path -> {action, dest}
  const selected = new Set();
  const all = data.inboxes.flatMap((ib) => ib.items);

  const updateBar = () => {
    const items = all.filter((i) => selected.has(i.path));
    const n = items.filter((i) => (plan.get(i.path) || {}).action !== "keep").length;
    actionbar.set(selected.size, `${selected.size} selected · ${fmt.size(items.reduce((a, b) => a + b.size, 0))}`, [
      h("button", { class: "btn", onclick: () => { selected.clear(); route(); } }, "Clear"),
      h("button", { class: "btn primary", disabled: !n, onclick: () => apply(items) }, `Apply ${n}`),
    ]);
  };

  const apply = async (items) => {
    const todo = items.map((i) => ({ i, p: plan.get(i.path) })).filter(({ p }) => p.action !== "keep");
    const missing = todo.filter(({ p }) => p.action === "move" && !p.dest);
    if (missing.length) return toast(`Pick a destination for ${missing[0].i.name}`);
    const risky = todo.filter(({ i }) => i.used_by);
    const ok = await confirmItems(`Apply ${todo.length} change(s)?`, todo.map(({ i, p }) => ({
      label: i.name, detail: p.action === "trash" ? "→ Trash" : "→ " + pretty(p.dest),
    })), "Apply", risky.length ? `${risky.map((r) => r.i.name).join(", ")} contain files used by Ableton sets elsewhere; moving them will make those sets show missing files.` : null);
    if (!ok) return;
    await runActions(todo.map(({ i, p }) => ({ path: i.path, action: p.action, dest: p.dest, bytes: i.size })));
    route();
  };

  const filters = [["all", "All"], ["stale", `Untouched ${data.stale_days}+ days`], ["suggested", "Has a suggestion"], ["nosugg", "Needs a decision"]];
  const seg = h("div", { class: "seg" }, filters.map(([k, l]) =>
    h("button", { class: inboxFilter === k ? "on" : "", onclick: () => { inboxFilter = k; route(); } }, l)));
  const pass = (i) => inboxFilter === "all" || (inboxFilter === "stale" && i.stale)
    || (inboxFilter === "suggested" && i.suggestion && i.suggestion.action !== "keep") || (inboxFilter === "nosugg" && !i.suggestion);

  const datalist = h("datalist", { id: "inbox-dests" }, data.destinations.map((d) => h("option", { value: pretty(d) })));
  const checkboxes = [];

  const sections = data.inboxes.map((ib) => {
    const items = ib.items.filter(pass);
    const rows = items.map((i) => {
      const s = i.suggestion || { action: "keep" };
      plan.set(i.path, { action: s.action, dest: s.dest || "" });
      const destIn = h("input", { type: "text", list: "inbox-dests", value: s.dest ? pretty(s.dest) : "", placeholder: "Destination folder",
        title: s.dest || "", hidden: s.action !== "move",
        onchange: () => { plan.get(i.path).dest = destIn.value.trim(); } });
      const actSel = h("select", { "aria-label": "Action for " + i.name, onchange: () => {
        plan.get(i.path).action = actSel.value;
        destIn.hidden = actSel.value !== "move";
        updateBar();
      } }, [["keep", "Keep here"], ["move", "Move to"], ["trash", "Trash"]].map(([v, l]) =>
        h("option", { value: v, selected: v === s.action }, l)));
      const cb = h("input", { type: "checkbox", "aria-label": "Select " + i.name, onchange: () => {
        if (cb.checked) selected.add(i.path); else selected.delete(i.path);
        updateBar();
      } });
      cb._item = i;
      checkboxes.push(cb);
      const kindLabel = i.kind === "ableton-project" ? "Ableton project" : i.kind === "folder" ? `Folder of ${(CAT_LABEL[i.category] || "other").toLowerCase()}`
        : CAT_LABEL[i.category] || "Other";
      return h("tr", {},
        h("td", { class: "check" }, cb),
        h("td", { class: "name" },
          h("span", { class: "trunc", title: i.name }, i.name + (i.is_dir ? "/" : "")),
          i.used_by ? h("span", { class: "status warning", title: i.used_by.map(short).join("\n") },
            h("span", { class: "dot" }), `Used by ${i.used_by.length} Ableton set${i.used_by.length > 1 ? "s" : ""} elsewhere`) : null),
        h("td", {}, h("span", { class: "chip" }, h("i", { class: "sw", style: { background: i.kind === "ableton-project" ? "var(--c1)" : groupOf(i.category).color } }), kindLabel)),
        h("td", { class: "num" }, fmt.size(i.size)),
        h("td", { class: "num " + (i.stale ? "" : "muted"), title: "Since last modified" }, i.stale ? h("b", {}, fmt.age(i.age_days)) : fmt.age(i.age_days)),
        h("td", { style: { width: "38%" } }, h("div", { class: "sugg" }, actSel, destIn,
          s.action === "trash" ? riskPill(s.risk) : null),
          h("div", { class: "muted", style: { fontSize: "11.5px" } }, i.suggestion
            ? (i.suggestion.reason ? `${i.suggestion.rule}: ${i.suggestion.reason}` : `Rule: ${i.suggestion.rule}`)
            : "No rule matched; choose where it goes, or leave it.")),
        h("td", {}, h("button", { class: "btn small", onclick: () => reveal(i.path) }, "Show")));
    });
    return h("div", { class: "card" },
      h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, short(ib.path)),
        ib.active ? h("span", { class: "chip", title: `Items here are left alone until untouched for ${data.stale_days} days` }, "Active workspace") : null,
        h("span", { class: "ink2" }, `${ib.count} items · ${fmt.size(ib.size)} · ${ib.stale} untouched ${data.stale_days}+ days`)),
      ib.error ? h("div", { class: "warn" }, ib.error) : null,
      rows.length ? h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", {}, "Name"), h("th", {}, "Type"),
        h("th", { class: "num" }, "Size"), h("th", { class: "num" }, "Age"), h("th", {}, "Where it should go"), h("th", {}))),
      h("tbody", {}, rows)) : h("p", { class: "muted" }, "Nothing here matches this filter."));
  });

  const selectSuggested = (action) => {
    for (const cb of checkboxes) {
      const sg = cb._item.suggestion;
      if (sg && sg.action === action && !cb._item.used_by) { cb.checked = true; selected.add(cb._item.path); }
    }
    updateBar();
  };
  const count = (action) => checkboxes.filter((cb) => cb._item.suggestion && cb._item.suggestion.action === action && !cb._item.used_by).length;

  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Catch-alls"),
      h("div", { class: "ink2" }, "Everything sitting loose in your Downloads and Desktop, with a suggested home from your rules.")),
    h("div", { class: "spacer" })),
    h("div", { class: "toolbar" }, seg, h("div", { class: "spacer" }),
      count("move") ? h("button", { class: "btn", onclick: () => selectSuggested("move") }, `Select ${count("move")} suggested moves`) : null,
      count("trash") ? h("button", { class: "btn", onclick: () => selectSuggested("trash") }, `Select ${count("trash")} suggested for Trash`) : null,
      h("a", { class: "btn", href: "#rules" }, "Edit rules")),
    datalist, h("div", { class: "stack" }, sections));
};

// ---------------------------------------------------------------- cleanup
const CLOUD_MARK = ICLOUD_REL + "/";
VIEWS.cleanup = async (root) => {
  const data = await get("/api/purge");
  if (!data.has_scan) return noScan(root);
  updateBadges(null, data);
  const selected = new Map();
  const groups = new Map();
  for (const f of data.findings) {
    if (!groups.has(f.group)) groups.set(f.group, []);
    groups.get(f.group).push(f);
  }
  const confirmAndTrash = async (items) => {
    const warnings = [];
    if (items.some((f) => f.kind === "cache" || f.title === "Ableton decoding cache")) {
      warnings.push("Quit the apps these caches belong to first (Live for its decoding cache). An app that's open while its cache moves can misbehave until you restart it.");
    }
    if (items.some((f) => f.path.includes(CLOUD_MARK))) {
      warnings.push("Some of these are in iCloud Drive. Trashing them removes them from your other devices too.");
    }
    const ok = await confirmItems(`Move ${items.length} item${items.length === 1 ? "" : "s"} (${fmt.size(items.reduce((a, f) => a + f.alloc, 0))}) to the Trash?`,
      items.map((f) => ({ group: f.group, why: f.kind === "dupe" ? null : f.why, label: f.title,
        detail: `${fmt.size(f.alloc)} · ${pretty(f.path)}` })), "Move to Trash", warnings);
    if (!ok) return;
    await runActions(items.map((f) => ({ path: f.path, action: f.action, bytes: f.alloc })));
    route();
  };
  const updateBar = () => {
    const items = [...selected.values()];
    actionbar.set(items.length, `${items.length} selected · ${fmt.size(items.reduce((a, b) => a + b.alloc, 0))}`, [
      h("button", { class: "btn", onclick: () => { selected.clear(); route(); } }, "Clear"),
      h("button", { class: "btn primary", onclick: () => confirmAndTrash(items) }, "Move to Trash…"),
    ]);
  };
  const boxes = [];
  const LIMIT = 150;
  const cards = [...groups].sort((a, b) => b[1].reduce((s, f) => s + f.alloc, 0) - a[1].reduce((s, f) => s + f.alloc, 0)).map(([name, items]) => {
    const total = items.reduce((a, f) => a + f.alloc, 0);
    const infoOnly = items.every((f) => !f.action);
    const sorted = items.sort((a, b) => b.alloc - a.alloc);
    return h("div", { class: "card" },
      h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, name), h("span", { class: "ink2" }, `${items.length} · ${fmt.size(total)}`),
        infoOnly ? h("span", { class: "chip" }, "For information: nothing to select") : null),
      h("table", {}, h("tbody", {}, sorted.slice(0, LIMIT).map((f) => {
        const cb = f.action ? h("input", { type: "checkbox", "aria-label": "Select " + f.title, onchange: () => {
          if (cb.checked) selected.set(f.path, f); else selected.delete(f.path);
          updateBar();
        } }) : null;
        if (cb) { cb._f = f; boxes.push(cb); }
        return h("tr", {},
          h("td", { class: "check" }, cb),
          h("td", { class: "name" }, h("span", { class: "trunc", title: f.title }, f.title),
            h("span", { class: "trunc path", title: f.path }, pretty(f.path))),
          h("td", { style: { width: "104px" } }, f.action ? riskPill(f.risk) : null),
          h("td", { class: "ink2", style: { width: "40%" } }, f.why),
          h("td", { class: "num", style: { width: "80px" } }, fmt.size(f.alloc)),
          h("td", {}, h("button", { class: "btn small", onclick: () => reveal(f.path) }, "Show")));
      }))),
      items.length > LIMIT ? h("p", { class: "muted" }, `Showing the ${LIMIT} biggest of ${items.length}.`) : null);
  });
  const safeBoxes = boxes.filter((cb) => cb._f.risk === "safe");
  const safeBytes = safeBoxes.reduce((a, cb) => a + cb._f.alloc, 0);
  const sum = data.summary || {};
  const banner = sum.unchecked_sets ? h("div", { class: "warn" },
    `${sum.unchecked_sets} Ableton set${sum.unchecked_sets === 1 ? "" : "s"} couldn't be checked (only in iCloud, or unreadable), so audio duplicates are hidden: one of those sets might use them. `,
    "To check them, open iCloud Drive in Finder, right-click Ableton Projects → Download Now, then rescan.") : null;
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Cleanup"),
      h("div", { class: "ink2" }, "Things you probably don't need. Ticked items go to the Trash, so nothing is gone until you empty it.")),
    h("div", { class: "spacer" }),
    safeBoxes.length ? h("button", { class: "btn primary", onclick: () => {
      safeBoxes.forEach((cb) => { cb.checked = true; selected.set(cb._f.path, cb._f); });
      updateBar();
    } }, `Select ${safeBoxes.length} safe item${safeBoxes.length === 1 ? "" : "s"} (${fmt.size(safeBytes)})`) : null),
    h("div", { class: "legend-row" },
      riskPill("safe"), h("span", { class: "ink2" }, "rebuilt automatically, or an exact copy of something you keep"),
      riskPill("review"), h("span", { class: "ink2" }, "probably not needed, but only you can tell"),
      h("span", { class: "muted" }, data.scanned_at ? `Based on the scan from ${data.scanned_at}. Everything is re-checked when you click.` : "")),
    banner || "",
    cards.length ? h("div", { class: "stack" }, cards) : h("div", { class: "card empty" }, "Nothing obvious to clean up. Nice."));
};

// ------------------------------------------------------------------- music
VIEWS.music = async (root) => {
  const data = await get("/api/ableton");
  if (!data.has_scan) return noScan(root);
  const t = data.totals;
  const now = Date.now() / 1000;
  const suggestBucket = (p) => {
    if (p.bucket) return p.bucket;
    const age = (now - p.mtime) / 86400;
    const b = data.buckets;
    if (age < 45 && b.includes("Active")) return "Active";
    if (age < 365 && b.includes("Ideas")) return "Ideas";
    return b.includes("Archive") ? "Archive" : b[0];
  };
  const statusEl = (p) => {
    const ext = p.sets.reduce((a, s) => a + s.external, 0);
    const miss = p.sets.reduce((a, s) => a + s.missing, 0);
    if (p.status === "ok") return h("span", { class: "status good" }, h("span", { class: "dot" }), "Self-contained");
    if (p.status === "missing") return h("span", { class: "status critical" }, h("span", { class: "dot" }), `${miss} missing`);
    if (p.status === "external") return h("span", { class: "status warning" }, h("span", { class: "dot" }), `${ext} outside project`);
    if (p.status === "no-sets") return h("span", { class: "status neutral" }, h("span", { class: "dot" }), "No sets");
    return h("span", { class: "status neutral" }, h("span", { class: "dot" }), "iCloud only");
  };

  const selected = new Map();
  const target = new Map();
  const updateBar = () => {
    const items = [...selected.values()];
    actionbar.set(items.length, `${items.length} project${items.length > 1 ? "s" : ""} selected`, [
      h("button", { class: "btn primary", onclick: async () => {
        const todo = items.filter((p) => !(p.in_library && p.bucket === target.get(p.path)));
        if (!todo.length) return toast("Those are already in the chosen buckets.");
        const risky = todo.filter((p) => p.status === "external" || p.status === "missing");
        const ok = await confirmItems(`Move ${todo.length} project(s)?`, todo.map((p) => ({
          label: p.name, detail: "→ " + pretty(data.root + "/" + target.get(p.path)),
        })), "Move", (risky.length ? `${risky.length} of these use files outside the project folder. Open them in Live and use File → Collect All and Save first, or they may show missing samples after moving. ` : "")
          + "Close these sets in Live before moving them.");
        if (!ok) return;
        await runActions(todo.map((p) => ({ path: p.path, action: "move", dest: data.root + "/" + target.get(p.path) })));
        route();
      } }, "Move to chosen buckets"),
    ]);
  };

  const tbody = h("tbody", {});
  for (const p of data.projects) {
    target.set(p.path, suggestBucket(p));
    const cb = h("input", { type: "checkbox", "aria-label": "Select " + p.name, onchange: () => {
      if (cb.checked) selected.set(p.path, p); else selected.delete(p.path);
      updateBar();
    } });
    const sel = h("select", { "aria-label": "Bucket for " + p.name, onchange: () => target.set(p.path, sel.value) },
      data.buckets.map((b) => h("option", { value: b, selected: b === target.get(p.path) }, b)));
    const where = p.in_library ? h("span", { class: "chip" }, p.bucket ? "Projects · " + p.bucket : "Projects · unsorted")
      : h("span", { class: "trunc ink2", title: p.parent }, pretty(p.parent));
    const detail = h("tr", { class: "detail-row", hidden: true }, h("td", {}), h("td", { colspan: 8 }, projectDetail(p)));
    const nameCell = h("td", { class: "name rowlink", onclick: () => (detail.hidden = !detail.hidden) },
      h("span", { class: "trunc", style: { color: "var(--accent)" } }, p.name.replace(/ Project$/, "")),
      p.possible_copies.length ? h("span", { class: "status warning" }, h("span", { class: "dot" }), `${p.possible_copies.length} possible cop${p.possible_copies.length > 1 ? "ies" : "y"}`) : null);
    tbody.append(h("tr", {},
      h("td", { class: "check" }, cb), nameCell,
      h("td", { style: { maxWidth: "220px" } }, where),
      h("td", {}, statusEl(p)),
      h("td", { class: "ink2" }, (p.version || "").replace("Ableton Live ", "")),
      h("td", { class: "num" }, fmt.size(p.alloc)),
      h("td", { class: "num ink2" }, fmt.ago(p.mtime)),
      h("td", { class: "num muted" }, p.backup_bytes ? fmt.size(p.backup_bytes) : ""),
      h("td", {}, sel)), detail);
  }

  const maxLoc = Math.max(1, ...data.locations.map((l) => l.count));
  const locs = h("table", {}, h("tbody", {}, data.locations.map((l) => h("tr", {},
    h("td", { class: "name" }, h("span", { class: "trunc" }, pretty(l.location)),
      h("div", { class: "inbar" }, h("span", { style: { width: `${(100 * l.count) / maxLoc}%`, background: "var(--c1)" } }))),
    h("td", { class: "num" }, `${l.count}`), h("td", { class: "num muted" }, fmt.size(l.alloc))))));

  const loose = data.loose_sets.length ? h("div", { class: "card" }, h("h2", {}, `Sets outside a project folder (${data.loose_sets.length})`),
    h("p", { class: "ink2" }, "Open these in Live and use File → Collect All and Save, or Save As into a new project, so they get a proper project folder."),
    h("table", {}, h("tbody", {}, data.loose_sets.map((s) => h("tr", {},
      h("td", { class: "name" }, h("span", { class: "trunc" }, pretty(s.path))),
      h("td", {}, s.error ? h("span", { class: "muted" }, s.error) : s.external || s.missing
        ? h("span", { class: "status warning" }, h("span", { class: "dot" }), `${s.external + s.missing} files elsewhere`) : h("span", { class: "muted" }, "no samples")),
      h("td", {}, h("button", { class: "btn small", onclick: () => reveal(s.path) }, "Show"))))))) : null;

  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Music"),
      h("div", { class: "ink2" }, "Every Ableton project found on this Mac, where it lives, and whether it's safe to move."))),
    h("div", { class: "grid tiles" },
      tile("Projects", fmt.count(t.projects), fmt.size(t.alloc)),
      tile("Outside your projects folder", fmt.count(t.outside_library), "should move into " + pretty(data.root)),
      tile("Need Collect All and Save", fmt.count(t.needs_collect), "use samples outside the project, or have missing ones"),
      tile("Auto-backups", fmt.size(t.backup_bytes), "Backup folders inside projects"),
      tile(".asd analysis files", fmt.size(t.asd_bytes), "waveform and warp data; Live re-analyses most of it")),
    h("div", { class: "grid cols-2", style: { marginBottom: "14px" } },
      h("div", { class: "card" }, h("h2", {}, "Where projects live"), locs),
      h("div", { class: "card note" }, h("h2", {}, "Suggested system"),
        h("p", {}, "One home for every project: ", h("b", {}, pretty(data.root)), ", split by status:"),
        h("ul", {}, data.buckets.map((b) => h("li", {}, h("b", {}, b), " ", {
          Active: "— what you're working on now (replaces keeping projects on the Desktop)",
          Ideas: "— sketches and loops worth coming back to",
          Finished: "— released or bounced; keep for stems and remixes",
          Archive: "— old or abandoned; candidates for an external drive",
        }[b] || ""))),
        h("p", {}, "Projects marked ", h("b", {}, "Self-contained"), " can be moved freely. Change the buckets in Rules."))),
    h("div", { class: "card", style: { marginBottom: "14px" } },
      h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, "Projects"), h("span", { class: "ink2" }, "Click a name for details. The last column is the suggested bucket.")),
      h("div", { style: { overflowX: "auto" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", {}, "Project"), h("th", {}, "Location"),
        h("th", {}, "Samples"), h("th", {}, "Live"), h("th", { class: "num" }, "Size"), h("th", { class: "num" }, "Last saved"),
        h("th", { class: "num" }, "Backups"), h("th", {}, "Bucket"))), tbody))),
    loose || "");
};

function projectDetail(p) {
  return h("div", { class: "stack" },
    h("div", { class: "kv" },
      h("span", { class: "muted" }, "Path"), h("span", {}, pretty(p.path), " ", h("button", { class: "btn small", onclick: () => reveal(p.path) }, "Show")),
      h("span", { class: "muted" }, "Files"), h("span", {}, `${fmt.count(p.files)} · ${fmt.size(p.alloc)} on this Mac (${fmt.size(p.size)} total)`),
      h("span", { class: "muted" }, "Backups"), h("span", {}, `${p.backup_sets} auto-saved versions, ${fmt.size(p.backup_bytes)}`),
      p.possible_copies.length ? [h("span", { class: "muted" }, "Same name"), h("span", {}, p.possible_copies.map(pretty).join(" · "))] : null),
    p.sets.map((s) => h("div", {},
      h("b", {}, s.path.split("/").pop()), h("span", { class: "ink2" },
        s.error ? ` — ${s.error}` : ` — ${s.refs} files: ${s.in_project} in project, ${s.packs} from Packs, ${s.external} elsewhere, ${s.missing} missing`),
      (s.examples.external || []).length ? h("div", { class: "path" }, "Elsewhere: ", s.examples.external.map(pretty).join(" · ")) : null,
      (s.examples.missing || []).length ? h("div", { class: "path" }, "Missing: ", s.examples.missing.map(pretty).join(" · ")) : null)));
}

// ------------------------------------------------------------------- rules
VIEWS.rules = async (root) => {
  const data = await get("/api/config");
  const cfg = data.config;
  const what = (w) => {
    const bits = [];
    if (w.kind && w.kind.includes("ableton-project")) bits.push("Ableton project folders");
    else if (w.ext) bits.push(w.ext.join(", ") + " files");
    else if (w.category) bits.push(w.category.map((c) => (CAT_LABEL[c] || c).toLowerCase()).join(" or ") + (w.kind && w.kind.includes("folder") ? " folders" : " files"));
    else if (w.name_regex) bits.push("files named like " + w.name_regex.replace(/^\^\(?|\)?\\b$|\\b/g, "").split("|").slice(0, 3).join(" / "));
    else bits.push("anything");
    if (w.name_regex && (w.ext || w.category)) bits.push("from known music-software makers");
    if (w.larger_than_mb) bits.push(`bigger than ${w.larger_than_mb} MB`);
    return bits.join(" ");
  };
  const save = async (next) => {
    const r = await post("/api/config", { config: next });
    if (r.ok) { toast("Saved. Catch-alls uses the new rules straight away."); route(); } else toast(r.error);
  };
  const rows = cfg.rules.map((r, i) => {
    const w = r.when || {};
    const on = h("input", { type: "checkbox", checked: r.enabled !== false, "aria-label": `Rule ${r.name} on`,
      onchange: () => { cfg.rules[i].enabled = on.checked; save(cfg); } });
    let days = null;
    if (w.older_than_days !== undefined) {
      days = h("input", { type: "number", min: 0, value: w.older_than_days, style: { width: "56px" },
        "aria-label": "Days", onchange: () => { cfg.rules[i].when.older_than_days = Number(days.value) || 0; save(cfg); } });
    }
    const then = r.action === "move" ? ["move them to ", h("b", {}, pretty(r.dest.replace("{cloud}", HOME + ICLOUD_REL).replace("{ableton}", "iCloud Drive/Ableton Projects").replace("{year}", "‹year›").replace("{month}", "‹month›")))]
      : r.action === "trash" ? ["suggest the Trash ", riskPill(r.risk || "review")] : ["leave them"];
    return h("tr", { class: r.enabled === false ? "off" : "" },
      h("td", { class: "check" }, on),
      h("td", {}, h("div", {}, h("b", {}, r.name || `Rule ${i + 1}`)),
        h("div", { class: "ink2" }, "When there are ", what(w),
          days ? [" untouched for ", days, " days"] : "", ", ", then, ".")),
      h("td", { class: "muted" }, r.auto ? "runs automatically" : ""));
  });
  const ta = h("textarea", { class: "code", spellcheck: "false" }, JSON.stringify(cfg, null, 2));
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Rules"),
      h("div", { class: "ink2" }, "How Catch-alls suggests a home for things in Downloads and Desktop. The first rule that fits an item wins. Rules only ever suggest; nothing happens until you click Apply."))),
    h("div", { class: "card", style: { marginBottom: "14px" } },
      h("table", { class: "rules" }, h("tbody", {}, rows)),
      h("p", { class: "ink2" }, `Desktop counts as your active workspace: its items are left alone until untouched for ${cfg.stale_days} days. `,
        "Anything an Ableton set uses is always kept where it is, whatever the rules say.")),
    h("details", { class: "card" },
      h("summary", {}, "Advanced: edit the rules as text"),
      h("p", { class: "ink2" }, "Destinations can use {cloud} {ableton} {year} {month} {category}. ",
        "Settings file: ", h("span", { class: "mono" }, short(data.path))),
      h("div", { class: "toolbar" }, h("div", { class: "spacer" }),
        h("button", { class: "btn", onclick: () => { ta.value = JSON.stringify(data.defaults, null, 2); } }, "Load defaults"),
        h("button", { class: "btn primary", onclick: () => {
          let parsed;
          try { parsed = JSON.parse(ta.value); } catch (e) { return toast("That isn't valid JSON: " + e.message); }
          save(parsed);
        } }, "Save")),
      ta));
};

// ----------------------------------------------------------------- history
VIEWS.history = async (root) => {
  const { history } = await get("/api/history");
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "History"), h("div", { class: "ink2" }, "Every move and trash, newest first."))),
    history.length ? h("div", { class: "card" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "What"), h("th", {}, "From"), h("th", {}, "To"), h("th", {}))),
      h("tbody", {}, history.map((e) => h("tr", {},
        h("td", { class: "ink2 num" }, e.ts),
        h("td", {}, e.op === "trash" ? "Trashed" : "Moved", e.note ? h("div", { class: "muted" }, e.note) : null),
        h("td", { class: "name" }, h("span", { class: "trunc", title: e.src }, pretty(e.src))),
        h("td", { class: "name" }, h("span", { class: "trunc", title: e.dst }, pretty(e.dst))),
        h("td", {}, e.undone ? h("span", { class: "muted" }, "undone") : h("button", { class: "btn small", onclick: async () => {
          const r = await post("/api/undo", { id: e.id });
          if (r.ok) { toast("Undone."); route(); } else toast(r.error);
        } }, "Undo")))))))
      : h("div", { class: "card empty" }, h("h2", {}, "Nothing yet"),
        h("p", {}, "Anything you move or trash shows up here, and can be undone until you empty the Trash.")));
};

// ----------------------------------------------------------------- updates
// Three ways this runs (UPDATE.mode): "app" (Mac Cleaner.app), "legacy" (the
// old browser-based install) and "source" (a git checkout).
let UPDATE = null;
async function checkUpdate(force) {
  try {
    const r = await fetch("/api/update" + (force ? "?force=1" : ""));
    UPDATE = await r.json();
  } catch (e) {
    UPDATE = { error: "Couldn't check for updates: " + e.message };
  }
  if (UPDATE.problem && !checkUpdate.shownProblem) {
    checkUpdate.shownProblem = true;
    modal("The update didn't go through", h("p", {}, UPDATE.problem));
  }
  const el = $("#update");
  if (UPDATE.mode === "app" && UPDATE.available) {
    el.replaceChildren(h("button", { class: "btn primary", onclick: showUpdate }, `Update to ${UPDATE.latest}`));
  } else if (UPDATE.mode && UPDATE.mode !== "app" && UPDATE.app_available) {
    el.replaceChildren(h("button", { class: "btn primary", onclick: showMigrate }, "Get the Mac app"));
  } else if (UPDATE.mode === "legacy" && UPDATE.available) {
    el.replaceChildren(h("button", { class: "btn primary", onclick: showUpdate }, `Update to ${UPDATE.latest}`));
  } else {
    el.replaceChildren();
  }
  return UPDATE;
}

function releaseNotes(u) {
  return u.notes ? h("pre", { class: "survey" }, u.notes) : null;
}

function showUpdate() {
  const u = UPDATE;
  if (u.mode === "source") return showMigrate();
  const body = h("div", {},
    h("p", { class: "ink2" }, `You have ${u.current}. ${u.published_at ? "Released " + u.published_at.slice(0, 10) + "." : ""}`),
    releaseNotes(u),
    u.blocked ? h("div", { class: "warn" }, u.blocked)
      : h("p", { class: "ink2" }, u.mode === "app"
        ? "Mac Cleaner will close, update itself and reopen in a few seconds. Your settings, scans and history are kept, and you can roll back from Version · Updates."
        : "Mac Cleaner will restart; your settings, scans and history are kept."));
  modal(`Mac Cleaner ${u.latest} is available`, body, [
    { label: "Later", value: false },
    { label: "Update now", value: true, cls: "primary" },
  ]).then((go) => { if (go && !u.blocked) applyUpdate("/api/update/install"); });
}

function showMigrate() {
  const u = UPDATE;
  const body = h("div", {},
    h("p", {}, "Mac Cleaner is now a proper Mac app: its own window and Dock icon, no browser, no Terminal. Updates stay one click."),
    h("p", { class: "ink2" }, "This installs it in your Applications folder and opens it. Your settings, scans and history carry over. This browser tab will stop working; you can close it."),
    releaseNotes(u));
  modal("Get the Mac app", body, [
    { label: "Not now", value: false },
    { label: "Install and open", value: true, cls: "primary" },
  ]).then((go) => { if (go) applyUpdate("/api/update/migrate"); });
}

async function applyUpdate(endpoint) {
  const msg = h("p", {}, "Downloading and checking the new version…");
  $("#modal-body").replaceChildren(h("h2", {}, "Updating"), msg);
  $("#modal").showModal();
  let res;
  try {
    res = await post(endpoint);
  } catch (e) {
    res = { ok: false, error: e.message };
  }
  if (!res.ok) {
    $("#modal").close();
    return modal("Couldn't update", h("p", {}, res.error));
  }
  if (endpoint.endsWith("migrate")) {
    msg.textContent = `Mac Cleaner ${res.to} is installed in ${short(res.path).replace(/\/Mac Cleaner\.app$/, "")} and opening now. You can close this tab.`;
    return;
  }
  if (res.relaunch) {
    msg.textContent = `Installing ${res.to}. Mac Cleaner will reopen in a moment…`;
    return;
  }
  msg.textContent = `Installed ${res.to}. Restarting…`;
  const deadline = Date.now() + 60000;
  const poll = async () => {
    try {
      const s = await (await fetch("/api/status", { cache: "no-store" })).json();
      if (s.version === res.to) return location.reload();
    } catch (e) { /* server is restarting */ }
    if (Date.now() > deadline) {
      msg.textContent = "The update is installed but the app didn't come back. Quit and reopen Mac Cleaner.";
      return;
    }
    setTimeout(poll, 700);
  };
  setTimeout(poll, 1000);
}

async function showAbout() {
  const u = await checkUpdate(false);
  const tokenIn = h("input", { type: "text", placeholder: "github_pat_…", style: { width: "100%" }, autocomplete: "off" });
  const needsToken = u.error && /token/.test(u.error);
  const how = { app: "Mac app", legacy: "browser version", source: "running from source" }[u.mode] || "";
  const body = h("div", { class: "stack" },
    h("div", { class: "kv" },
      h("span", { class: "muted" }, "Version"), h("span", {}, `${u.current}${how ? " · " + how : ""}`),
      h("span", { class: "muted" }, "Latest release"), h("span", {}, u.latest || "—", u.checked_at ? h("span", { class: "muted" }, ` · checked ${u.checked_at}`) : "")),
    u.available && u.mode === "app" ? h("div", { class: "note" }, `${u.latest} is available. `,
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); $("#modal").close(); showUpdate(); } }, "See what's new"))
      : !u.error ? h("p", { class: "ink2" }, u.available ? `${u.latest} is available.` : "You're up to date.") : null,
    u.mode !== "app" && u.app_available ? h("div", { class: "note" }, "There's a standalone Mac app now. ",
      h("a", { href: "#", onclick: (e) => { e.preventDefault(); $("#modal").close(); showMigrate(); } }, "Get it")) : null,
    u.blocked ? h("div", { class: "warn" }, u.blocked) : null,
    u.problem ? h("div", { class: "warn" }, u.problem) : null,
    u.error ? h("div", { class: "warn" }, u.error) : null,
    needsToken ? h("div", {},
      h("p", { class: "ink2" }, "Updates come from your private GitHub repository, so the app needs a read-only token. Create a fine-grained token at github.com → Settings → Developer settings → Personal access tokens, with access to only seths-Mac-cleaner and Contents: Read-only, and paste it here. It's stored in your Keychain."),
      tokenIn) : null);
  const buttons = [{ label: "Quit Mac Cleaner", value: "quit", cls: "danger" }];
  if (u.can_rollback) buttons.push({ label: `Roll back to ${u.previous}`, value: "rollback" });
  if (needsToken) buttons.push({ label: "Save token", value: "token" });
  buttons.push({ label: "Check now", value: "check" }, { label: "Close", value: false, cls: "primary" });
  const v = await modal("About & updates", body, buttons);
  if (v === "check") { await checkUpdate(true); showAbout(); }
  if (v === "token") {
    const r = await post("/api/update/token", { token: tokenIn.value });
    if (!r.ok) toast(r.error); else { toast("Token saved."); await checkUpdate(true); showAbout(); }
  }
  if (v === "rollback") applyUpdate("/api/update/rollback");
  if (v === "quit") {
    await post("/api/quit").catch(() => {});
    document.body.replaceChildren(h("div", { class: "empty" }, h("h2", {}, "Mac Cleaner has quit"),
      h("p", {}, "Open it again from your Applications folder.")));
  }
}

// -------------------------------------------------------------------- boot
refreshStatus().then(route);
checkUpdate(false);
setInterval(() => checkUpdate(false), 6 * 3600 * 1000);
