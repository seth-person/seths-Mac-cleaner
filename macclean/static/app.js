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

function toastAction(msg, label, fn, ms = 8000) {
  const t = $("#toast");
  t.replaceChildren(h("span", {}, msg, " "), h("button", { class: "btn small", onclick: () => { t.hidden = true; fn(); } }, label));
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}

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

// Time Machine's last backup, asked once per page load, for the reminder before big batches.
let BACKUP = null;
async function backupReminder(count, bytes) {
  if (count < 50 && bytes < 10e9) return null;
  try { BACKUP = BACKUP || await get("/api/backup"); } catch (e) { return null; }
  if (!BACKUP.supported || !BACKUP.remind) return null;
  return BACKUP.days === null
    ? "Time Machine has no backup of this Mac. Back up before a change this big: you'll still be able to undo it here, but a backup covers anything going wrong."
    : `Your last Time Machine backup was ${Math.floor(BACKUP.days)} days ago. Back up first?`;
}

// items: [{label, detail, group?, why?, bytes?}] - grouped by `group` when given.
async function confirmItems(title, items, okLabel, warning) {
  const reminder = await backupReminder(items.length, items.reduce((a, i) => a + (i.bytes || 0), 0));
  if (reminder) warning = [].concat(warning || [], reminder);
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
async function runActions(items, label) {
  const res = await post("/api/apply", { items, label: label || "" });
  if (res.verify && res.verify.length) await verifyWarning(res.verify);
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

// After a batch moved Ableton sets: any set that now misses files it didn't miss before.
async function verifyWarning(problems) {
  const batch = (problems.find((p) => p.batch) || {}).batch;
  const v = await modal("Some sets now have missing files", h("div", {},
    h("div", { class: "warn" }, "After moving, these sets can't find files they found before. Putting the batch back fixes it."),
    h("ul", {}, problems.map((p) => h("li", {}, h("b", {}, setName(p.set)), " ",
      p.error ? p.error : `${p.missing_after} missing (was ${p.missing_before})`)))),
  batch ? [{ label: "Keep as it is", value: false }, { label: "Put the batch back", value: "undo", cls: "primary" }] : undefined);
  if (v === "undo") {
    const r = await post("/api/undo-batch", { id: batch });
    toast(r.ok ? `Put back ${r.undone} item${r.undone === 1 ? "" : "s"}.` : r.error);
  }
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
      h("span", {}, "Disk: ", h("b", {}, fmt.size(d.used)), " used of ", fmt.size(d.total)),
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

// A copy of Mac Cleaner's own data found in a library folder, when this Mac has none.
let dataCopyDismissed = false;
async function dataCopyOffer() {
  if (dataCopyDismissed) return null;
  let d;
  try { d = await get("/api/data-copy"); } catch (e) { return null; }
  const o = d.offer;
  if (!o) return null;
  const card = h("div", { class: "card note", style: { marginBottom: "14px" } },
    h("h2", {}, "Bring back your tags?"),
    h("p", {}, "Mac Cleaner found a copy of its data in ", h("b", {}, pretty(o.path)), o.saved_at ? `, saved ${agoText(o.saved_at)}` : "", ": ",
      [o.tags ? `${o.tags} tag${o.tags === 1 ? "" : "s"} on ${o.tagged} project${o.tagged === 1 ? "" : "s"}` : null,
        o.important ? `${o.important} starred project${o.important === 1 ? "" : "s"}` : null, "saved plans and settings"].filter(Boolean).join(", "), ". ",
      "Restoring it puts them back on this Mac. Nothing in your music folders changes."),
    h("div", { class: "toolbar" },
      h("button", { class: "btn primary", onclick: async () => {
        const r = await post("/api/data-copy/restore", { path: o.path });
        if (!r.ok) return toast(r.error);
        toast("Restored your tags, marks and settings.");
        route();
      } }, "Restore"),
      h("button", { class: "btn", onclick: () => { dataCopyDismissed = true; card.remove(); } }, "Not now")));
  return card;
}

// ---------------------------------------------------------------- overview
VIEWS.overview = async (root) => {
  const [ov, inbox, purge, abl, restoreCard] = await Promise.all([
    get("/api/overview"), get("/api/inbox"), get("/api/purge"), get("/api/ableton"), dataCopyOffer()]);
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
      ". ", h("b", {}, `${ibCount} item${ibCount === 1 ? "" : "s"}`), ibCount === 1 ? " is" : " are", " sitting in Downloads and Desktop",
      ibStale ? [`, ${ibStale} of them untouched for ${inbox.stale_days}+ days`] : "", "."),
    h("div", { class: "toolbar", style: { margin: 0 } },
      h("a", { class: "btn primary", href: "#cleanup" }, "Start cleanup"),
      h("a", { class: "btn", href: "#inbox" }, "Sort Downloads & Desktop"),
      t.needs_collect || t.outside_library ? h("button", { class: "btn", onclick: () => openTab(t.needs_collect ? "collect" : "projects") }, "Tidy Ableton projects") : null));

  const tiles = h("div", { class: "grid tiles" },
    tile(JSON.parse(m.roots || "[]")[0] === HOME ? "Your home folder" : "Scanned", fmt.size(m.total_alloc), `${fmt.count(m.total_files)} files`),
    tile("Catch-alls", `${ibCount} items`, `${fmt.size(ibSize)} · ${ibStale} untouched ${inbox.stale_days}+ days`, () => (location.hash = "#inbox")),
    tile("Ready to clean", fmt.size(safe), `+ ${fmt.size(review)} to check first`, () => (location.hash = "#cleanup")),
    tile("Ableton projects", fmt.count(t.projects),
      `${t.outside_library} outside your projects folder · ${t.needs_collect} need Collect All`, () => openTab("collect")),
    ov.cloud ? tile("iCloud Drive", fmt.size(ov.cloud.size), abl.icloud && abl.icloud.cloud_only_files
      ? `${fmt.size(abl.icloud.cloud_only_bytes)} of your files only in iCloud` : "everything is on this Mac") : null);

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
    errors || "", restoreCard || "", hero, tiles, icloudCard(abl.icloud) || "",
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
  await runActions(nodes.map((n) => ({ path: n.path, action: "move", dest: input.value.trim() })), `Explore · ${nodes.length} moved`);
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
    nodes.map((n) => ({ label: n.name, detail: fmt.size(n.alloc), bytes: n.alloc })), "Move to Trash", warnings);
  if (!ok) return;
  await runActions(nodes.map((n) => ({ path: n.path, action: "trash", bytes: n.alloc })), `Explore · ${nodes.length} trashed`);
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
      label: i.name, detail: p.action === "trash" ? "→ Trash" : "→ " + pretty(p.dest), bytes: i.size,
    })), "Apply", risky.length ? `${risky.map((r) => r.i.name).join(", ")} contain files used by Ableton sets elsewhere; moving them will make those sets show missing files.` : null);
    if (!ok) return;
    await runActions(todo.map(({ i, p }) => ({ path: i.path, action: p.action, dest: p.dest, bytes: i.size })), `Catch-alls · ${todo.length} item${todo.length === 1 ? "" : "s"}`);
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
            h("span", { class: "dot" }), i.used_by_text ? `Used by ${i.used_by_text}` : `Used by ${i.used_by.length} Ableton set${i.used_by.length > 1 ? "s" : ""} elsewhere`) : null),
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

  // Quick-select: moves, or trash that's Safe. "Check first" trash is ticked by hand.
  const picks = (action) => checkboxes.filter((cb) => {
    const sg = cb._item.suggestion;
    return sg && sg.action === action && !cb._item.used_by && (action !== "trash" || sg.risk === "safe");
  });
  const selectSuggested = (action) => {
    for (const cb of picks(action)) { cb.checked = true; selected.add(cb._item.path); }
    updateBar();
  };
  const count = (action) => picks(action).length;
  const checkFirst = checkboxes.filter((cb) => cb._item.suggestion && cb._item.suggestion.action === "trash" && cb._item.suggestion.risk !== "safe").length;

  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Catch-alls"),
      h("div", { class: "ink2" }, "Everything sitting loose in your Downloads and Desktop, with a suggested home from your rules.")),
    h("div", { class: "spacer" })),
    h("div", { class: "toolbar" }, seg, h("div", { class: "spacer" }),
      count("move") ? h("button", { class: "btn", onclick: () => selectSuggested("move") }, `Select ${count("move")} suggested moves`) : null,
      count("trash") ? h("button", { class: "btn", onclick: () => selectSuggested("trash"),
        title: checkFirst ? `${checkFirst} more marked "Check first": tick those yourself` : null },
      `Select ${count("trash")} safe for Trash`) : null,
      h("a", { class: "btn", href: "#rules" }, "Edit rules")),
    datalist, h("div", { class: "stack" }, sections));
};

// -------------------------------------------------------------------- plan
// Preview only in this version: proposals for any folder, which you can tick,
// change and save, and a preview of exactly what a batch would do.
let planFolder = "";
const CONFIDENCE = {
  sure: ["good", "Sure", "A Stem Prep record, or it's already in the right project"],
  likely: ["neutral", "Likely", "The name or track names match"],
  guess: ["neutral", "Guess", "Only a rule by type; check it"],
};
function confidencePill(c) {
  if (!c) return null;
  const [cls, label, title] = CONFIDENCE[c];
  return h("span", { class: "status " + cls, title }, h("span", { class: "dot" }), label);
}

function librarySetup(data) {
  const setup = data.setup || {};
  const lay = data.layout || {};
  const choices = setup.suggestions || [];
  const rootIn = h("input", { type: "text", id: "lib-root", list: "lib-root-list", style: { width: "100%" },
    value: pretty(choices[0] || data.library.root), "aria-label": "Library folder" });
  const statusIn = h("input", { type: "text", id: "lib-statuses", style: { width: "100%" },
    value: (lay.statuses || []).join(", "), "aria-label": "Status folders" });
  const save = async () => {
    const root = rootIn.value.trim().replace(/^iCloud Drive/, HOME + ICLOUD_REL).replace(/^~/, HOME);
    const r = await post("/api/library", { root, statuses: statusIn.value.split(",").map((x) => x.trim()).filter(Boolean) });
    if (!r.ok) return toast(r.error);
    toast("Library set up. Nothing was moved.");
    route();
  };
  return h("div", { class: "card note", style: { marginBottom: "14px" } },
    h("h2", {}, "Set up your library"),
    h("p", {}, "Pick the one folder your music should live in. It can move later, because everything is filed relative to it. ",
      "Choosing it doesn't move anything; it only decides where the suggestions point."),
    h("div", { class: "kv" },
      h("span", { class: "muted" }, "Library folder"), h("span", {}, rootIn,
        h("datalist", { id: "lib-root-list" }, choices.map((c) => h("option", { value: pretty(c) })))),
      h("span", { class: "muted" }, "Status folders"), h("span", {}, statusIn,
        h("div", { class: "muted", style: { fontSize: "12px" } }, `Projects are filed in ${lay.projects || "Projects"}/<status>. Separate names with commas.`))),
    h("div", { class: "toolbar", style: { marginTop: "10px" } }, h("div", { class: "spacer" }),
      h("button", { class: "btn primary", onclick: save }, "Use this library")));
}

