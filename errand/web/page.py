"""The page: HTML, CSS and a little JS, inline -- one file, no build, nothing fetched elsewhere.

Left, the list ( machines, what runs, what waits, VMs and guests, history ); right, the row chosen:
what it is, its files ( each opens whole ), the end of its output, and a stop button. Both are asked
again every 2 s; what is folded or opened stays in the browser ( localStorage ), the row chosen in
the URL ( #key ).
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>errand</title>
<style>
:root { --bg: #fbfbfa; --fg: #1d1d1b; --dim: #74746f; --line: #e3e2de; --sel: #e8eefc; --run: #1f7a3e;
        --wait: #a66200; --bad: #b42318; --hit: #2a55c9; --pre: #f3f2ef; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #17181a; --fg: #e6e5e1; --dim: #8d8c87; --line: #2c2d30; --sel: #1f2a44; --run: #5cc27f;
          --wait: #e6a23c; --bad: #f2776b; --hit: #84a7ff; --pre: #1e1f22; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 13px/1.45 ui-monospace, SFMono-Regular, Menlo, monospace; }
header { display: flex; gap: 12px; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--line); }
header b { font-size: 14px; }
header input { flex: 1; max-width: 360px; font: inherit; padding: 3px 8px; background: transparent; color: var(--fg);
               border: 1px solid var(--line); border-radius: 4px; }
#said { color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
main { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr); height: calc(100vh - 41px); }
#list, #detail { overflow: auto; padding: 6px 0; }
#list { border-right: 1px solid var(--line); }
.row { display: flex; gap: 10px; padding: 1px 16px; cursor: pointer; white-space: nowrap; }
.row:hover { background: var(--pre); }
.row.sel { background: var(--sel); }
.row .label { overflow: hidden; text-overflow: ellipsis; }
.row .detail { margin-left: auto; color: var(--dim); overflow: hidden; text-overflow: ellipsis; }
.row.machine .label, .row.broken .label { font-weight: 600; }
.row.broken .detail { color: var(--bad); }
.row.note .label, .row.more .label { color: var(--dim); }
.mark { display: inline-block; width: 5ch; }
.m-run { color: var(--run); } .m-wait { color: var(--wait); } .m-orph, .m-lost, .m-FAIL { color: var(--bad); }
.m-ok { color: var(--run); } .m-skip { color: var(--dim); }
#detail { padding: 10px 16px; }
#detail h2 { font-size: 14px; margin: 0 0 8px; }
#detail table { border-collapse: collapse; }
#detail td { padding: 1px 12px 1px 0; vertical-align: top; word-break: break-all; }
#detail td:first-child { color: var(--dim); white-space: nowrap; }
#detail h3 { font-size: 12px; color: var(--dim); margin: 14px 0 4px; font-weight: normal; }
#detail a { color: var(--hit); text-decoration: none; }
#detail a:hover { text-decoration: underline; }
.files td:nth-child(2), .files td:nth-child(3) { color: var(--dim); text-align: right; }
pre { background: var(--pre); padding: 8px; margin: 0; max-height: 60vh; overflow: auto; white-space: pre-wrap; word-break: break-all; }
button { font: inherit; padding: 2px 10px; border-radius: 4px; border: 1px solid var(--bad); color: var(--bad);
         background: transparent; cursor: pointer; margin-top: 10px; }
.err { color: var(--bad); }
.dim { color: var(--dim); }
@media (max-width: 760px) { main { grid-template-columns: 1fr; height: auto; } #list { border-right: 0; max-height: 50vh; } }
</style>
</head>
<body>
<header><b>errand</b><input id="q" placeholder="/ filter: machine, project, what, env, state" autocomplete="off"><span id="said"></span></header>
<main><div id="list"></div><div id="detail"><span class="dim">choose a row</span></div></main>
<script>
"use strict";
const EVERY = 2000;
const $ = id => document.getElementById(id);
function load(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
function keep(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
let folded = new Set(load("folded", [])), opened = new Set(load("opened", [])), shown = 50;
let chosen = decodeURIComponent(location.hash.slice(1)) || null, rows = [];

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"})[c]); }
function ago(s) { s = Math.max(0, Math.floor(s)); return s < 90 ? s + " s" : s < 5400 ? Math.floor(s / 60) + " min"
  : s < 172800 ? Math.floor(s / 3600) + " h" : Math.floor(s / 86400) + " d"; }
function size(n) { for (const u of ["B", "kB", "MB", "GB"]) { if (n < 1000 || u == "GB") return u == "B" ? n + " B" : n.toFixed(1) + " " + u; n /= 1000; } }

async function ask(path, opts) {
  const r = await fetch(path, opts);
  const got = await r.json().catch(() => ({error: r.status + " " + r.statusText}));
  if (!r.ok && !got.error) got.error = r.status + " " + r.statusText;
  return got;
}

async function state() {
  const q = new URLSearchParams({q: $("q").value, folded: [...folded].join(","), opened: [...opened].join(","), shown});
  try {
    const got = await ask("/state?" + q);
    if (got.error) throw new Error(got.error);
    rows = got.rows;
    draw();
    $("said").textContent = "";
  } catch (e) { $("said").innerHTML = '<span class="err">' + esc(e.message || e) + "</span>"; }
}

function draw() {
  $("list").innerHTML = rows.map(r => {
    const fold = r.open === null ? "" : r.open ? "▾ " : "▸ ";
    const mark = r.mark ? '<span class="mark m-' + esc(r.mark) + '">' + esc(r.mark) + "</span>" : "";
    return '<div class="row ' + esc(r.kind) + (r.key === chosen ? " sel" : "") + '" data-key="' + esc(r.key) + '" style="padding-left:' +
      (16 + 20 * r.depth) + 'px"><span class="label">' + fold + mark + esc(r.label) + '</span><span class="detail">' + esc(r.detail) + "</span></div>";
  }).join("") || '<div class="row note"><span class="label">asking…</span></div>';
}

$("list").addEventListener("click", ev => {
  const el = ev.target.closest(".row"); if (!el) return;
  const r = rows.find(r => r.key === el.dataset.key); if (!r) return;
  if (r.kind === "machine" || r.kind === "broken") toggle(folded, "folded", r.machine);
  else if (r.kind === "group") toggle(opened, "opened", r.machine);
  else if (r.kind === "more") { shown += 50; state(); }
  if (["proc", "run", "vm", "machine", "broken"].includes(r.kind)) choose(r.key);
});
function toggle(set, name, m) { set.has(m) ? set.delete(m) : set.add(m); keep(name, [...set]); state(); }
function choose(key) { chosen = key; history.replaceState(null, "", "#" + encodeURIComponent(key)); draw(); detail(true); }

let detailing = false;
async function detail(fresh) {
  if (!chosen || (detailing && !fresh)) return;
  detailing = true;
  const key = chosen;
  try {
    const d = await ask("/detail?" + new URLSearchParams({key}));
    if (key === chosen) show(d);
  } finally { detailing = false; }
}

function show(d) {
  const pane = $("detail");
  if (d.error && !d.facts) { pane.innerHTML = '<span class="err">' + esc(d.error) + "</span>"; return; }
  const pre = pane.querySelector("pre");
  const bottom = !pre || pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
  let h = "<h2>" + esc(d.title) + "</h2><table>" + d.facts.map(([k, v]) => "<tr><td>" + esc(k) + "</td><td>" + esc(v) + "</td></tr>").join("") + "</table>";
  if (d.stop === true) h += '<button id="stop">stop</button>';
  else if (typeof d.stop === "string") h += '<p class="dim">' + esc(d.stop) + "</p>";
  if (d.error) h += '<p class="err">cannot read: ' + esc(d.error) + "</p>";
  const link = p => "/file?" + new URLSearchParams({machine: d.machine, path: p});
  if (d.files && d.files.length) h += "<h3>files</h3><table class=\"files\">" + d.files.map(f =>
    '<tr><td><a target="_blank" href="' + esc(link(f.path)) + '">' + esc(f.name) + "</a></td><td>" + size(f.size) + "</td><td>" + ago(f.age) + "</td></tr>").join("") + "</table>";
  if (d.out !== undefined) h += "<h3>output " + esc(d.source || "") + (d.path ? ' · <a target="_blank" href="' + esc(link(d.path)) + '">whole</a>' : "") +
    "</h3><pre>" + esc(d.out || "( nothing yet )") + "</pre>";
  const scroll = pre ? pre.scrollTop : 0;
  pane.innerHTML = h;
  const now = pane.querySelector("pre");
  if (now) now.scrollTop = bottom ? now.scrollHeight : scroll;
  const b = $("stop");
  if (b) b.onclick = stop;
}

async function stop() {
  const r = rows.find(r => r.key === chosen);
  if (!confirm("stop " + (r ? r.label.replace(/\s+/g, " ") : "this") + " ?  ( cancel line, then INT, TERM, KILL )")) return;
  const got = await ask("/stop", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({key: chosen})});
  $("said").innerHTML = got.error ? '<span class="err">' + esc(got.error) + "</span>" : esc(got.said);
  state();
}

$("q").addEventListener("input", () => state());
document.addEventListener("keydown", ev => {
  if (ev.key === "/" && document.activeElement !== $("q")) { ev.preventDefault(); $("q").focus(); }
  else if (ev.key === "Escape") { $("q").value = ""; $("q").blur(); state(); }
});
function tick() { state(); detail(false); }
tick();
setInterval(tick, EVERY);
</script>
</body>
</html>
"""