VIEWS.plan = async (root) => {
  const data = await get("/api/plan" + (planFolder ? "?folder=" + encodeURIComponent(planFolder) : ""));
  if (!data.has_scan) return noScan(root);
  const lib = data.library;
  const head = h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "Plan"),
    h("div", { class: "ink2" }, "Pick a folder to see where everything in it would go, and why. This is a preview: nothing moves from this tab yet.")));
  const pathIn = h("input", { type: "text", id: "plan-folder", value: planFolder ? pretty(planFolder) : "", placeholder: "Any folder in your home folder",
    style: { minWidth: "260px", flex: "1" }, "aria-label": "Folder to plan" });
  const open = (path) => { planFolder = path; route(); };
  const picker = h("div", { class: "card", style: { marginBottom: "14px" } },
    h("div", { class: "toolbar", style: { flexWrap: "wrap" } },
      data.places.map((pl) => h("button", { class: "btn small" + (pl.path === planFolder ? " primary" : ""), onclick: () => open(pl.path) }, pl.label))),
    h("div", { class: "toolbar", style: { marginTop: "8px" } }, pathIn,
      h("button", { class: "btn", onclick: () => open(pathIn.value.trim().replace(/^iCloud Drive/, HOME + ICLOUD_REL).replace(/^~/, HOME)) }, "Show plan")));
  const parts = [head, lib.ready ? null : librarySetup(data), picker];
  if (lib.ready) {
    parts.push(h("p", { class: "ink2" }, "Library: ", h("b", {}, pretty(lib.root)), ` · projects in ${pretty(lib.projects)}/`,
      Object.keys(lib.statuses).join(", "),
      h("div", { class: "muted", style: { fontSize: "12px" } }, "A copy of your tags, marks, saved plans and settings is kept in its “Mac Cleaner data” folder, so they go wherever your files go.")));
  }
  if (!planFolder) {
    root.replaceChildren(...parts.filter(Boolean), h("div", { class: "card empty" }, h("h2", {}, "Choose a folder"),
      h("p", {}, "Start with Downloads or Desktop, or a folder of projects or stems. Suggestions marked ",
        h("b", {}, "Sure"), " or ", h("b", {}, "Likely"), " start ticked; guesses never do.")));
    return;
  }
  if (data.error) {
    root.replaceChildren(...parts.filter(Boolean), h("div", { class: "warn" }, data.error));
    return;
  }
  if (!data.has_tracks) {
    parts.push(h("div", { class: "note card", style: { marginBottom: "14px" } },
      "Rescan once so Mac Cleaner reads your sets' track names. Until then, stems are only matched to projects by name."));
  }

  const decisions = new Map();
  for (const it of data.items) {
    const saved = data.decisions[it.path];
    decisions.set(it.path, saved && !it.blockers.length ? { ...saved }
      : { action: it.action, dest: it.dest || "", ticked: it.ticked });
  }
  const changed = () => { saveBtn.disabled = false; saveBtn.textContent = "Save my changes"; summary(); };

  const byGroup = new Map();
  for (const it of data.items) {
    const d = decisions.get(it.path);
    const g = it.blockers.length ? "Can't move yet" : d.action === "keep" ? "Stays here" : d.action === "trash" ? "Trash" : "→ " + pretty(d.dest);
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push(it);
  }
  const order = (g) => (g === "Can't move yet" ? 2 : g === "Stays here" ? 3 : g === "Trash" ? 1 : 0);
  const sections = [...byGroup].sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0])).map(([g, its]) => {
    const rows = its.map((it) => {
      const d = decisions.get(it.path);
      const cb = h("input", { type: "checkbox", checked: d.ticked && !it.blockers.length, disabled: !!it.blockers.length || d.action === "keep",
        "aria-label": "Include " + it.name, onchange: () => { d.ticked = cb.checked; changed(); } });
      const dest = h("input", { type: "text", list: "plan-dests", value: d.dest ? pretty(d.dest) : "", hidden: d.action !== "move",
        placeholder: "Destination folder", "aria-label": "Destination for " + it.name,
        onchange: () => { d.dest = dest.value.trim(); changed(); } });
      const act = h("select", { "aria-label": "Action for " + it.name, disabled: !!it.blockers.length, onchange: () => {
        d.action = act.value; dest.hidden = act.value !== "move";
        cb.disabled = act.value === "keep"; if (act.value === "keep") { cb.checked = false; d.ticked = false; }
        changed();
      } }, [["keep", "Keep here"], ["move", "Move to"], ["trash", "Trash"]].map(([v, l]) => h("option", { value: v, selected: v === d.action }, l)));
      const kindLabel = it.kind === "ableton-project" ? "Ableton project" : it.kind === "folder" ? `Folder of ${(CAT_LABEL[it.category] || "other").toLowerCase()}` : CAT_LABEL[it.category] || "Other";
      return h("tr", {},
        h("td", { class: "check" }, cb),
        h("td", { class: "name" }, h("span", { class: "trunc", title: it.name }, it.name + (it.is_dir ? "/" : "")),
          h("div", { class: "muted", style: { fontSize: "11.5px" } }, kindLabel, " · ", fmt.size(it.size), " · ", fmt.age(it.age_days))),
        h("td", { style: { width: "42%" } },
          h("div", {}, confidencePill(it.confidence), " ", h("span", { class: "ink2" }, it.reason)),
          it.blockers.map((b) => h("div", { class: "status critical" }, h("span", { class: "dot" }), b)),
          it.warnings.map((w) => h("div", { class: "status warning" }, h("span", { class: "dot" }), w))),
        h("td", { style: { width: "30%" } }, h("div", { class: "sugg" }, act, dest)),
        h("td", {}, h("button", { class: "btn small", onclick: () => reveal(it.path) }, "Show")));
    });
    return h("div", { class: "card" }, h("h2", { style: { margin: "0 0 6px" } }, g, " ", h("span", { class: "ink2", style: { fontWeight: 400 } }, `${its.length}`)),
      h("table", {}, h("tbody", {}, rows)));
  });

  const counts = h("span", { class: "ink2" });
  const summary = () => {
    const ticked = data.items.filter((it) => decisions.get(it.path).ticked && decisions.get(it.path).action !== "keep" && !it.blockers.length);
    counts.textContent = `${ticked.length} ticked · ${fmt.size(ticked.reduce((a, it) => a + (it.size || 0), 0))}`;
    previewBtn.disabled = !ticked.length;
  };
  const saveBtn = h("button", { class: "btn", disabled: true, onclick: async () => {
    const r = await post("/api/plan/save", { folder: planFolder, decisions: Object.fromEntries(decisions) });
    if (!r.ok) return toast(r.error);
    saveBtn.disabled = true; saveBtn.textContent = "Saved";
  } }, data.saved_at ? "Saved" : "Save my changes");
  const previewBtn = h("button", { class: "btn primary", onclick: async () => {
    const items = data.items.filter((it) => decisions.get(it.path).ticked && !it.blockers.length)
      .map((it) => ({ path: it.path, ...decisions.get(it.path) })).filter((it) => it.action !== "keep");
    const r = await post("/api/plan/preview", { items });
    if (!r.ok) return toast(r.error);
    const ok = r.results.filter((x) => x.ok);
    const bad = r.results.filter((x) => !x.ok);
    await modal(`Preview: ${ok.length} change${ok.length === 1 ? "" : "s"}`, h("div", {},
      h("p", { class: "ink2" }, "Exactly what this batch would do. Running batches from the Plan tab comes in a later version, after you've checked these suggestions on your real folders."),
      bad.length ? h("div", { class: "warn" }, `${bad.length} would be skipped:`, h("ul", {}, bad.map((b) => h("li", {}, `${short(b.path)}: ${b.error}`)))) : null,
      h("div", { style: { maxHeight: "50vh", overflow: "auto" } }, h("table", {}, h("tbody", {}, ok.map((x) => h("tr", {},
        h("td", { class: "name", style: { width: "35%" } }, h("span", { class: "trunc", title: x.src }, x.src.split("/").pop())),
        h("td", { class: "ink2" }, h("span", { class: "trunc", title: x.dst }, x.op === "trash" ? "→ Trash" : "→ " + pretty(x.dst.slice(0, x.dst.lastIndexOf("/"))))))))))));
  } }, "Preview batch");

  root.replaceChildren(...parts.filter(Boolean),
    h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, pretty(planFolder)), counts, h("div", { class: "spacer" }), saveBtn, previewBtn),
    h("datalist", { id: "plan-dests" }, [...new Set(data.items.map((it) => it.dest).filter(Boolean)), ...Object.values(lib.statuses)].map((d) => h("option", { value: pretty(d) }))),
    data.items.length ? h("div", { class: "stack" }, sections) : h("div", { class: "card empty" }, h("p", {}, "This folder is empty.")));
  summary();
};

// ---------------------------------------------------------------- cleanup
const CLOUD_MARK = ICLOUD_REL + "/";
const COLLECT_ALL = "In Live, open each set, then File → Collect All and Save, and tick every source: Elsewhere, Other Projects, User Library and Factory Packs.";
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
        detail: `${fmt.size(f.alloc)} · ${pretty(f.path)}`, bytes: f.alloc })), "Move to Trash", warnings);
    if (!ok) return;
    await runActions(items.map((f) => ({ path: f.path, action: f.action, bytes: f.alloc })), `Cleanup · ${items.length} item${items.length === 1 ? "" : "s"}`);
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
          h("td", { style: { width: "104px" } }, f.action ? riskPill(f.risk)
            : f.kind === "dupe" ? h("a", { class: "chip", href: "#music", title: "See the project in Ableton" }, "Keep both") : null),
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

// ----------------------------------------------------------------- ableton
let musicTab = "recent";
const MUSIC_TABS = [["recent", "Recent"], ["songs", "Songs"], ["important", "Important"], ["tags", "Tags"], ["collect", "Collect All"], ["projects", "All projects"], ["packs", "Factory Packs"]];
const musicTabs = (counts) => h("div", { class: "seg" }, MUSIC_TABS.map(([k, l]) =>
  h("button", { class: musicTab === k ? "on" : "", onclick: () => { musicTab = k; route(); } },
    l, counts && counts[k] ? ` (${counts[k]})` : "")));
const openTab = (k) => { musicTab = k; location.hash === "#music" ? route() : (location.hash = "#music"); };

function abletonHeader(sub, counts) {
  return h("div", {}, h("h1", {}, "Ableton"), h("div", { class: "toolbar" }, musicTabs(counts)),
    h("p", { class: "ink2" }, sub));
}

// ------------------------------------------------------------------ tags
// Tags live in Mac Cleaner's own data (never in the projects). The filter bar
// narrows Recent, Important and All projects: every chosen tag must match.
let TAGDEFS = [];
let TAGKINDS = [];
const tagFilter = new Set();
let projectSearch = "";
let refocusSearch = false;
const tagDef = (name) => TAGDEFS.find((d) => d.name === name) || { name, kind: "Other", color: 8 };
const byKind = (defs) => {
  const m = new Map();
  for (const d of defs) { if (!m.has(d.kind)) m.set(d.kind, []); m.get(d.kind).push(d); }
  const order = (k) => { const i = TAGKINDS.indexOf(k); return i < 0 ? 99 : i; };
  return [...m].sort((a, b) => order(a[0]) - order(b[0]) || a[0].localeCompare(b[0]))
    .map(([k, ds]) => [k, ds.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))]);
};
function tagChip(name, opts = {}) {
  const d = tagDef(name);
  return h("span", { class: "chip tag" + (opts.on ? " on" : ""), title: opts.title || `${d.kind}: ${d.name}`, role: opts.onclick ? "button" : null,
    tabindex: opts.onclick ? "0" : null, onclick: opts.onclick || null,
    onkeydown: opts.onclick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts.onclick(e); } } : null },
  h("i", { class: "sw", style: { background: `var(--c${d.color || 8})` } }), d.name);
}
function passTags(p) {
  for (const t of tagFilter) if (!(p.tags || []).includes(t)) return false;
  const q = projectSearch.trim().toLowerCase();
  if (!q) return true;
  const hay = [p.name, p.parent, ...(p.tags || []), ...(p.sets || []).map((s) => setName(s.path))].join("\n").toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}
function filterBar(projects) {
  const counts = new Map();
  for (const p of projects) for (const t of p.tags || []) counts.set(t, (counts.get(t) || 0) + 1);
  let timer = null;
  const search = h("input", { type: "search", id: "proj-search", value: projectSearch, placeholder: "Search projects, sets and tags",
    "aria-label": "Search projects", oninput: () => {
      clearTimeout(timer);
      timer = setTimeout(() => { projectSearch = search.value; refocusSearch = true; route(); }, 250);
    } });
  if (refocusSearch) { refocusSearch = false; setTimeout(() => { search.focus(); search.setSelectionRange(search.value.length, search.value.length); }, 0); }
  const toggle = (name) => { if (tagFilter.has(name)) tagFilter.delete(name); else tagFilter.add(name); route(); };
  const groups = byKind(TAGDEFS.filter((d) => counts.has(d.name) || tagFilter.has(d.name))).map(([kind, ds]) =>
    h("span", { class: "group" }, h("span", { class: "muted" }, kind), ds.map((d) =>
      tagChip(d.name, { on: tagFilter.has(d.name), onclick: () => toggle(d.name), title: `${counts.get(d.name) || 0} project${counts.get(d.name) === 1 ? "" : "s"} · click to ${tagFilter.has(d.name) ? "stop filtering" : "show only these"}` }))));
  const shown = projects.filter(passTags).length;
  return h("div", { class: "tag-bar" }, search, ...groups,
    tagFilter.size || projectSearch ? [h("span", { class: "ink2" }, `${shown} of ${projects.length}`),
      h("button", { class: "btn small", onclick: () => { tagFilter.clear(); projectSearch = ""; route(); } }, "Clear")] : null,
    !TAGDEFS.length ? h("span", { class: "muted" }, "No tags yet: use + Tag on any project.") : null);
}
// Tick tags for one project, or add a new one.
async function editTags(p, after) {
  const chosen = new Set(p.tags || []);
  const list = h("div", { class: "tag-pick" });
  const draw = () => list.replaceChildren(...byKind(TAGDEFS).map(([kind, ds]) => h("div", {}, h("div", { class: "muted" }, kind),
    ds.map((d) => { const cb = h("input", { type: "checkbox", checked: chosen.has(d.name), onchange: () => { if (cb.checked) chosen.add(d.name); else chosen.delete(d.name); } });
      return h("label", {}, cb, tagChip(d.name)); }))),
  ...(TAGDEFS.length ? [] : [h("p", { class: "muted" }, "No tags yet. Make the first one below.")]));
  draw();
  const nameIn = h("input", { type: "text", id: "new-tag-name", placeholder: "New tag, e.g. Forever or Remix", maxlength: 40 });
  const kindIn = h("input", { type: "text", id: "new-tag-kind", list: "tag-kinds", value: "Album / EP", style: { width: "130px" }, "aria-label": "Kind of tag" });
  const add = async () => {
    const name = nameIn.value.trim();
    if (!name) return;
    const r = await post("/api/tag", { op: "create", name, kind: kindIn.value.trim() || "Other" });
    if (!r.ok) return toast(r.error);
    TAGDEFS.push(r.tag); chosen.add(r.tag.name); nameIn.value = ""; draw();
  };
  nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
  const body = h("div", {}, list, h("div", { class: "toolbar", style: { marginTop: "10px" } }, nameIn, kindIn,
    h("datalist", { id: "tag-kinds" }, TAGKINDS.map((k) => h("option", { value: k }))),
    h("button", { class: "btn", onclick: add }, "Add")));
  const ok = await modal(`Tags for ${projName(p)}`, body, [{ label: "Cancel", value: false }, { label: "Save", value: true, cls: "primary" }]);
  if (!ok) return;
  const r = await post("/api/ableton/tags", { path: p.path, tags: [...chosen] });
  if (!r.ok) return toast(r.error);
  p.tags = r.tags;
  if (after) after(); else route();
}
async function tagMany(projects) {
  const nameIn = h("input", { type: "text", id: "many-tag", list: "all-tags", placeholder: "Tag name", maxlength: 40, style: { width: "100%" } });
  const body = h("div", {}, h("p", { class: "ink2" }, `Adds a tag to ${projects.length} project${projects.length === 1 ? "" : "s"}. Their other tags stay.`),
    nameIn, h("datalist", { id: "all-tags" }, TAGDEFS.map((d) => h("option", { value: d.name }))),
    TAGDEFS.length ? h("div", { class: "tag-cell", style: { marginTop: "8px" } }, TAGDEFS.map((d) => tagChip(d.name, { onclick: () => { nameIn.value = d.name; } }))) : null);
  const ok = await modal("Add a tag", body, [{ label: "Cancel", value: false }, { label: "Add tag", value: true, cls: "primary" }]);
  if (!ok || !nameIn.value.trim()) return;
  const r = await post("/api/ableton/tags", { paths: projects.map((p) => p.path), add: [nameIn.value.trim()] });
  if (!r.ok) return toast(r.error);
  toast(`Tagged ${projects.length} project${projects.length === 1 ? "" : "s"} “${r.tags[0]}”.`);
  route();
}
function tagCell(p) {
  return h("span", { class: "tag-cell" }, (p.tags || []).map((t) => tagChip(t, { on: tagFilter.has(t), onclick: (e) => {
    e.stopPropagation(); if (tagFilter.has(t)) tagFilter.delete(t); else tagFilter.add(t); route(); } })),
  h("button", { class: "btn small", title: "Add or remove tags", onclick: (e) => { e.stopPropagation(); editTags(p); } }, (p.tags || []).length ? "Edit" : "+ Tag"));
}

async function tagsView(root, data, head) {
  const counts = new Map();
  for (const p of data.projects) for (const t of p.tags || []) counts.set(t, (counts.get(t) || 0) + 1);
  const change = async (body, msg) => {
    const r = await post("/api/tag", body);
    if (!r.ok) return toast(r.error);
    if (msg) toast(msg);
    route();
  };
  const rows = byKind(TAGDEFS).map(([kind, ds]) => h("div", { class: "card" }, h("h2", { style: { margin: "0 0 6px" } }, kind),
    h("table", {}, h("tbody", {}, ds.map((d) => {
      const nameIn = h("input", { type: "text", value: d.name, maxlength: 40, "aria-label": "Tag name",
        onchange: () => nameIn.value.trim() && nameIn.value.trim() !== d.name && change({ op: "update", name: d.name, new_name: nameIn.value.trim() }, "Renamed everywhere it's used.") });
      const kindIn = h("input", { type: "text", value: d.kind, list: "tag-kinds-view", style: { width: "130px" }, "aria-label": "Kind",
        onchange: () => change({ op: "update", name: d.name, kind: kindIn.value.trim() || "Other" }) });
      const colour = h("select", { "aria-label": "Colour", onchange: () => change({ op: "update", name: d.name, color: Number(colour.value) }) },
        [1, 2, 3, 4, 5, 6, 7, 8].map((c) => h("option", { value: c, selected: c === d.color }, ["Blue", "Orange", "Green", "Amber", "Pink", "Dark green", "Purple", "Red"][c - 1])));
      const n = counts.get(d.name) || 0;
      return h("tr", {},
        h("td", { style: { width: "1%" } }, tagChip(d.name)),
        h("td", {}, nameIn), h("td", {}, kindIn), h("td", {}, colour),
        h("td", { class: "num ink2" }, `${n} project${n === 1 ? "" : "s"}`),
        h("td", { style: { width: "1%", whiteSpace: "nowrap" } },
          h("button", { class: "btn small", disabled: !n, onclick: () => { tagFilter.clear(); tagFilter.add(d.name); openTab("projects"); } }, "Show projects"), " ",
          h("button", { class: "btn small", onclick: async () => {
            const ok = await modal(`Delete the tag “${d.name}”?`, h("p", {}, `It's removed from ${n} project${n === 1 ? "" : "s"}. The projects themselves aren't touched.`),
              [{ label: "Cancel", value: false }, { label: "Delete tag", value: true, cls: "danger" }]);
            if (ok) change({ op: "delete", name: d.name }, "Tag deleted.");
          } }, "Delete")));
    })))));
  const nameIn = h("input", { type: "text", id: "tags-new-name", placeholder: "New tag name", maxlength: 40 });
  const kindIn = h("input", { type: "text", id: "tags-new-kind", list: "tag-kinds-view", value: "Album / EP", style: { width: "140px" }, "aria-label": "Kind" });
  root.replaceChildren(head,
    h("datalist", { id: "tag-kinds-view" }, TAGKINDS.map((k) => h("option", { value: k }))),
    h("div", { class: "card", style: { marginBottom: "14px" } }, h("div", { class: "toolbar" }, nameIn, kindIn,
      h("button", { class: "btn primary", onclick: () => nameIn.value.trim() && change({ op: "create", name: nameIn.value.trim(), kind: kindIn.value.trim() || "Other" }, "Tag added.") }, "Add tag"),
      h("span", { class: "ink2" }, "Kinds group your tags: an album, a type of project (Remix, Collab, Sketch), a status…"))),
    TAGDEFS.length ? h("div", { class: "stack" }, rows) : h("div", { class: "card empty" }, h("h2", {}, "No tags yet"),
      h("p", {}, "Add one here, or use ", h("b", {}, "+ Tag"), " on any project. In All projects you can tick several projects and tag them all at once.")));
}

const SLIPPING_DAYS = 30;
const projName = (p) => p.name.replace(/ Project$/, "");
const daysSince = (ts) => Math.floor((Date.now() / 1000 - ts) / 86400);

function starButton(p, after) {
  const btn = h("button", { class: "star" + (p.important ? " on" : ""), "aria-pressed": p.important ? "true" : "false",
    title: p.important ? "Important: click to unmark" : "Mark as important",
    onclick: async (e) => {
      e.stopPropagation();
      const on = !p.important;
      const r = await post("/api/ableton/mark", { path: p.path, important: on });
      if (!r.ok) return toast(r.error);
      p.important = on;
      btn.className = "star" + (on ? " on" : "");
      btn.textContent = on ? "★" : "☆";
      btn.title = on ? "Important: click to unmark" : "Mark as important";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      toast(on ? `${projName(p)} is marked important.` : `${projName(p)} is no longer marked important.`);
      if (after) after();
    } }, p.important ? "★" : "☆");
  return btn;
}

const finderButton = (p) => h("button", { class: "btn small", title: "Show the project folder in Finder",
  onclick: (e) => { e.stopPropagation(); reveal(p.path); } }, "Show in Finder");
const agoText = (ts) => { const v = fmt.ago(ts); return ["today", "yesterday", "—"].includes(v) ? v : v + " ago"; };
const setName = (path) => path.split("/").pop().replace(/\.als$/i, "");

function openInLive(path) {
  post("/api/ableton/open", { path }).then((r) => toast(r.ok ? `Opening ${setName(path)} in Live…` : r.error)).catch((e) => toast(e.message));
}

function setStatus(s) {
  if (s.error) return statusPill("neutral", "Couldn't read", s.error);
  if (s.missing) return statusPill("critical", `${s.missing} missing`, "Files this set uses that can't be found");
  if (s.external) return statusPill("warning", `${s.external} outside project`, "Needs Collect All and Save");
  return statusPill("good", "Self-contained");
}

function setExamples(s) {
  return [(s.examples.external || []).length ? h("div", { class: "path" }, "Elsewhere: ", s.examples.external.map(pretty).join(" · ")) : null,
    missingList(s)];
}

// One player for the whole app: exports and samples play here, streamed by the engine.
const player = {
  el: null,
  play(path, label) {
    if (!this.el) {
      this.audio = h("audio", { controls: true, preload: "auto" });
      this.title = h("div", { class: "player-title" });
      this.audio.addEventListener("error", () => {
        if (this.audio.getAttribute("src")) toast("That file can't be played here. Use Show to find it in Finder.");
      });
      this.el = h("div", { class: "player", role: "region", "aria-label": "Player" },
        h("div", { class: "player-head" }, this.title,
          h("button", { class: "btn small", "aria-label": "Stop and close the player", onclick: () => this.stop() }, "✕")),
        this.audio);
      document.body.append(this.el);
    }
    this.title.replaceChildren(h("b", { class: "trunc" }, label), h("span", { class: "trunc path" }, pretty(path)));
    this.audio.src = `/api/audio?path=${encodeURIComponent(path)}&t=${encodeURIComponent(TOKEN)}`;
    this.el.hidden = false;
    document.body.classList.add("playing");
    this.audio.play().catch(() => {});
  },
  stop() {
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
    this.el.hidden = true;
    document.body.classList.remove("playing");
  },
};
const stem = (name) => name.replace(/\.[^.]+$/, "");
const playButton = (path, label, title) => h("button", { class: "btn small play", title: title || "Play " + label,
  onclick: (e) => { e.stopPropagation(); player.play(path, label); } }, h("span", { "aria-hidden": "true" }, "▶ "), label);

// Exports of the song, and every audio file the set uses. Fetched when you open it.
async function listenPanel(s, panel) {
  panel.replaceChildren(h("span", { class: "muted" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Loading…"));
  let d;
  try {
    d = await get("/api/ableton/set?path=" + encodeURIComponent(s.path));
  } catch (e) {
    return panel.replaceChildren(h("span", { class: "muted" }, e.message));
  }
  const WHERE = { project: "in project", library: "library", elsewhere: "outside project" };
  const row = (path, label, meta) => h("div", { class: "listen-row" }, playButton(path, label),
    h("span", { class: "muted" }, meta), h("span", { class: "spacer" }),
    h("button", { class: "btn small", onclick: (e) => { e.stopPropagation(); reveal(path); } }, "Show"));
  panel.replaceChildren(
    h("div", { class: "listen-h" }, `Exports of this song (${d.bounces.length})`),
    d.bounces.length ? h("div", {}, d.bounces.map((b) => row(b.path, stem(b.name),
      [agoText(b.mtime), fmt.size(b.size), pretty(b.path.slice(0, b.path.lastIndexOf("/"))), b.icloud_only ? "in iCloud, downloads when played" : ""].filter(Boolean).join(" · "))))
      : h("div", { class: "muted" }, "None found. Exports are matched by name: “", setName(s.path), " V3.wav” or “", setName(s.path), " (MASTER).wav” would count."),
    h("div", { class: "listen-h" }, `Audio in this set (${d.ingredients.length})`),
    d.ingredients.length ? h("div", {}, d.ingredients.map((i) => row(i.path, stem(i.name), [WHERE[i.where], fmt.size(i.size)].join(" · "))))
      : h("div", { class: "muted" }, "No audio files: everything in it comes from MIDI and instruments."));
}

function listenControls(s) {
  const b = (s.bounces || [])[0];
  const panel = h("div", { class: "listen-panel", hidden: true });
  const toggle = h("button", { class: "btn small", "aria-expanded": "false", title: "Exports of this song, and the audio files the set uses",
    onclick: (e) => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", String(!panel.hidden));
      if (!panel.hidden && !panel.dataset.loaded) { panel.dataset.loaded = "1"; listenPanel(s, panel); }
    } }, "What's in it");
  const bounce = b ? playButton(b.path, stem(b.name), `Play the newest export: ${pretty(b.path)}`)
    : h("span", { class: "muted", title: "No exported audio with this set's name was found" }, "no bounce yet");
  return { bounce, toggle, panel };
}

// Every set in a project folder (never the Backup copies), each with its own status,
// so a problem in one set isn't mistaken for the whole project.
function setList(p, withDetails) {
  if (!p.sets.length) return null;
  return h("div", { class: "set-list" }, p.sets.map((s) => { const l = listenControls(s); return h("div", { class: "set-item" },
    h("div", { class: "set-line" },
      h("span", { class: "set-name", title: s.path }, setName(s.path)),
      p.sets.length > 1 && s.path === p.newest_set ? h("span", { class: "chip" }, "latest") : null,
      setStatus(s),
      h("span", { class: "muted" }, [s.mtime ? "saved " + agoText(s.mtime) : "", (s.version || "").replace("Ableton Live ", "Live ")].filter(Boolean).join(" · ")),
      h("span", { class: "spacer" }),
      l.bounce, l.toggle,
      h("button", { class: "btn small", title: "Open this set in Live", onclick: (e) => { e.stopPropagation(); openInLive(s.path); } }, "Open in Live"),
      h("button", { class: "btn small", title: "Show this set in Finder", onclick: (e) => { e.stopPropagation(); reveal(s.path); } }, "Show")),
    withDetails && (s.external || s.missing) ? h("div", { class: "set-details" }, setExamples(s)) : null, l.panel); }));
}

function samplesStatus(p) {
  const bad = p.sets.filter((s) => s.missing || s.external).length;
  const which = p.sets.length > 1 && bad ? ` · ${bad} of ${p.sets.length} sets` : "";
  if (p.status === "ok") return statusPill("good", "Self-contained");
  if (p.status === "missing") return statusPill("critical", `${p.missing_total} missing${which}`, "Files a set uses that can't be found. The set list says which set.");
  if (p.status === "external") return statusPill("warning", `${p.external_total} outside project${which}`, "Needs Collect All and Save. The set list says which set.");
  if (p.status === "no-sets") return statusPill("neutral", "No sets");
  return statusPill("neutral", "Couldn't check", "Only in iCloud, or unreadable");
}

function projectTable(projects, cols) {
  return h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", {}, "Project"),
    cols.map((c) => h("th", { class: c.num ? "num" : "" }, c.label)), h("th", {}))),
  h("tbody", {}, projects.map((p) => {
    const detail = h("tr", { class: "detail-row", hidden: true }, h("td", {}), h("td", { colspan: cols.length + 2 }, projectDetail(p)));
    return [h("tr", { class: p.sets.length ? "has-sets" : "" },
      h("td", { class: "check" }, starButton(p)),
      h("td", { class: "name rowlink", onclick: () => (detail.hidden = !detail.hidden) },
        h("span", { class: "trunc", style: { color: "var(--accent)" } }, projName(p)), cloudChip(p),
        h("span", { class: "trunc path", title: p.path }, pretty(p.parent))),
      cols.map((c) => h("td", { class: c.num ? "num ink2" : "" }, c.cell(p))),
      h("td", { style: { width: "1%" } }, finderButton(p))),
      p.sets.length ? h("tr", { class: "sets-row" }, h("td", {}), h("td", { colspan: cols.length + 2 }, setList(p))) : null, detail];
  })));
}

function recentView(root, data, head) {
  const live = data.recent_from_live;
  const byOpened = (a, b) => (a.opened_rank ?? 1e9) - (b.opened_rank ?? 1e9) || (b.mtime || 0) - (a.mtime || 0);
  const all = data.projects.filter((p) => p.status !== "no-sets");
  const list = all.filter(passTags).sort(live ? byOpened : (a, b) => (b.mtime || 0) - (a.mtime || 0)).slice(0, tagFilter.size || projectSearch ? 300 : 30);
  root.replaceChildren(head, filterBar(all),
    list.length ? h("div", { class: "card" }, projectTable(list, [
      live ? { label: "Opened", cell: (p) => p.opened_rank == null ? h("span", { class: "muted" }, "—") : `#${p.opened_rank + 1}` } : null,
      { label: "Last saved", num: true, cell: (p) => fmt.ago(p.mtime) },
      { label: "Samples", cell: samplesStatus },
      { label: "Tags", cell: tagCell },
    ].filter(Boolean)), h("p", { class: "muted" }, "Click a name for details."))
      : h("div", { class: "card empty" }, tagFilter.size || projectSearch ? "No projects match. Clear the filter to see them all." : "No Ableton projects found in the last scan."));
}

// Songs: each project's master, newest bounce and stems in one row, to find and play them.
const MASTER_RE = /(^|[^a-z])(master(ed)?|pre-?master|final)(?![a-z])/i;
let songSort = "saved";
function songExports(p) {
  const stemDirs = new Set((p.stem_groups || []).map((g) => g.folder));  // a stems export's full mix isn't a bounce
  const seen = new Map();
  for (const s of p.sets) for (const b of s.bounces || []) if (!stemDirs.has(b.path.slice(0, b.path.lastIndexOf("/")))) seen.set(b.path, b);
  const all = [...seen.values()].sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
  return { masters: all.filter((b) => MASTER_RE.test(stem(b.name))), bounces: all.filter((b) => !MASTER_RE.test(stem(b.name))) };
}
function songsView(root, data, head) {
  const all = data.projects.filter((p) => p.sets.length);
  const byName = (a, b) => projName(a).localeCompare(projName(b), undefined, { numeric: true, sensitivity: "base" });
  const list = all.filter(passTags).sort(songSort === "name" ? byName : (a, b) => (b.mtime || 0) - (a.mtime || 0));
  const sortSel = h("select", { "aria-label": "Sort songs", onchange: () => { songSort = sortSel.value; route(); } },
    [["saved", "Last saved"], ["name", "Name"]].map(([v, l]) => h("option", { value: v, selected: songSort === v }, "Sort: " + l)));
  const play = (b, none) => b ? playButton(b.path, stem(b.name), `Play ${pretty(b.path)}`) : h("span", { class: "muted" }, none);
  const more = (n, what) => n > 0 ? h("div", { class: "muted" }, `+ ${n} older ${what}${n === 1 ? "" : "s"}`) : null;
  const rows = list.slice(0, 500).map((p) => {
    const { masters, bounces } = songExports(p);
    const groups = p.stem_groups || [];
    const mine = groups.filter((g) => !g.received && !g.copy_of);
    const got = groups.filter((g) => g.received).length, copies = groups.filter((g) => g.copy_of && !g.received).length;
    return h("tr", {},
      h("td", { class: "check" }, starButton(p)),
      h("td", { class: "name", style: { minWidth: "180px" } }, h("b", { class: "trunc", title: p.path }, projName(p)),
        h("div", { style: { marginTop: "3px" } }, tagCell(p))),
      h("td", {}, play(masters[0], "no master yet"), more(masters.length - 1, "master")),
      h("td", {}, play(bounces[0], "none"), more(bounces.length - 1, "bounce")),
      h("td", {}, mine.length ? h("button", { class: "btn small", title: "Show the newest stems in Finder: " + pretty(mine[0].folder),
        onclick: () => reveal(mine[0].folder) }, `${mine.length} export${mine.length === 1 ? "" : "s"}`) : h("span", { class: "muted" }, "none"),
      got ? h("div", { class: "muted" }, `+ ${got} received`) : null,
      copies ? h("div", { class: "muted", title: "Copies of stems already filed in the project. The Plan suggests trashing them." }, `+ ${copies} cop${copies === 1 ? "y" : "ies"}`) : null),
      h("td", { class: "num ink2" }, agoText(p.mtime)),
      h("td", { style: { width: "1%", whiteSpace: "nowrap" } },
        h("button", { class: "btn small", title: "Open the newest set in Live", onclick: () => openInLive(p.newest_set || p.sets[0].path) }, "Open in Live"), " ",
        finderButton(p)));
  });
  root.replaceChildren(head, h("div", { class: "toolbar" }, filterBar(all), sortSel),
    rows.length ? h("div", { class: "card" }, h("div", { style: { overflowX: "auto" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", {}, "Song"),
      h("th", {}, "Master"), h("th", {}, "Newest bounce"), h("th", {}, "Stems"), h("th", { class: "num" }, "Last saved"), h("th", {}))),
    h("tbody", {}, rows))),
    list.length > 500 ? h("p", { class: "muted" }, `Showing 500 of ${list.length}. Search or pick a tag to narrow it down.`) : null,
    h("p", { class: "muted" }, "Exports are matched by name: “Song V3.wav” and “Song (MASTER).wav” belong to the set “Song”. ▶ plays a file; nothing is moved."))
      : h("div", { class: "card empty" }, tagFilter.size || projectSearch ? "No songs match. Clear the filter to see them all." : "No Ableton projects found in the last scan."));
}

function importantView(root, data, head) {
  const starred = data.projects.filter((p) => p.important);
  const list = starred.filter(passTags).sort((a, b) => (a.mtime || 0) - (b.mtime || 0));
  const slipping = list.filter((p) => daysSince(p.mtime) >= SLIPPING_DAYS);
  const away = starred.filter((p) => p.cloud_only);
  root.replaceChildren(head, starred.length ? filterBar(starred) : "",
    away.length ? h("div", { class: "note card", style: { marginBottom: "10px" } },
      `${away.length} starred project${away.length === 1 ? " has" : "s have"} files only in iCloud. Download them before you go offline (a gig, a flight). `,
      downloadButton(away.map((p) => p.path), `${away.length} starred project${away.length === 1 ? "" : "s"}`,
        away.reduce((a, p) => a + p.cloud_only.bytes, 0))) : "",
    slipping.length ? h("div", { class: "warn" }, `${slipping.length} important project${slipping.length === 1 ? " hasn't" : "s haven't"} been saved in over ${SLIPPING_DAYS} days.`) : "",
    list.length ? h("div", { class: "card" }, projectTable(list, [
      { label: "Untouched", num: true, cell: (p) => {
        const d = daysSince(p.mtime);
        const label = d < 1 ? "saved today" : d === 1 ? "1 day" : `${d} days`;
        return d >= SLIPPING_DAYS ? h("b", { style: { color: "var(--serious)" } }, label) : label;
      } },
      { label: "Samples", cell: samplesStatus },
      { label: "Where", cell: (p) => p.in_library ? h("span", { class: "chip" }, p.bucket || "Projects folder") : h("span", { class: "ink2" }, "outside projects folder") },
      { label: "Tags", cell: tagCell },
    ]))
      : h("div", { class: "card empty" }, h("h2", {}, "Nothing starred yet"),
        h("p", {}, "Click the ☆ next to a project in Recent or All projects to keep an eye on it here.")));
}

// Broken projects: "Archive as broken" marks a project so it may move, into a folder
// of its own. "Allow moving anyway" lets one that isn't broken move despite its outside files.
async function setProjectFlag(p, flag, on, msg) {
  const r = await post("/api/ableton/flag", { path: p.path, flag, on });
  if (!r.ok) { toast(r.error); return false; }
  p[flag === "archive_broken" ? "archivable" : "move_anyway"] = on;
  if (msg) toast(msg);
  return true;
}
function archiveButton(p, after) {
  const btn = h("button", { class: "btn small", title: p.archivable ? "Unmark: it stays with your other projects"
    : "Mark this project as broken: it may then move, into its own Broken Projects folder", onclick: async (e) => {
    e.stopPropagation();
    const on = !p.archivable;
    if (await setProjectFlag(p, "archive_broken", on, on ? `${projName(p)} is marked for the broken archive.` : `${projName(p)} is no longer marked as broken.`)) (after || route)();
  } }, p.archivable ? "✓ Marked broken" : "Archive as broken");
  return btn;
}
function moveAnywayToggle(p) {
  if (p.status !== "external" && p.status !== "missing" && !p.move_anyway) return null;
  const cb = h("input", { type: "checkbox", checked: !!p.move_anyway, onchange: async () => {
    if (!(await setProjectFlag(p, "move_anyway", cb.checked, cb.checked
      ? `${projName(p)} may be moved even though it uses files outside its folder.` : `${projName(p)} stays put until it's self-contained.`))) cb.checked = !cb.checked;
  } });
  return h("label", { class: "ink2", title: "Projects that use outside files, or miss some, never move unless you allow it" }, cb, " Allow moving anyway");
}
async function moveBroken(data) {
  const todo = data.projects.filter((p) => p.archivable && !p.in_broken);
  if (!todo.length) return toast("No projects are marked as broken.");
  const ok = await confirmItems(`Move ${todo.length} broken project${todo.length === 1 ? "" : "s"}?`,
    todo.map((p) => ({ label: projName(p), detail: "→ " + pretty(data.broken_dir), bytes: p.alloc })), "Move to Broken Projects",
    "They keep their outside and missing files as they are: nothing inside them changes. Close Live first. You can undo the whole batch from History.");
  if (!ok) return;
  await runActions(todo.map((p) => ({ path: p.path, action: "move", dest: data.broken_dir, bytes: p.alloc })),
    `Broken projects · ${todo.length} archived`);
  route();
}
function brokenCard(data) {
  const marked = data.projects.filter((p) => p.archivable);
  if (!marked.length) return "";
  const waiting = marked.filter((p) => !p.in_broken);
  return h("div", { class: "card", style: { marginBottom: "14px" } },
    h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, `Marked as broken (${marked.length})`),
      h("span", { class: "ink2" }, waiting.length ? `${waiting.length} still to move into ${pretty(data.broken_dir)}` : `All in ${pretty(data.broken_dir)}`),
      h("div", { class: "spacer" }),
      waiting.length ? h("button", { class: "btn primary", onclick: () => moveBroken(data) }, `Move ${waiting.length} to Broken Projects`) : null),
    h("div", { class: "tag-cell", style: { maxWidth: "none", marginTop: "6px" } }, marked.map((p) =>
      h("span", { class: "chip", title: pretty(p.path) }, projName(p), p.in_broken ? " ✓" : "", " ",
        h("button", { class: "btn small", title: "Unmark", "aria-label": "Unmark " + projName(p), onclick: async () => {
          if (await setProjectFlag(p, "archive_broken", false, `${projName(p)} is no longer marked as broken.`)) route();
        } }, "×")))));
}

// Where a project's missing files are now, and which folder to point Live's search at.
async function findMissing(p) {
  toast(`Looking for ${projName(p)}'s missing files…`, 2000);
  let r;
  try { r = await get("/api/ableton/missing?project=" + encodeURIComponent(p.path)); } catch (e) { return toast(e.message); }
  if (r.error) return toast(r.error);
  const steps = h("ol", {},
    h("li", {}, "In Live, open the set (", h("b", {}, "Open in Live"), " in Collect All)."),
    h("li", {}, "Choose ", h("b", {}, "File → Manage Files"), ", then ", h("b", {}, "Manage Set"), "."),
    h("li", {}, "Under Missing Samples, click ", h("b", {}, "Locate"), ". Set ", h("b", {}, "Search Folder"), " to the folder above and click ", h("b", {}, "Go"), ". Live finds them by name."),
    h("li", {}, "Save the set, then ", h("b", {}, "Re-check"), " here."));
  const body = h("div", {},
    h("p", {}, `${r.missing} missing file${r.missing === 1 ? "" : "s"}: `, h("b", {}, `${r.findable} found elsewhere on this Mac`),
      r.gone ? `, ${r.gone} gone for good` : "", "."),
    r.folders.length ? h("div", { class: "card note", style: { margin: "8px 0" } }, h("b", {}, "Point Live's search at:"),
      r.folders.map((f) => h("div", { class: "path" }, pretty(f.folder), ` (${f.covers} file${f.covers === 1 ? "" : "s"}) `,
        h("button", { class: "btn small", onclick: () => reveal(f.folder) }, "Show")))) : null,
    r.folders.length ? steps : h("p", { class: "ink2" }, "None of them were found by name on this Mac. If they're gone for good, ", h("b", {}, "Archive as broken"), " keeps the project out of the way."),
    h("details", {}, h("summary", {}, "Every missing file"),
      h("div", { style: { maxHeight: "40vh", overflow: "auto" } }, r.sets.map((s) => h("div", { style: { marginTop: "8px" } },
        h("b", {}, setName(s.set)), s.newest ? h("span", { class: "chip" }, "newest") : null,
        s.error ? h("span", { class: "muted" }, " couldn't be read") : h("span", { class: "ink2" }, ` ${s.found} of ${s.missing} found`),
        h("ul", {}, (s.items || []).map((i) => h("li", {}, h("b", {}, i.name),
          i.candidates.length ? h("div", { class: "path" }, "Now at: ", pretty(i.candidates[0]), i.candidates.length + i.more > 1 ? ` (+${i.candidates.length + i.more - 1} more)` : "")
            : h("div", { class: "muted" }, i.gone ? `Gone: ${i.gone}.` : "Not found on this Mac.")))))))));
  await modal(`Missing files in ${projName(p)}`, body);
}
// Projects not saved in over 2 years whose newest set misses files: mark them broken in one go.
const OLD_DAYS = 730;
function oldBrokenCard(data) {
  const old = data.projects.filter((p) => !p.archivable && !p.movable && p.status === "missing" && daysSince(p.mtime) > OLD_DAYS);
  if (!old.length) return "";
  const review = async () => {
    const picked = new Set(old.map((p) => p.path));
    const list = h("div", { style: { maxHeight: "50vh", overflow: "auto" } }, old.map((p) => {
      const cb = h("input", { type: "checkbox", checked: true, onchange: () => { if (cb.checked) picked.add(p.path); else picked.delete(p.path); } });
      return h("label", { style: { display: "flex", gap: "8px", alignItems: "baseline", padding: "2px 0" } }, cb,
        h("span", {}, h("b", {}, projName(p)), " ", h("span", { class: "ink2" }, `${agoText(p.mtime)} · ${p.missing_total} missing`),
          h("div", { class: "path" }, pretty(p.parent))));
    }));
    const ok = await modal(`Mark ${old.length} old projects as broken?`, h("div", {},
      h("p", { class: "ink2" }, "Untick any you want to keep fixing. Marking only allows them to move into Broken Projects; nothing moves yet."), list),
    [{ label: "Cancel", value: false }, { label: "Mark as broken", value: true, cls: "primary" }]);
    if (!ok || !picked.size) return;
    const r = await post("/api/ableton/flag", { paths: [...picked], flag: "archive_broken", on: true });
    if (!r.ok) return toast(r.error);
    toast(`Marked ${r.count} project${r.count === 1 ? "" : "s"} as broken.`);
    route();
  };
  return h("div", { class: "card", style: { marginBottom: "14px" } }, h("div", { class: "toolbar" },
    h("h2", { style: { margin: 0 } }, `Old and broken (${old.length})`),
    h("span", { class: "ink2" }, "Not saved in over 2 years, and the newest set misses files."), h("div", { class: "spacer" }),
    h("button", { class: "btn", onclick: review }, "Review and mark as broken")));
}

function collectView(root, data, head) {
  const needs = data.projects.filter((p) => (p.status === "external" || p.status === "missing") && !p.archivable);
  const unchecked = data.projects.filter((p) => p.status === "unknown");
  const loose = data.loose_sets.filter((s) => s.external || s.missing);
  const countEl = h("h2", {}, "");
  const setCount = () => {
    const n = needs.filter((p) => p.status === "external" || p.status === "missing").length;
    countEl.textContent = n ? `${n} project${n === 1 ? "" : "s"} to collect` : "All collected";
    const tab = document.querySelector(".seg button.on");
    if (tab) tab.textContent = n ? `Collect All (${n})` : "Collect All";
  };
  // Re-reads one project and swaps in its new row: no page reload, so you stay where you were.
  const recheck = async (p, row, btn) => {
    btn.disabled = true;
    btn.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), "Checking…");
    row.classList.add("busy");
    try {
      const r = await post("/api/ableton/recheck", { project: p.path });
      if (!r.ok) { toast(r.error); return; }
      if (r.item) {
        needs[needs.indexOf(p)] = r.item;
        row.replaceWith(collectRow(r.item, true));
        setCount();
      }
      const ext = r.sets.reduce((a, s) => a + (s.external || 0), 0);
      const miss = r.sets.reduce((a, s) => a + (s.missing || 0), 0);
      toast(r.status === "ok" ? `${projName(p)} is self-contained now.`
        : r.status === "unknown" ? `Some sets in ${projName(p)} couldn't be read.`
          : `${projName(p)} still has ${ext ? `${ext} file${ext === 1 ? "" : "s"} outside the project` : ""}${ext && miss ? " and " : ""}${miss ? `${miss} missing` : ""}.`, 6000);
    } catch (e) {
      toast(e.message);
    } finally {
      if (btn.isConnected) {
        btn.disabled = false;
        btn.textContent = "Re-check";
        row.classList.remove("busy");
      }
    }
  };
  const collectRow = (p, justChecked) => {
    const sets = p.sets.filter((s) => s.external || s.missing);
    const done = p.status === "ok";
    const btn = h("button", { class: "btn small", title: "Read the project again after you've collected it" }, "Re-check");
    const hasMissing = sets.some((s) => s.missing);
    const row = h("div", { class: "collect-row" + (justChecked ? " checked" : "") },
      h("div", { class: "toolbar" }, starButton(p),
        h("div", { style: { minWidth: 0, flex: "1 1 240px" } }, h("b", {}, projName(p)), " ", h("span", { class: "ink2" }, agoText(p.mtime)),
          h("div", { class: "trunc path", title: p.path }, pretty(p.path))),
        done ? statusPill("good", "Self-contained now") : samplesStatus(p),
        !done && p.movable ? statusPill("good", "Safe to move", "Its newest set is self-contained; only older versions in the folder aren't collected") : null,
        finderButton(p),
        hasMissing ? h("button", { class: "btn small", title: "Copy what Mac Cleaner found, to paste into a message",
          onclick: () => copyDetails(p) }, "Copy details") : null,
        done ? null : btn, hasMissing ? h("button", { class: "btn small", title: "Look for the missing files elsewhere on this Mac",
          onclick: () => findMissing(p) }, "Find missing") : null, done ? null : archiveButton(p)),
      h("div", { class: "collect-sets" }, setList(p, true)));
    btn.onclick = () => recheck(p, row, btn);
    return row;
  };
  const rows = needs.map((p) => collectRow(p));
  setCount();
  root.replaceChildren(head,
    h("div", { class: "card note", style: { marginBottom: "14px" } },
      h("h2", {}, "How to fix each one"),
      h("ol", {},
        h("li", {}, "Click ", h("b", {}, "Open in Live"), " next to the set that needs it. Each set in a project folder is listed separately."),
        h("li", {}, data.collect_steps),
        h("li", {}, "Back here, click ", h("b", {}, "Re-check"), ". The project drops off this list once it's self-contained.")),
      h("p", { class: "ink2" }, "A project may move once its newest set is self-contained; older versions in the folder don't count. Until then it never moves, unless you allow it. Old ones that are too broken to fix: click ",
        h("b", {}, "Archive as broken"), " to put them in a folder of their own."),
      h("p", { class: "ink2" }, h("b", {}, "Missing"), " files are ones Mac Cleaner can't find (often old paths, or samples on a drive that isn't plugged in). ",
        "Collect All can't copy those. To see whether Live agrees, open the set and choose File → Manage Files → Manage Set: it lists any missing files and has a Locate button. ",
        "If Live says nothing is missing, Mac Cleaner got it wrong: click ", h("b", {}, "Copy details"), " and send it so it can be fixed.")),
    brokenCard(data), oldBrokenCard(data),
    rows.length ? h("div", { class: "card" }, countEl,
      h("p", { class: "ink2" }, "Newest first. These use samples from outside their project folder, so they could break if those files move."),
      h("div", { class: "stack" }, rows))
      : h("div", { class: "card empty" }, h("h2", {}, "Every project is self-contained"), h("p", {}, "Nothing to collect. Nice.")),
    loose.length ? h("div", { class: "card", style: { marginTop: "14px" } }, h("h2", {}, `Sets outside a project folder (${loose.length})`),
      h("p", { class: "ink2" }, "Open each in Live, use File → Save Live Set As… to give it its own project folder, then Collect All and Save."),
      h("table", {}, h("tbody", {}, loose.map((s) => h("tr", {},
        h("td", { class: "name" }, h("span", { class: "trunc" }, pretty(s.path)), setExamples(s)),
        h("td", {}, statusPill(s.missing ? "critical" : "warning", `${s.external + s.missing} files elsewhere`)),
        h("td", { style: { width: "1%", whiteSpace: "nowrap" } }, h("button", { class: "btn small", onclick: () => openInLive(s.path) }, "Open in Live"), " ",
          h("button", { class: "btn small", onclick: () => reveal(s.path) }, "Show"))))))) : "",
    unchecked.length ? h("div", { class: "card", style: { marginTop: "14px" } }, h("h2", {}, `Couldn't check (${unchecked.length})`),
      h("p", { class: "ink2" }, "These sets are only in iCloud or couldn't be read. In Finder, right-click the folder → Download Now, then rescan."),
      h("table", {}, h("tbody", {}, unchecked.map((p) => h("tr", {},
        h("td", { class: "name" }, h("span", { class: "trunc" }, projName(p)), h("span", { class: "trunc path" }, pretty(p.path))),
        h("td", { style: { width: "1%" } }, finderButton(p))))))) : "");
}

// Missing files, with where in the set each one is used (scans from 0.7.1 on).
function missingList(s) {
  const detail = s.examples.missing_detail;
  if (detail && detail.length) {
    return h("div", { class: "path" }, "Missing:", detail.map((d) => h("div", { class: "missing-item" },
      pretty(d.path || d.rel), d.where ? h("span", { class: "muted" }, " — in " + d.where) : null)));
  }
  return (s.examples.missing || []).length ? h("div", { class: "path" }, "Missing: ", s.examples.missing.map(pretty).join(" · ")) : null;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const ta = h("textarea", { style: { position: "fixed", opacity: "0" } }, text);
    document.body.append(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
    return ok;
  }
}

async function copyDetails(p) {
  const lines = [`Mac Cleaner ${STATUS ? STATUS.version : ""}: missing files in ${p.path}`];
  for (const s of p.sets.filter((x) => x.missing)) {
    lines.push("", `Set: ${s.path.split("/").pop()} (${s.version || "unknown Live version"}): ${s.missing} missing of ${s.refs}`);
    const detail = s.examples.missing_detail;
    if (!detail) { lines.push("  (rescan to get details)", ...(s.examples.missing || []).map((m) => "  " + m)); continue; }
    for (const d of detail) {
      lines.push(`- Path: ${d.path || "(none)"}`, `  RelativePath: ${d.rel || "(none)"}  RelativePathType: ${d.rel_type || "(none)"}`,
        `  Pack: ${d.pack || "(none)"}`, `  In: ${d.where || "(unknown)"}`, `  XML: ${d.xml}`);
    }
  }
  const text = lines.join("\n");
  if (await copyText(text)) return toast("Copied. Paste it into a message.");
  modal("Details", h("textarea", { class: "code", readonly: true, style: { width: "100%", height: "40vh" } }, text));
}

function statusPill(kind, label, title) {
  return h("span", { class: `status ${kind}`, title: title || null }, h("span", { class: "dot" }), label);
}

async function packsView(root) {
  const data = await get("/api/packs");
  if (!data.has_scan) return noScan(root);
  const packs = data.packs;
  const sum = (xs) => xs.reduce((a, p) => a + (p.alloc || 0), 0);
  const installed = packs.filter((p) => p.exists);
  const used = packs.filter((p) => p.status === "used");
  const unused = packs.filter((p) => p.status === "unused");
  const missingUsed = packs.filter((p) => p.status === "missing-used");
  const pill = (p) => ({
    "used": statusPill("good", "In use"),
    "unused": statusPill("neutral", "Not used", "No set or preset on this Mac loads anything from it"),
    "unknown": statusPill("warning", "Unknown", "Nothing that could be read uses it, but some sets or presets couldn't be read"),
    "missing-used": statusPill("critical", p.listed || p.path ? "Missing, but used" : "Not installed, but used"),
    "missing": statusPill("neutral", "Listed by Live, not on disk"),
  })[p.status];
  const tbody = h("tbody", {});
  for (const p of packs) {
    const n = p.sets.length + p.presets.length;
    const detail = h("tr", { class: "detail-row", hidden: true }, h("td", { colspan: 5 },
      p.sets.length ? h("div", {}, h("b", {}, "Sets: "), p.sets.map(pretty).join(" · ")) : null,
      p.presets.length ? h("div", {}, h("b", {}, "Presets and racks: "), p.presets.map(pretty).join(" · ")) : null));
    const usedBy = n ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); detail.hidden = !detail.hidden; } },
      [p.sets.length ? `${p.sets.length} set${p.sets.length === 1 ? "" : "s"}` : "", p.sets.length && p.presets.length ? ", " : "",
        p.presets.length ? `${p.presets.length} preset${p.presets.length === 1 ? "" : "s"}` : ""].join(""))
      : h("span", { class: "muted" }, "nothing");
    tbody.append(h("tr", {},
      h("td", { class: "name" }, h("span", { class: "trunc" }, p.name), p.path ? h("span", { class: "trunc path" }, pretty(p.path)) : null),
      h("td", { class: "num" }, p.alloc == null ? h("span", { class: "muted" }, p.exists ? "not scanned" : "—") : fmt.size(p.alloc)),
      h("td", {}, usedBy),
      h("td", {}, pill(p)),
      h("td", {}, p.exists ? h("button", { class: "btn small", onclick: () => reveal(p.path) }, "Show") : null)), detail);
  }
  root.replaceChildren(
    abletonHeader("Each installed Pack, and which of your sets and presets (including racks in your User Library) load something from it."),
    data.rescan_needed ? h("div", { class: "warn" }, "This scan is from an older version that only read sets. Rescan so presets and racks are checked too; until then, nothing here is called unused.") : "",
    data.unchecked ? h("div", { class: "warn" }, `${data.unchecked} set${data.unchecked === 1 ? "" : "s"} or preset${data.unchecked === 1 ? "" : "s"} couldn't be read (only in iCloud, or damaged), so no Pack is called unused. `,
      "To check them: in Finder, right-click the folder → Download Now, then rescan.") : "",
    !data.cfg_found ? h("div", { class: "note" }, "Live's settings (Library.cfg) weren't found, so this lists the Pack folders on disk.") : "",
    h("div", { class: "grid tiles" },
      tile("Installed Packs", fmt.count(installed.length), fmt.size(sum(installed))),
      tile("In use", fmt.count(used.length), fmt.size(sum(used))),
      tile("Not used", data.rescan_needed ? "—" : fmt.count(unused.length), unused.length ? fmt.size(sum(unused)) : "nothing can be called unused yet"),
      missingUsed.length ? tile("Missing but used", fmt.count(missingUsed.length), "reinstall these, or sets and presets break") : null),
    h("div", { class: "card" },
      h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Pack"), h("th", { class: "num" }, "Size"), h("th", {}, "Used by"),
        h("th", {}, "Status"), h("th", {}))), tbody),
      h("p", { class: "ink2" }, "Mac Cleaner never moves or deletes Packs. To remove one you don't use, do it from Live's browser (Packs), so Live knows it's gone. ",
        "For a Pack that's missing but used, reinstall it from Live's browser or your Ableton account.")));
}

VIEWS.music = async (root) => {
  if (musicTab === "packs") return packsView(root);
  const data = await get("/api/ableton");
  if (!data.has_scan) return noScan(root);
  TAGDEFS = data.tag_defs || [];
  TAGKINDS = data.tag_kinds || [];
  const t = data.totals;
  const counts = { important: data.projects.filter((p) => p.important).length, collect: t.needs_collect };
  const sub = {
    recent: data.recent_from_live
      ? "Your projects in the order Live last opened them (from Live's own recent list), then by last saved. Star the ones you don't want to lose track of."
      : "Your projects by when a set in them was last saved (Live's recently-opened list wasn't found). Star the ones you don't want to lose track of.",
    songs: "Every song with its master, its newest bounce and its stems in one place. Play them from here, or open the set in Live.",
    important: "Projects you've starred, the ones you haven't touched longest first, so nothing slips through the cracks.",
    collect: "Projects that use files from outside their folder. Collect All and Save makes them safe to move.",
    projects: "Every Ableton project found on this Mac, where it lives, and whether it's safe to move.",
    tags: "Your tags: name them, group them by kind (an album, a type of project), and use them to find projects. Tags are kept by Mac Cleaner; nothing is written into the projects.",
  }[musicTab];
  const head = abletonHeader(sub, counts);
  if (musicTab === "recent") return recentView(root, data, head);
  if (musicTab === "important") return importantView(root, data, head);
  if (musicTab === "collect") return collectView(root, data, head);
  if (musicTab === "tags") return tagsView(root, data, head);
  if (musicTab === "songs") return songsView(root, data, head);
  const now = Date.now() / 1000;
  const suggestBucket = (p) => {
    if (p.bucket) return p.bucket;
    const age = (now - p.mtime) / 86400;
    const b = data.buckets;
    if (age < 45 && b.includes("Active")) return "Active";
    if (age < 365 && b.includes("Ideas")) return "Ideas";
    return b.includes("Archive") ? "Archive" : b[0];
  };

  const selected = new Map();
  const target = new Map();
  const updateBar = () => {
    const items = [...selected.values()];
    actionbar.set(items.length, `${items.length} project${items.length > 1 ? "s" : ""} selected`, [
      h("button", { class: "btn", onclick: () => tagMany(items) }, "Add tag"),
      h("button", { class: "btn primary", onclick: async () => {
        const todo = items.filter((p) => !(p.in_library && p.bucket === target.get(p.path)));
        if (!todo.length) return toast("Those are already in the chosen buckets.");
        const risky = todo.filter((p) => !p.movable);
        const ok = await confirmItems(`Move ${todo.length} project(s)?`, todo.map((p) => ({
          label: p.name, detail: "→ " + pretty(data.root + "/" + target.get(p.path)),
        })), "Move", (risky.filter((p) => !p.move_anyway && !p.archivable).length
          ? `${risky.filter((p) => !p.move_anyway && !p.archivable).length} of these use files outside the project folder, so they'll be skipped. ${COLLECT_ALL} Or allow moving them in their details. ` : "")
          + "Close these sets in Live before moving them.");
        if (!ok) return;
        await runActions(todo.map((p) => ({ path: p.path, action: "move", dest: data.root + "/" + target.get(p.path) })), `Projects · ${todo.length} moved`);
        route();
      } }, "Move to chosen buckets"),
    ]);
  };

  const tbody = h("tbody", {});
  const passCheck = (p) => checklistFilter === "all" || (checklistFilter === "organised" && checkScore(p.checklist) === 3)
    || (checklistFilter === "almost" && checkScore(p.checklist) === 2) || (checklistFilter === "needs" && checkScore(p.checklist) <= 1)
    || (checklistFilter === "broken" && p.archivable) || (checklistFilter === "icloud" && p.cloud_only);
  for (const p of data.projects) {
    if (!passCheck(p) || !passTags(p)) continue;
    target.set(p.path, suggestBucket(p));
    const cb = h("input", { type: "checkbox", "aria-label": "Select " + p.name, onchange: () => {
      if (cb.checked) selected.set(p.path, p); else selected.delete(p.path);
      updateBar();
    } });
    const sel = h("select", { "aria-label": "Bucket for " + p.name, onchange: () => target.set(p.path, sel.value) },
      data.buckets.map((b) => h("option", { value: b, selected: b === target.get(p.path) }, b)));
    const where = p.in_library ? h("span", { class: "chip" }, p.bucket ? "Projects · " + p.bucket : "Projects · unsorted")
      : h("span", { class: "trunc ink2", title: p.parent }, pretty(p.parent));
    const detail = h("tr", { class: "detail-row", hidden: true }, h("td", {}), h("td", {}), h("td", { colspan: 9 }, projectDetail(p)));
    const nameCell = h("td", { class: "name rowlink", style: { minWidth: "200px" }, onclick: () => (detail.hidden = !detail.hidden) },
      h("span", { class: "trunc", style: { color: "var(--accent)" } }, p.name.replace(/ Project$/, "")),
      p.possible_copies.length ? h("span", { class: "status warning" }, h("span", { class: "dot" }), `${p.possible_copies.length} possible cop${p.possible_copies.length > 1 ? "ies" : "y"}`) : null,
      p.archivable ? h("span", { class: "chip", title: "Marked “Archive as broken”" }, "Broken") : null,
      p.move_anyway ? h("span", { class: "chip", title: "Allowed to move although it uses outside files" }, "May move") : null,
      cloudChip(p),
      h("div", { style: { marginTop: "3px" } }, tagCell(p)));
    tbody.append(h("tr", { class: p.sets.length ? "has-sets" : "" },
      h("td", { class: "check" }, cb), h("td", { class: "check" }, starButton(p)), nameCell,
      h("td", { style: { maxWidth: "220px" } }, where),
      h("td", {}, samplesStatus(p)),
      h("td", {}, checklistCell(p)),
      h("td", { class: "ink2" }, (p.version || "").replace("Ableton Live ", "")),
      h("td", { class: "num" }, fmt.size(p.alloc)),
      h("td", { class: "num ink2" }, fmt.ago(p.mtime)),
      h("td", { class: "num muted" }, p.backup_bytes ? fmt.size(p.backup_bytes) : ""),
      h("td", {}, sel)),
      p.sets.length ? h("tr", { class: "sets-row" }, h("td", {}), h("td", {}), h("td", { colspan: 9 }, setList(p))) : "", detail);
  }

  const maxLoc = Math.max(1, ...data.locations.map((l) => l.count));
  const locs = h("table", {}, h("tbody", {}, data.locations.map((l) => h("tr", {},
    h("td", { class: "name" }, h("span", { class: "trunc" }, pretty(l.location)),
      h("div", { class: "inbar" }, h("span", { style: { width: `${(100 * l.count) / maxLoc}%`, background: "var(--c1)" } }))),
    h("td", { class: "num" }, `${l.count}`), h("td", { class: "num muted" }, fmt.size(l.alloc))))));

  const loose = data.loose_sets.length ? h("div", { class: "card" }, h("h2", {}, `Sets outside a project folder (${data.loose_sets.length})`),
    h("p", { class: "ink2" }, "Open each in Live and use File → Save Live Set As… to give it its own project folder, then File → Collect All and Save (tick Elsewhere, Other Projects, User Library and Factory Packs)."),
    h("table", {}, h("tbody", {}, data.loose_sets.map((s) => h("tr", {},
      h("td", { class: "name" }, h("span", { class: "trunc" }, pretty(s.path))),
      h("td", {}, s.error ? h("span", { class: "muted" }, s.error) : s.external || s.missing
        ? h("span", { class: "status warning" }, h("span", { class: "dot" }), `${s.external + s.missing} files elsewhere`) : h("span", { class: "muted" }, "no samples")),
      h("td", { style: { width: "1%", whiteSpace: "nowrap" } }, h("button", { class: "btn small", onclick: () => openInLive(s.path) }, "Open in Live"), " ",
        h("button", { class: "btn small", onclick: () => reveal(s.path) }, "Show"))))))) : null;

  root.replaceChildren(
    head,
    h("div", { class: "grid tiles" },
      tile("Projects", fmt.count(t.projects), fmt.size(t.alloc)),
      tile("Outside your projects folder", fmt.count(t.outside_library), "should move into " + pretty(data.root)),
      tile("Need Collect All and Save", fmt.count(t.needs_collect), "use samples outside the project, or have missing ones", () => openTab("collect")),
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
    data.template_problem ? h("div", { class: "warn" }, "Live's default template is missing (", pretty(data.template_problem),
      "), so new sets start empty. In Live, open a set you like and use File → Save Live Set As Default Set.") : "",
    data.tracks_rescan_needed ? h("div", { class: "note card", style: { marginBottom: "10px" } },
      "Rescan once so Mac Cleaner reads each set's track names and every audio file. That's how stems get matched to projects when their names differ, and how missing samples are found again.") : "",
    data.exports && data.exports.unmatched_groups.length ? h("div", { class: "note card", style: { marginBottom: "10px" } },
      `${data.exports.unmatched_groups.length} stem export${data.exports.unmatched_groups.length === 1 ? "" : "s"} didn't match a project. `,
      "Open their folders in the ", h("a", { href: "#plan" }, "Plan"), " tab to choose where they go.") : "",
    checklistFilter === "icloud" ? "" : icloudNotice(data.icloud) || "",
    filterBar(data.projects),
    brokenCard(data),
    h("div", { class: "card", style: { marginBottom: "14px" } },
      h("div", { class: "toolbar" }, h("h2", { style: { margin: 0 } }, "Projects"),
        h("div", { class: "seg" }, [["all", "All"], ["organised", `Organised (${data.projects.filter((p) => checkScore(p.checklist) === 3).length})`],
          ["almost", "Almost"], ["needs", "Needs work"], ["broken", `Broken (${data.projects.filter((p) => p.archivable).length})`],
          ["icloud", `Only in iCloud (${data.projects.filter((p) => p.cloud_only).length})`]].map(([k, l]) =>
          h("button", { class: checklistFilter === k ? "on" : "", onclick: () => { checklistFilter = k; route(); } }, l))),
        h("span", { class: "ink2" }, "Click a name for details. The last column is the suggested bucket.")),
      h("div", { style: { overflowX: "auto" } }, h("table", {}, h("thead", {}, h("tr", {}, h("th", { class: "check" }), h("th", { class: "check" }), h("th", {}, "Project"), h("th", {}, "Location"),
        h("th", {}, "Samples"), h("th", { title: "Self-contained, has a master, has stems" }, "Organised?"), h("th", {}, "Live"), h("th", { class: "num" }, "Size"), h("th", { class: "num" }, "Last saved"),
        h("th", { class: "num" }, "Backups"), h("th", {}, "Bucket"))), tbody))),
    loose || "");
};

// The organising checklist: self-contained, has a master, has stems.
let checklistFilter = "all";
function checkScore(c) {
  if (!c) return 0;
  return [c.self_contained, ["in", "not-needed"].includes(c.master), c.stems === "in" || (c.stems === "none" && c.master === "not-needed")]
    .filter(Boolean).length;
}
function checklistCell(p) {
  const c = p.checklist;
  if (!c) return null;
  const samples = c.self_contained ? ["good", "Samples", "Everything the sets use is inside the project"]
    : c.status === "missing" ? ["critical", "Samples", "Some files are missing"]
    : c.status === "external" ? ["warning", "Samples", "Uses files outside the project: Collect All and Save"]
    : ["neutral", "Samples", "Not checked yet"];
  const master = { in: ["good", "Master", "A master is in the project's Exports/Master"],
    elsewhere: ["warning", "Master", "A master was found outside the project"],
    "not-needed": ["neutral", "Master", "Marked as not needing a master"], none: ["neutral", "Master", "No master found"] }[c.master];
  const stems = { in: ["good", "Stems", "Stems are inside the project"], elsewhere: ["warning", "Stems", "Stems were found outside the project"],
    none: ["neutral", "Stems", "No stems found"] }[c.stems];
  return h("span", { style: { display: "inline-flex", gap: "8px" } }, [samples, master, stems].map(([cls, label, title]) =>
    h("span", { class: "status " + cls, title }, h("span", { class: "dot" }), label)));
}
function organisingDetail(p) {
  const c = p.checklist;
  if (!c) return null;
  const flag = h("input", { type: "checkbox", checked: c.master === "not-needed", "aria-label": "Doesn't need a master",
    onchange: async () => {
      const r = await post("/api/ableton/flag", { path: p.path, flag: "no_master", on: flag.checked });
      if (!r.ok) toast(r.error); else route();
    } });
  const fileLine = (path) => h("div", { class: "path" }, pretty(path), " ", h("button", { class: "btn small", onclick: () => reveal(path) }, "Show"));
  return h("div", { class: "card note", style: { margin: "6px 0" } },
    h("h3", { style: { margin: "0 0 6px" } }, "Getting it organised"),
    h("div", {}, c.self_contained && c.status !== "ok" ? "✓ Samples: the newest set is self-contained, so it's safe to move. Older versions in the folder aren't collected; that doesn't stop it moving."
      : c.self_contained ? "✓ Samples: everything the sets use is inside the project."
      : c.status === "external" ? "Samples: uses files outside the project. " + COLLECT_ALL
      : c.status === "missing" ? "Samples: some files are missing. Open the set in Live to find them." : "Samples: not checked yet. Rescan."),
    c.self_contained ? null : h("div", { class: "toolbar", style: { marginTop: "4px" } }, archiveButton(p), moveAnywayToggle(p),
      h("span", { class: "muted" }, "Until then, it never moves.")),
    h("div", { style: { marginTop: "6px" } },
      c.master === "in" ? "✓ Master: in Exports/Master." : c.master === "not-needed" ? "Master: not needed." :
        c.master === "elsewhere" ? "Master: found outside the project (it'll be filed into Exports/Master in a later version):" : "Master: none found.",
      " ", h("label", { class: "muted" }, flag, " Doesn't need a master")),
    (c.master === "in" ? c.masters_in : c.masters_elsewhere).map(fileLine),
    h("div", { style: { marginTop: "6px" } }, stemsLine(p.stem_groups)),
    p.stem_groups.map((g) => h("div", { class: "path" }, confidencePill(g.confidence), " ",
      h("b", {}, g.prefix), ` · ${g.count} files · ${fmt.size(g.bytes)} · ${agoText(g.first)} · `, pretty(g.folder),
      g.stem_prep ? h("span", { class: "chip", title: "Matched to a Stem Prep run record" }, "Stem Prep") : null,
      g.received ? h("span", { class: "chip", title: "Stems that came from somewhere else (sent to you, or exported from another project), not ones you exported from this one. The Plan files them in Samples/Received Stems." }, "Received") : null,
      g.copy_of ? h("span", { class: "chip", title: "Every file is also in " + pretty(g.copy_of) }, g.copy_checked ? "Copy" : "Likely a copy") : null,
      h("div", { class: "muted" }, g.why), " ", h("button", { class: "btn small", onclick: () => reveal(g.folder) }, "Show"))));
}

function stemsLine(groups) {
  const mine = groups.filter((g) => !g.received).length, got = groups.length - mine;
  if (!groups.length) return "Stems: none found.";
  const bits = [mine ? `${mine} export${mine === 1 ? "" : "s"} found` : "none exported yet", got ? `${got} set${got === 1 ? "" : "s"} of stems from somewhere else` : null];
  return "Stems: " + bits.filter(Boolean).join(", ") + ".";
}

// Files the last scan saw only in iCloud (Optimise Mac Storage removed the copy on this Mac).
const KEEP_DOWNLOADED = "Keep Downloaded (here, or in Finder: right-click the folder → Keep Downloaded).";
const inICloud = (path) => [HOME + ICLOUD_REL, HOME + "/Desktop", HOME + "/Documents"].some((b) => path.startsWith(b + "/"));
// Keep Downloaded: the same setting as Finder's. A folder inside a kept folder is kept too.
function keepButton(path, keptBy, after) {
  const set = async (on) => {
    const r = await post("/api/icloud/keep", { path, on });
    if (!r.ok) return toast(r.error, 6000);
    toast(on ? (r.confirmed ? `${path.split("/").pop()} is kept downloaded. macOS downloads anything missing by itself.`
      : "Done, but macOS hasn't confirmed it yet. In Finder, right-click it: Keep Downloaded should be ticked.")
      : `${path.split("/").pop()} is no longer kept downloaded.`, 6000);
    (after || route)();
  };
  if (keptBy && keptBy !== path) return h("span", { class: "status good", title: `Because ${pretty(keptBy)} is kept downloaded` },
    h("span", { class: "dot" }), "Kept downloaded");
  if (keptBy === path) return h("span", {}, h("span", { class: "status good" }, h("span", { class: "dot" }), "Kept downloaded"), " ",
    h("button", { class: "btn small", title: "macOS may remove its files from this Mac again when it needs space", onclick: (e) => { e.stopPropagation(); set(false); } }, "Stop keeping"));
  return h("button", { class: "btn small", title: "Like Finder's right-click → Keep Downloaded: macOS downloads all of it and never removes it from this Mac",
    onclick: (e) => { e.stopPropagation(); set(true); } }, "Keep Downloaded");
}
// Download now: fetch what's only in iCloud, once, in the background.
const downloads = {
  el: null, timer: null,
  async start(paths, label) {
    const r = await post("/api/icloud/download", { paths, label });
    if (!r.ok) return toast(r.error, 6000);
    if (!r.job.files) return toast(`Everything in ${label} is already on this Mac.`);
    this.poll();
  },
  async poll() {
    clearTimeout(this.timer);
    let d;
    try { d = await get("/api/icloud/jobs"); } catch (e) { return; }
    const active = d.jobs.filter((j) => !j.finished);
    const recent = d.jobs.filter((j) => j.finished && Date.now() / 1000 - j.finished < 8);
    if (!this.el) { this.el = h("div", { class: "player downloads", role: "status", "aria-live": "polite" }); document.body.append(this.el); }
    this.el.hidden = !active.length && !recent.length;
    this.el.replaceChildren(...[...active, ...recent].map((j) => h("div", { class: "player-head" },
      j.finished ? null : h("span", { class: "spinner", "aria-hidden": "true" }),
      h("span", { class: "player-title" }, j.finished
        ? `${j.cancelled ? "Stopped" : "Downloaded"} ${j.label}: ${j.done} of ${j.files} file${j.files === 1 ? "" : "s"}${j.errors.length ? `, ${j.errors.length} couldn't be downloaded (${j.errors[0]})` : ""}.`
        : `Downloading ${j.label}: ${j.done} of ${j.files} files (${fmt.size(j.done_bytes)} of ${fmt.size(j.bytes)})`),
      j.finished ? null : h("button", { class: "btn small", onclick: () => post("/api/icloud/cancel", { id: j.id }).then(() => this.poll()) }, "Stop"))));
    if (active.length || recent.length) this.timer = setTimeout(() => this.poll(), active.length ? 1500 : 8000);
  },
};
const downloadButton = (paths, label, bytes) => h("button", { class: "btn small", title: "Download it to this Mac now. macOS may remove it again later unless it's kept downloaded.",
  onclick: (e) => { e.stopPropagation(); downloads.start(paths, label); } }, bytes ? `Download now (${fmt.size(bytes)})` : "Download now");
function cloudChip(p) {
  const c = p.cloud_only;
  if (!c) return null;
  return h("span", { class: "chip", title: `${c.files} file${c.files === 1 ? "" : "s"} (${fmt.size(c.bytes)}) only in iCloud: Live downloads them when you open the set, `
    + "and offline they show as missing. " + KEEP_DOWNLOADED }, "☁︎ iCloud only");
}
function icloudNotice(ic) {
  if (!ic || !ic.projects) return null;
  const imp = (ic.important || []).map((n) => n.replace(/ Project$/, ""));
  const n = ic.projects;
  return h("div", { class: "note card", style: { marginBottom: "14px" } },
    ic.optimise ? [h("b", {}, "Optimise Mac Storage is on. "), "When this Mac wants space, macOS removes the copy on this Mac of iCloud files you haven't opened lately. "] : "",
    `${n} Ableton project${n === 1 ? " has" : "s have"} files that are only in iCloud right now`,
    imp.length ? `, including ${imp.length === 1 ? "the starred project" : "starred"} ${imp.slice(0, 4).join(", ")}${imp.length > 4 ? ` and ${imp.length - 4} more` : ""}` : "",
    ". Live downloads them when you open a set, and without internet they show up as missing. ",
    ic.optimise && ic.disk && ic.disk.low ? h("b", {}, `Only ${fmt.size(ic.disk.free)} is free, so macOS will remove more. `) : "",
    "To keep a project on your Mac for good, open it and click ", KEEP_DOWNLOADED, " ",
    h("button", { class: "btn small", onclick: () => { checklistFilter = "icloud"; route(); } }, "Show which projects"), " ",
    downloadButton(ic.project_paths || [], `${n} project${n === 1 ? "" : "s"}`));
}
// Overview: where the files only in iCloud are, with Keep Downloaded and Download now for each place.
function icloudCard(ic) {
  if (!ic || !ic.cloud_only_files) return null;
  const n = ic.projects || 0;
  const names = (ic.kept || []).map((k) => k.split("/").pop());
  return h("div", { class: "card", style: { marginBottom: "14px" } },
    h("h2", {}, "Only in iCloud"),
    h("p", {}, ic.optimise ? [h("b", {}, "Optimise Mac Storage is on: "), "when this Mac wants space, macOS removes the copy on this Mac of iCloud files you haven't opened lately. "] : "",
      h("b", {}, fmt.size(ic.cloud_only_bytes)), ` of your files (${fmt.count(ic.cloud_only_files)}) ${ic.cloud_only_files === 1 ? "isn't" : "aren't"} on this Mac right now. `,
      "Opening one downloads it first, and without internet it won't open.",
      ic.optimise && ic.disk && ic.disk.low ? h("b", {}, ` Only ${fmt.size(ic.disk.free)} is free, so macOS will remove more.`) : ""),
    names.length ? h("p", {}, h("span", { class: "status good" }, h("span", { class: "dot" }), "Kept downloaded: "), names.join(", "),
      h("span", { class: "muted" }, ". macOS never removes these.")) : null,
    h("table", {}, h("tbody", {}, (ic.areas || []).map((a) => h("tr", {},
      h("td", { class: "name" }, h("span", { class: "trunc", title: a.path }, pretty(a.path)),
        a.music ? h("span", { class: "chip", title: "Has audio or Ableton files" }, "audio") : null),
      h("td", { class: "num ink2" }, `${fmt.count(a.files)} file${a.files === 1 ? "" : "s"}`),
      h("td", { class: "num" }, fmt.size(a.bytes)),
      h("td", { style: { width: "1%", whiteSpace: "nowrap" } }, downloadButton([a.path], a.path.split("/").pop()), " ",
        keepButton(a.path, a.kept_by), " ", h("button", { class: "btn small", onclick: () => reveal(a.path) }, "Show")))))),
    n ? h("p", {}, `${n} Ableton project${n === 1 ? " has" : "s have"} files among them. `,
      h("button", { class: "btn small", onclick: () => { checklistFilter = "icloud"; openTab("projects"); } }, "Show which projects")) : null,
    h("p", { class: "muted" }, "Keep Downloaded is the same as Finder's right-click → Keep Downloaded: macOS downloads the folder and never removes it. ",
      "Download now fetches the files once; macOS may remove them again later. As of the last scan."));
}

function cloudDetail(p) {
  const c = p.cloud_only;
  if (!c) return inICloud(p.path) || p.kept_by ? h("div", {}, "On this Mac: ", keepButton(p.path, p.kept_by),
    p.kept_by ? null : h("span", { class: "muted" }, " Optimise Mac Storage may remove its files from this Mac when space runs low.")) : null;
  return h("div", { class: "card note" }, h("b", {}, `${c.files} file${c.files === 1 ? "" : "s"} in this project (${fmt.size(c.bytes)}) ${c.files === 1 ? "is" : "are"} only in iCloud`),
    c.sets ? `, including ${c.sets} set${c.sets === 1 ? "" : "s"}` : "", ". ",
    "Live downloads them when you open the set, which takes a while, and without internet they show up as missing. ",
    h("div", { class: "toolbar", style: { marginTop: "6px" } }, downloadButton([p.path], projName(p), c.bytes), keepButton(p.path, p.kept_by),
      h("span", { class: "muted" }, "Keep Downloaded keeps it on this Mac for good.")));
}

function projectDetail(p) {
  return h("div", { class: "stack" }, cloudDetail(p), organisingDetail(p),
    h("div", { class: "kv" },
      h("span", { class: "muted" }, "Path"), h("span", {}, pretty(p.path), " ", h("button", { class: "btn small", onclick: () => reveal(p.path) }, "Show")),
      h("span", { class: "muted" }, "Files"), h("span", {}, `${fmt.count(p.files)} · ${fmt.size(p.alloc)} on this Mac (${fmt.size(p.size)} total)`),
      h("span", { class: "muted" }, "Backups"), h("span", {}, `${p.backup_sets} auto-saved versions, ${fmt.size(p.backup_bytes)}`),
      p.possible_copies.length ? [h("span", { class: "muted" }, "Same name"), h("span", {}, p.possible_copies.map(pretty).join(" · "))] : null),
    p.sets.map((s) => h("div", {},
      h("b", {}, s.path.split("/").pop()), h("span", { class: "ink2" },
        s.error ? ` — ${s.error}` : ` — ${s.refs} files: ${s.in_project} in project, ${s.packs} from Packs, ${s.external} elsewhere, ${s.missing} missing`),
      (s.examples.external || []).length ? h("div", { class: "path" }, "Elsewhere: ", s.examples.external.map(pretty).join(" · ")) : null,
      missingList(s))));
}

// Apps that remember where files are: their files are kept where they are.
function appsCard() {
  const box = h("div", { class: "card", style: { marginBottom: "14px" } }, h("p", { class: "muted" }, "Checking rekordbox and Final Cut…"));
  get("/api/links").then((st) => {
    const rb = st.rekordbox || {};
    const pathIn = h("input", { type: "text", id: "rb-xml", value: rb.path ? pretty(rb.path) : "", placeholder: "~/Documents/rekordbox.xml",
      style: { flex: "1", minWidth: "240px" }, "aria-label": "rekordbox collection file" });
    const save = async (value) => {
      const r = await post("/api/links", { rekordbox_xml: value.replace(/^iCloud Drive/, HOME + ICLOUD_REL) });
      if (!r.ok) return toast(r.error);
      toast(value ? `rekordbox: ${r.rekordbox.tracks} tracks will stay where they are.` : "rekordbox collection removed.");
      route();
    };
    const fc = st.final_cut || {};
    box.replaceChildren(h("h2", {}, "Apps that keep track of files"),
      h("p", { class: "ink2" }, "rekordbox and Final Cut remember exactly where your files are. Mac Cleaner never moves or trashes the files they use, the same way it protects files your Live sets use."),
      h("h3", { style: { margin: "10px 0 4px" } }, "rekordbox"),
      rb.set && !rb.error ? h("p", {}, `${fmt.count(rb.tracks)} tracks protected, from a collection exported ${Math.floor(rb.exported_days)} days ago.`,
        rb.stale ? h("span", { class: "status warning" }, h("span", { class: "dot" }), " Export it again so new tracks are included") : null) : null,
      rb.error ? h("div", { class: "warn" }, rb.error) : null,
      !rb.set ? h("p", { class: "ink2" }, "In rekordbox choose ", h("b", {}, "File → Export Collection in xml format"),
        ", save it somewhere like Documents, then enter that file here. Export it again now and then so new tracks are included.") : null,
      h("div", { class: "toolbar" }, pathIn, h("button", { class: "btn primary", onclick: () => save(pathIn.value.trim()) }, "Use this file"),
        rb.set ? h("button", { class: "btn", onclick: () => save("") }, "Remove") : null),
      h("h3", { style: { margin: "12px 0 4px" } }, "Final Cut Pro"),
      h("p", {}, fc.links ? `${fmt.count(fc.links)} files linked from ${fc.libraries} librar${fc.libraries === 1 ? "y" : "ies"} (${fc.library_names.join(", ")}) are protected.`
        : "No Final Cut library links to files outside itself (or there was no scan yet)."));
  }).catch((e) => box.replaceChildren(h("div", { class: "warn" }, e.message)));
  return box;
}

// ------------------------------------------------------------------- rules
VIEWS.rules = async (root) => {
  const data = await get("/api/config");
  const cfg = data.config;
  const what = (w, r) => {
    if (r && r.describe) return r.describe;
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
  const before = JSON.parse(JSON.stringify(cfg));
  const save = async (next, undoable = true) => {
    const r = await post("/api/config", { config: next });
    if (!r.ok) return toast(r.error);
    route();
    if (undoable) toastAction("Saved. Catch-alls uses the new rules straight away.", "Undo", () => save(before, false));
    else toast("Change undone.");
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
    const then = r.action === "move" ? ["move them to ", h("b", {}, pretty(r.dest.replace("{ableton}", data.ableton_path).replace("{cloud}", data.cloud_path).replace("{year}", "‹year›").replace("{month}", "‹month›")))]
      : r.action === "trash" ? ["suggest the Trash ", riskPill(r.risk || "review")] : ["leave them"];
    return h("tr", { class: r.enabled === false ? "off" : "" },
      h("td", { class: "check" }, on),
      h("td", {}, h("div", {}, h("b", {}, r.name || `Rule ${i + 1}`)),
        h("div", { class: "ink2" }, "When there are ", what(w, r),
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
        "Anything an Ableton set or preset uses is always kept where it is, whatever the rules say.")),
    appsCard(),
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
  const { history, batches, interrupted } = await get("/api/history");
  const byBatch = new Map(batches.map((b) => [b.id, b]));
  const undoOne = async (e) => {
    const r = await post("/api/undo", { id: e.id });
    if (r.ok) { toast("Undone."); route(); } else toast(r.error);
  };
  const undoBatch = async (b) => {
    const ok = await modal(`Undo “${b.label}”?`, h("p", {}, `Puts back the ${b.done - b.undone} change${b.done - b.undone === 1 ? "" : "s"} in this batch that aren't undone yet, newest first.`),
      [{ label: "Cancel", value: false }, { label: "Undo all", value: true, cls: "primary" }]);
    if (!ok) return;
    const r = await post("/api/undo-batch", { id: b.id });
    if (!r.ok) return toast(r.error);
    if (r.failed.length) {
      await modal("Some couldn't be put back", h("div", {}, h("p", {}, `${r.undone} put back. These weren't:`),
        h("ul", {}, r.failed.map((f) => h("li", {}, `${short(f.path)}: ${f.error}`)))));
    } else toast(`Put back ${r.undone} item${r.undone === 1 ? "" : "s"}.`);
    route();
  };
  const resume = async (b) => {
    const r = await post("/api/resume-batch", { id: b.id });
    if (!r.ok) return toast(r.error);
    if (r.verify && r.verify.length) await verifyWarning(r.verify);
    const bad = r.results.filter((x) => !x.ok);
    toast(bad.length ? `${r.results.length - bad.length} done, ${bad.length} skipped.` : `Finished: ${r.results.length} more done.`);
    route();
  };
  const banners = interrupted.map((b) => h("div", { class: "warn", style: { marginBottom: "10px" } },
    h("b", {}, `“${b.label}” stopped after ${b.done} of ${b.planned}`), " (Mac Cleaner or the Mac stopped while it ran). ",
    h("button", { class: "btn small", onclick: () => resume(b) }, "Finish it"), " ",
    h("button", { class: "btn small", onclick: () => undoBatch(b) }, `Put back the ${b.done - b.undone} done`)));
  const rows = [];
  const shown = new Set();
  const entryRow = (e, inBatch) => h("tr", {},
    h("td", { class: "ink2 num" }, inBatch ? "" : e.ts),
    h("td", {}, e.op === "trash" ? "Trashed" : "Moved", e.note ? h("div", { class: "muted" }, e.note) : null),
    h("td", { class: "name" }, h("span", { class: "trunc", title: e.src }, pretty(e.src))),
    h("td", { class: "name" }, h("span", { class: "trunc", title: e.dst }, pretty(e.dst))),
    h("td", {}, e.undone ? h("span", { class: "muted" }, "undone") : h("button", { class: "btn small", onclick: () => undoOne(e) }, "Undo")));
  for (const e of history) {
    const b = e.batch && byBatch.get(e.batch);
    if (!b || b.done <= 1) { rows.push(entryRow(e, false)); continue; }
    if (shown.has(b.id)) continue;
    shown.add(b.id);
    const members = history.filter((x) => x.batch === b.id);
    const left = members.filter((x) => !x.undone).length;
    const detail = members.map((x) => { const r = entryRow(x, true); r.hidden = true; return r; });
    const toggle = h("button", { class: "btn small", onclick: () => {
      const open = detail[0].hidden; detail.forEach((r) => (r.hidden = !open)); toggle.textContent = open ? "Hide" : `Show ${members.length}`;
    } }, `Show ${members.length}`);
    rows.push(h("tr", { class: "has-sets" },
      h("td", { class: "ink2 num" }, b.ts),
      h("td", { colspan: 3 }, h("b", {}, b.label), " ", h("span", { class: "ink2" },
        `${members.length} change${members.length === 1 ? "" : "s"}${b.finished ? "" : ` of ${b.planned} (stopped early)`}${left < members.length ? ` · ${members.length - left} undone` : ""}`), " ", toggle),
      h("td", {}, left ? h("button", { class: "btn small", onclick: () => undoBatch(b) }, "Undo all") : h("span", { class: "muted" }, "undone"))), ...detail);
  }
  root.replaceChildren(
    h("div", { class: "toolbar" }, h("div", {}, h("h1", {}, "History"), h("div", { class: "ink2" }, "Every move and trash, newest first. Changes made together are one batch you can undo as one."))),
    ...banners,
    history.length ? h("div", { class: "card" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "When"), h("th", {}, "What"), h("th", {}, "From"), h("th", {}, "To"), h("th", {}))),
      h("tbody", {}, rows)))
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
