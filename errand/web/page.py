"""The page: HTML, CSS and a little JS, inline -- one file, no build, nothing fetched elsewhere.

What `errand tui` shows, with the same keys, and buttons beside them. Three tabs: the runs ( running,
waiting, done by day, every machine in one list ), the machines ( their gauges, VMs, guests' work ) and the
library caches they hold ( ADR 0022: per cache, a row per place, its entries merged across places ).
Right, the row chosen: its facts, its step, its views and outputs ( the console, then its files ); the
output chosen is shown below them -- text, an image, a page --, and opens whole in a tab of its own.
What is folded stays in the browser ( localStorage ), the row chosen in the URL ( #key ).

`LOGIN`: what a browser without the cookie gets -- a field for the token ( `errand web token` ).
"""

LOGIN = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>errand</title>
<style>
:root { --bg: #fbfbfa; --fg: #1d1d1b; --dim: #74746f; --line: #d9d8d3; --acc: #0f7c8a; --bad: #b42318; }
@media (prefers-color-scheme: dark) { :root { --bg: #151618; --fg: #e6e5e1; --dim: #8d8c87; --line: #33343a; --acc: #5fc4d0; --bad: #f2776b; } }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--fg);
       font: 14px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
form { width: min(520px, calc(100vw - 32px)); }
h1 { font-size: 18px; color: var(--acc); margin: 0 0 12px; }
p { color: var(--dim); margin: 6px 0; }
input { width: 100%; font: inherit; padding: 8px 10px; margin: 12px 0; background: transparent; color: var(--fg);
        border: 1px solid var(--line); border-radius: 6px; }
button { font: inherit; padding: 6px 16px; border-radius: 6px; border: 1px solid var(--acc); background: var(--acc); color: var(--bg); cursor: pointer; }
code { color: var(--fg); }
.bad { color: var(--bad); }
</style></head>
<body><form method="post" action="/login">
<h1>errand</h1>
<p>This page shows your runs: it opens to the token of your errand only.</p>
<p><code>errand web</code> opens it directly; otherwise, paste what <code>errand web token</code> prints.</p>
<p class="bad">{said}</p>
<input name="token" type="password" autocomplete="off" autofocus placeholder="token">
<button>open</button>
</form></body></html>
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>errand</title>
<style>
:root { --bg: #fbfbfa; --fg: #1d1d1b; --dim: #7a7a74; --faint: #b5b4ae; --line: #e3e2de; --sel: #e4eef0; --hover: #f1f0ec;
        --pre: #f4f3f0; --acc: #0f7c8a; --place: #8a3f8f; --ok: #1f7a3e; --wait: #a66200; --bad: #b42318;
        --g1: #2f9e55; --g2: #c98a00; --g3: #c7362b; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #151618; --fg: #e6e5e1; --dim: #8d8c87; --faint: #4c4d52; --line: #2a2b30; --sel: #1d3236; --hover: #1d1e22;
          --pre: #1b1c1f; --acc: #5fc4d0; --place: #d38bd8; --ok: #5cc27f; --wait: #e6a23c; --bad: #f2776b;
          --g1: #4fbf73; --g2: #e3b341; --g3: #f0685c; }
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
       display: flex; flex-direction: column; }
button { font: inherit; color: inherit; background: transparent; border: 1px solid var(--line); border-radius: 5px;
         padding: 1px 9px; cursor: pointer; white-space: nowrap; }
button:hover { border-color: var(--dim); }
button.danger { color: var(--bad); border-color: color-mix(in srgb, var(--bad) 45%, transparent); }
button.primary { background: var(--acc); border-color: var(--acc); color: var(--bg); }
button kbd { color: var(--dim); font: inherit; margin-left: 6px; }
button.primary kbd { color: inherit; opacity: .7; }

header { display: flex; gap: 10px; align-items: center; padding: 6px 14px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
header .name { color: var(--acc); font-weight: 700; font-size: 14px; margin-right: 6px; }
.tab { border: 0; border-radius: 5px; padding: 2px 10px; color: var(--dim); }
.tab.on { background: var(--acc); color: var(--bg); font-weight: 600; }
.tab kbd { font: inherit; opacity: .6; margin-right: 6px; }
#q { font: inherit; padding: 2px 8px; width: 260px; max-width: 40vw; background: transparent; color: var(--fg);
     border: 1px solid var(--line); border-radius: 5px; }
#counts { margin-left: auto; display: flex; gap: 16px; color: var(--dim); white-space: nowrap; }
#counts .on.run { color: var(--ok); font-weight: 600; } #counts .on.wait { color: var(--wait); font-weight: 600; }

main { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(200px, var(--left, 55%)) 6px minmax(240px, 1fr); }
.pane { overflow: auto; min-height: 0; outline: none; }
#list { padding: 4px 0; }
#right { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
#detail { flex: 1 1 auto; }
#view { flex: none; height: var(--bottom, 40%); padding: 6px 16px 16px; display: none; }
#right.viewing #view, #right.viewing #hsplit { display: block; }
.split { background: var(--line); position: relative; z-index: 2; }
.split::after { content: ""; position: absolute; inset: -3px; }          /* easier to catch */
.split.v { cursor: col-resize; width: 1px; justify-self: center; } .split.v:hover, .split.v.drag { width: 3px; background: var(--acc); }
.split.h { cursor: row-resize; height: 1px; flex: none; display: none; } .split.h:hover, .split.h.drag { height: 3px; background: var(--acc); }
body.dragging { user-select: none; }
.pane.focus { box-shadow: inset 0 2px 0 var(--acc); }

.row { display: flex; align-items: center; gap: 8px; padding: 0 14px; cursor: pointer; white-space: pre; min-height: 21px; }
.row:hover { background: var(--hover); }
.row.sel { background: var(--sel); }
.pane:not(.focus) .row.sel { background: color-mix(in srgb, var(--sel) 55%, transparent); }
.row .fold { width: 1.2ch; color: var(--dim); flex: none; }
.row .sign { width: 1.4ch; text-align: center; flex: none; }
.row .label { overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto; }
.row .label .where { color: var(--dim); }
.row .right { margin-left: auto; color: var(--dim); overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto;
              max-width: 55%; padding-left: 12px; }
.row.proc .right, .row.run .right { flex: none; }        /* the time, the step: kept, the name gives way */
.row.machine .label, .row.broken .label { font-weight: 600; }
.row.dormant { color: var(--faint); }
.row.day .label, .row.group .label, .row.centries .label { color: var(--dim); font-weight: 600; }
.row.cache .label { font-weight: 600; }
.row.note .label, .row.more .label { color: var(--dim); }
.row.broken .right { color: var(--bad); }
.hit { color: var(--acc); font-weight: 700; }
.m-run, .m-ok { color: var(--ok); } .m-wait { color: var(--wait); } .m-FAIL, .m-orph, .m-lost { color: var(--bad); } .m-dead { color: var(--wait); } .m-skip { color: var(--dim); }
.row.machine .label, .row.broken .label, .row.dormant .label { flex: none; width: 24ch; }   /* the gauges in one column */
.meters { display: flex; gap: 14px; color: var(--dim); flex: none; }
.meter { display: flex; align-items: center; gap: 5px; width: 15ch; }
.meter > span:first-child { width: 4ch; }
.bar { width: 46px; height: 7px; border-radius: 4px; background: var(--line); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--g1); }
.bar i.l2 { background: var(--g2); } .bar i.l3 { background: var(--g3); }
.meter b { font-weight: normal; width: 4ch; text-align: right; color: var(--fg); }

#detail { padding: 10px 16px 24px; }
#detail h2 { font-size: 14px; margin: 0 0 6px; word-break: break-all; }
.tools { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 10px; }
.facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); column-gap: 14px; }
.facts .k { color: var(--dim); }
.facts .v { word-break: break-all; }
.more { color: var(--dim); cursor: pointer; margin-top: 2px; user-select: none; }
.head { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; min-width: 0; }
.head h2 { margin: 0 !important; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { flex: none; padding: 0 7px; border-radius: 5px; font-weight: 600; background: var(--hover); color: var(--dim); }
.badge.ok { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.badge.bad { background: color-mix(in srgb, var(--bad) 16%, transparent); color: var(--bad); }
.badge.run { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.badge.wait { background: color-mix(in srgb, var(--wait) 16%, transparent); color: var(--wait); }
.chips { display: grid; grid-template-columns: repeat(auto-fill, minmax(20ch, 1fr)); gap: 2px 14px; margin: 2px 0 8px; }
.chips .br { grid-column: 1 / -1; height: 0; }
.chip { display: flex; align-items: center; gap: 7px; min-width: 0; padding: 0 4px; margin: 0 -4px; border-radius: 4px; }
.chip > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip.click { cursor: pointer; color: var(--acc); }
.chip.click:hover { background: var(--hover); }
.chip.shown { background: var(--sel); }
svg.i { flex: none; width: 14px; height: 14px; color: var(--dim); fill: none; stroke: currentColor; stroke-width: 1.3;
        stroke-linecap: round; stroke-linejoin: round; }
.out svg.i { margin-right: 2px; }
.out .n { display: flex; align-items: center; gap: 7px; }
.out.empty { color: var(--faint); cursor: default; }
.out.empty .e { cursor: pointer; } .out.empty .e:hover { color: var(--fg); }
.out.empty .e.sel { background: var(--sel); color: var(--fg); border-radius: 3px; }
.more:hover { color: var(--fg); }
.path { color: var(--acc); cursor: pointer; border-radius: 3px; }
.path:hover { text-decoration: underline; }
.path.shown { background: var(--sel); }
.vhead { display: flex; gap: 6px; align-items: center; position: sticky; top: -6px; background: var(--bg); padding: 4px 0 6px; flex-wrap: wrap; }
.vhead .where { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; text-align: left; color: var(--dim); }
.vhead .where b { color: var(--fg); font-weight: 600; }
.vhead button, .vhead a.btn { padding: 0 7px; }
a.btn { font: inherit; color: inherit; border: 1px solid var(--line); border-radius: 5px; padding: 1px 9px; text-decoration: none; white-space: nowrap; }
a.btn:hover { border-color: var(--dim); }
.tk-c { color: var(--dim); font-style: italic; } .tk-s { color: var(--ok); } .tk-k { color: var(--place); font-weight: 600; }
.tk-n { color: var(--wait); } .tk-f { color: var(--acc); } .tk-d { color: var(--place); } .tk-key { color: var(--acc); }
.code { white-space: pre; overflow-x: auto; border-left: 2px solid var(--line); padding: 2px 0 2px 10px; margin: 2px 0 2px 6px;
        background: var(--pre); border-radius: 0 5px 5px 0; }
body.job #list, body.job .tab, body.job #q, body.job #hsplit { display: none !important; }
body.job #view { height: 100% !important; }
body.only header, body.only footer, body.only #detail, body.only .split { display: none !important; }
body.only main { grid-template-columns: 1fr; }
body.only #view { padding: 4px 16px 16px; }
body.only .vhead a.btn[target], body.only .vhead [data-v="close"] { display: none; }    /* it is the tab, there is nothing behind */
.ent { display: grid; grid-template-columns: minmax(0, 1fr) 10ch 8ch; gap: 10px; padding: 0 6px; border-radius: 4px; cursor: pointer; }
.ent:hover { background: var(--hover); }
.ent .s, .ent .a { color: var(--dim); text-align: right; }
.ent.dir .n { color: var(--acc); }
.menu { position: fixed; z-index: 9; background: var(--bg); border: 1px solid var(--line); border-radius: 7px; padding: 4px;
        box-shadow: 0 8px 28px rgba(0,0,0,.2); min-width: 220px; display: none; }
.menu.on { display: block; }
.menu div { padding: 3px 10px; border-radius: 4px; cursor: pointer; display: flex; gap: 16px; }
.menu div:hover { background: var(--sel); }
.menu div.off { color: var(--faint); pointer-events: none; }
.menu kbd { margin-left: auto; color: var(--dim); font: inherit; }
h3 { font-size: 12px; color: var(--dim); font-weight: 600; margin: 14px 0 4px; text-transform: lowercase; letter-spacing: .02em; }
.out { display: flex; gap: 10px; padding: 1px 8px; margin: 0 -8px; border-radius: 5px; cursor: pointer; align-items: center; }
.out:hover { background: var(--hover); }
.out.sel { background: var(--sel); }
.out .n { overflow: hidden; text-overflow: ellipsis; }
.out .d { margin-left: auto; color: var(--dim); white-space: nowrap; }
.out .go { visibility: hidden; display: flex; gap: 4px; }
.out:hover .go, .out.sel .go { visibility: visible; }
.out .go a { color: var(--acc); text-decoration: none; padding: 0 4px; }
.console { margin-top: 12px; }
.chead { color: var(--acc); font-weight: 700; }
.lines { border-left: 2px solid var(--line); margin: 2px 0 2px 6px; padding: 2px 0 2px 10px; white-space: pre-wrap;
         word-break: break-all; background: var(--pre); border-radius: 0 5px 5px 0; }
.lines.err { border-left-color: var(--wait); }
.cend { margin-left: 6px; } .cend .st { font-weight: 700; }
.st.PASS { color: var(--ok); } .st.FAIL, .st.ERROR, .st.TIMEOUT { color: var(--bad); } .st.SKIP { color: var(--wait); }
.note { color: var(--dim); } .broken { color: var(--bad); }
.peek img { max-width: 100%; border: 1px solid var(--line); border-radius: 5px; background: #fff; }
.peek iframe { width: 100%; height: 100%; min-height: 200px; border: 1px solid var(--line); border-radius: 5px; background: #fff; }
.a1 { font-weight: 700; } .a2 { opacity: .65; } .a3 { font-style: italic; } .a4 { text-decoration: underline; }
.c0 { color: #555; } .c1 { color: var(--bad); } .c2 { color: var(--ok); } .c3 { color: var(--wait); } .c4 { color: #3b6fd8; }
.c5 { color: var(--place); } .c6 { color: var(--acc); } .c7 { color: var(--dim); }

footer { border-top: 1px solid var(--line); padding: 3px 14px; color: var(--dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
footer.said { color: var(--wait); }
footer kbd { font: inherit; color: var(--fg); }

.veil { position: fixed; inset: 0; background: color-mix(in srgb, var(--bg) 55%, transparent); display: none; place-items: center; z-index: 5; }
.veil.on { display: grid; }
.box { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; width: min(560px, calc(100vw - 32px));
       box-shadow: 0 12px 40px rgba(0,0,0,.18); }
.box.danger { border-color: var(--bad); }
.box h4 { margin: 0 0 10px; font-size: 14px; }
.box ul { margin: 0 0 14px; padding-left: 18px; color: var(--dim); }
.box input { width: 100%; font: inherit; padding: 6px 8px; margin: 0 0 14px; background: transparent; color: var(--fg);
             border: 1px solid var(--acc); border-radius: 5px; }
.box .keys { display: flex; gap: 8px; justify-content: flex-end; }
.help { display: grid; grid-template-columns: max-content 1fr; gap: 2px 16px; margin-bottom: 12px; }
.help kbd { font: inherit; color: var(--acc); }
@media (max-width: 800px) { main { grid-template-columns: 1fr; } .split.v { display: none; } #list { border-bottom: 1px solid var(--line); max-height: 45vh; } #counts { margin-left: 0; } }
</style>
</head>
<body>
<header>
  <span class="name">errand</span>
  <button class="tab" data-tab="runs"><kbd>1</kbd>runs</button>
  <button class="tab" data-tab="machines"><kbd>2</kbd>machines</button>
  <button class="tab" data-tab="caches"><kbd>3</kbd>caches</button>
  <input id="q" placeholder="/ filter: machine, project, what, env, state" autocomplete="off" spellcheck="false">
  <button id="refresh" title="ask every machine again now">↻<kbd>R</kbd></button>
  <button id="helpb" title="keys">?</button>
  <span id="counts"></span>
</header>
<main id="main">
  <div id="list" class="pane focus" tabindex="0"></div>
  <div class="split v" id="vsplit" title="drag"></div>
  <div id="right" class="viewing">
    <div id="detail" class="pane" tabindex="0"><span class="note">choose a row</span></div>
    <div class="split h" id="hsplit" title="drag"></div>
    <div id="view" class="pane" tabindex="0"><div id="vh"></div><div id="vb" style="height:calc(100% - 34px)"></div></div>
  </div>
</main>
<div class="menu" id="menu"></div>
<footer id="foot"></footer>
<div class="veil" id="veil"><div class="box" id="box"></div></div>
<script>
"use strict";
const EVERY = 2000;
const SIGNS = {run: "●", wait: "◌", ok: "✓", FAIL: "✗", skip: "–", lost: "?", orph: "?", dead: "✗"};
// what the detail says always; the rest is folded ( `more` )
const RARE = new Set(["pid", "agent", "id", "outputs", "reached", "host", "keeper", "qemu", "port", "image", "warm", "agents", "said"]);
const OPENED_IN_A_TAB = /\.(html?|svg|pdf|png|jpe?g|gif|webp|bmp)$/i;
const HINT = "<kbd>1</kbd> runs · <kbd>2</kbd> machines · <kbd>3</kbd> caches · <kbd>↑↓</kbd> choose · <kbd>→←</kbd> unfold, fold · <kbd>tab</kbd> detail · " +
             "click: show · double-click, <kbd>⌘</kbd>-click: open · right-click: more · <kbd>k</kbd> kill · <kbd>r</kbd> rename · <kbd>?</kbd> keys";
const KEYS = [
  ["↑ ↓  pgup pgdn", "move in the pane in front"], ["1  2  3", "the runs tab ( running, waiting, done ), the machines tab, the caches tab"],
  ["→  ←", "unfold, fold: a machine, a day · ← on a row inside: up to what holds it"],
  ["tab", "the other pane: the list, or the detail ( its outputs: the one chosen is shown below )"],
  ["click", "a row: its detail · a file, a folder: shown in the pane below"],
  ["double-click, ⌘-click", "open it: a page or an image in a tab, a text in an editor, a folder in the Finder"],
  ["right-click", "everything that can be done with it"],
  ["enter  o", "open the output chosen ( as a double-click )"], ["e", "the output chosen in an editor of this machine"],
  ["d", "the output chosen, downloaded"], ["esc", "back to the console · clear the filter"],
  ["k", "kill what is chosen, once confirmed: a process, a vm, or all errand runs on a machine"],
  ["f  a  r", "forget, watch or not, name the machine"], ["/", "filter: machine, project, command, state"], ["R", "ask every machine again now"],
  ["i  u", "caches: remove the dead entries, those unused for n days -- of a place, or of every place on a cache's row"],
  ["d  D", "caches: the entry chosen removed where it is dead or unused, or everywhere it is"],
  ["h", "caches: the machine of the place chosen holds its directory ( its agent purges it daily )"],
  ["n  v", "caches: the days after which an entry is unused ( 30 ) · every entry, or the dead and unused only"]];
const CACHE_ACTS = {dead: ["remove dead", "i"], unused: ["remove unused", "u"], flagged: ["remove where dead or unused", "d"], everywhere: ["remove everywhere", "D"]};

const $ = id => document.getElementById(id);
const MAC = /Mac|iPhone|iPad/.test(navigator.platform);
// a part of the page rebuilt only when what it shows changed: a frame is not reloaded, a click is not
// lost between its press and its release because the button was replaced under it
function put(el, html) { if (el._html === html) return false; el._html = html; el.innerHTML = html; return true; }
function load(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }
function keep(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[c]); }
function size(n) { for (const u of ["B", "kB", "MB", "GB"]) { if (n < 1000 || u == "GB") return u == "B" ? n + " B" : n.toFixed(1) + " " + u; n /= 1000; } }
function ago(s) { s = Math.max(0, Math.floor(s)); return s < 90 ? s + " s" : s < 5400 ? Math.floor(s / 60) + " min" : s < 172800 ? Math.floor(s / 3600) + " h" : Math.floor(s / 86400) + " d"; }

// `/job?key=…[&path=…]`: one run as a page of its own -- its detail and outputs left, the one chosen right
const JOB = location.pathname == "/job", JOBQ = new URLSearchParams(location.search);
const ONLY = JOB && JOBQ.has("only");                  // `&only=1`: the content alone, read again as it changes
let jobPath = JOB ? JOBQ.get("path") : null;
let cacheDays = load("cacheDays", 30), cacheAll = load("cacheAll", false);
let tab = load("tab", "runs"), folded = new Set(load("folded", [])), opened = new Set(load("opened", [])), shown = 50, query = "";
let rows = [], sel = decodeURIComponent(location.hash.slice(1)) || null, focus = "list", showMore = load("more", false);
let det = null, dsel = -1, said = "", saidAt = 0, modal = null, view = null;   // view: { key, path, dir, got }

async function ask(path, opts) {
  const r = await fetch(path, opts);
  if (r.status == 401) { location.reload(); throw new Error("signed out"); }
  const got = await r.json().catch(() => ({error: r.status + " " + r.statusText}));
  if (!r.ok || got.error) throw new Error(got.error || r.statusText);
  return got;
}
async function act(op, extra) {
  try {
    const got = await ask("/act", {method: "POST", headers: {"Content-Type": "application/json"},
                                   body: JSON.stringify({op, key: sel || "", ...extra})});
    if (got.confirm) return confirmBox(got.confirm, () => act(op, {...extra, sure: true}));
    if (got.prompt) return promptBox(got.prompt, label => act(op, {...extra, label}));
    say(got.said || "");
  } catch (e) { say(e.message); }
  refresh();
}
function say(s) { said = s; saidAt = Date.now(); foot(); }
function foot() {
  const f = $("foot"), live = said && Date.now() - saidAt < 8000;
  f.className = live ? "said" : ""; f.innerHTML = live ? esc(said) : HINT;
}

// ── the splitters ──────────────────────────────────────────────────────────
function drag(bar, move) {
  bar.addEventListener("pointerdown", e => {
    e.preventDefault(); bar.setPointerCapture(e.pointerId); bar.classList.add("drag"); document.body.classList.add("dragging");
    const up = () => { bar.classList.remove("drag"); document.body.classList.remove("dragging");
                       bar.removeEventListener("pointermove", mv); bar.removeEventListener("pointerup", up); };
    const mv = ev => move(ev);
    bar.addEventListener("pointermove", mv); bar.addEventListener("pointerup", up);
  });
}
const LEFT = JOB ? "jobleft" : "left";
function sizes() {
  document.documentElement.style.setProperty("--left", load(LEFT, JOB ? 34 : 55) + "%");
  document.documentElement.style.setProperty("--bottom", load("bottom", 40) + "%");
}
drag($("vsplit"), e => { const r = $("main").getBoundingClientRect();
  keep(LEFT, Math.max(15, Math.min(85, 100 * (e.clientX - r.left) / r.width))); sizes(); });
drag($("hsplit"), e => { const r = $("right").getBoundingClientRect();
  keep("bottom", Math.max(10, Math.min(90, 100 * (r.bottom - e.clientY) / r.height))); sizes(); });
sizes();

// ── the list ───────────────────────────────────────────────────────────────
function level(f) { return f >= .85 ? "l3" : f >= .6 ? "l2" : ""; }
function label(r) {
  if ((r.kind == "proc" || r.kind == "run") && tab == "runs") {          // its machine first, in grey
    const m = r.label.match(/^(\S+\s+)(.*)$/);
    if (m) return `<span class="where">${esc(m[1])}</span>${esc(m[2])}`;
  }
  if (r.hits && r.hits.length) {
    const hit = new Set(r.hits);
    return [...r.label].map((c, i) => hit.has(i) ? `<span class="hit">${esc(c)}</span>` : esc(c)).join("");
  }
  return esc(r.label);
}
function rowHtml(r) {
  const fold = r.open === null ? "" : r.open ? "▾" : "▸";
  const sign = SIGNS[r.mark] ? `<span class="sign m-${esc(r.mark)}">${SIGNS[r.mark]}</span>` : "";
  const meters = r.meters.length ? `<span class="meters">${r.meters.map(([n, f]) =>
      `<span class="meter"><span>${esc(n)}</span><span class="bar"><i class="${level(f)}" style="width:${Math.round(100 * f)}%"></i></span><b>${Math.round(100 * f)}%</b></span>`).join("")}</span>` : "";
  return `<div class="row ${esc(r.kind)}${r.key == sel ? " sel" : ""}" data-key="${esc(r.key)}" style="padding-left:${14 + 18 * r.depth}px">` +
         `<span class="fold">${fold}</span>${sign}<span class="label">${label(r)}</span>${meters}<span class="right">${esc(r.detail)}</span></div>`;
}
function drawList() {
  put($("list"), rows.map(rowHtml).join("") || `<div class="row note"><span class="label">nothing here</span></div>`);
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("on", b.dataset.tab == tab));
}
function drawCounts(c) {
  $("counts").innerHTML = `<span class="run ${c.running ? "on" : ""}">● ${c.running} running</span>` +
    `<span class="wait ${c.waiting ? "on" : ""}">◌ ${c.waiting} waiting</span>` +
    `<span>${c.machines} machines${c.off ? `, ${c.off} not watched` : ""}</span>`;
}
let stating = false;
async function state() {
  if (JOB) return detail();                             // one run: nothing to list
  if (stating) return; stating = true;
  try {
    const p = new URLSearchParams({tab, q: query, shown, folded: [...folded].join(","), opened: [...opened].join(","),
                                   days: cacheDays, all: cacheAll ? 1 : 0});
    const got = await ask("/state?" + p);
    rows = got.rows; drawCounts(got.counts);
    if (!rows.some(r => r.key == sel)) sel = (rows.find(r => r.kind == "proc" || r.kind == "run" || r.kind == "machine") || rows[0] || {}).key || null;
    drawList(); detail();
  } catch (e) { say(e.message); } finally { stating = false; }
}
function choose(key, reveal = true) {
  if (key == sel) return;
  sel = key; history.replaceState(null, "", "#" + encodeURIComponent(key || "")); det = null; dsel = -1;
  closeView(); drawList(); detail(true);
  if (reveal) document.querySelector("#list .row.sel")?.scrollIntoView({block: "nearest"});
}
function move(d) {
  if (!rows.length) return;
  choose(rows[Math.max(0, Math.min(rows.length - 1, rows.findIndex(r => r.key == sel) + d))].key);
}
function toggle(r) {
  if (r.kind == "more") { shown += 50; return refresh(); }
  if (!r.fold) return;
  const inOpened = r.kind == "group" || r.kind == "centries", set = inOpened ? opened : folded;
  set.has(r.fold) ? set.delete(r.fold) : set.add(r.fold); keep(inOpened ? "opened" : "folded", [...set]); refresh();
}
function fold(unfold) {
  const i = rows.findIndex(r => r.key == sel), r = rows[i];
  if (!r) return;
  if (r.open !== null && r.open != unfold) return toggle(r);
  if (!unfold && r.open === null) {
    for (let j = i - 1; j >= 0; j--) if (rows[j].open !== null && (rows[j].depth < r.depth || r.depth == 0)) return choose(rows[j].key);
  } else if (unfold && r.open) move(1);
}

// ── the detail ─────────────────────────────────────────────────────────────
const ANSI = /\x1b\[([0-9;]*)m/g;
function ansi(text) {                                   // the program's colours, as spans
  let out = "", cls = [], last = 0, m;
  const flush = s => { if (s) out += cls.length ? `<span class="${cls.join(" ")}">${esc(s)}</span>` : esc(s); };
  ANSI.lastIndex = 0;
  while ((m = ANSI.exec(text))) {
    flush(text.slice(last, m.index)); last = ANSI.lastIndex;
    for (const c of (m[1] || "0").split(";").map(Number)) {
      if (c == 0) cls = []; else if (c >= 1 && c <= 4) cls.push("a" + c);
      else if (c >= 30 && c <= 37) cls = cls.filter(x => x[0] != "c").concat("c" + (c - 30));
      else if (c >= 90 && c <= 97) cls = cls.filter(x => x[0] != "c").concat("c" + (c - 90));
    }
  }
  flush(text.slice(last)); return out;
}
function outputs() { return det ? det.rows.filter(r => r.kind == "output") : []; }
function pathOf(o) { return o.path || (det && det.console); }
function fileUrl(path, download) { return "/file?" + new URLSearchParams({key: sel, path, ...(download ? {download: 1} : {})}); }
function isPath(v) { return /^\/\S*$/.test(v); }
function consoleHtml(rs) {
  let h = "", lines = [];
  const close = () => { if (lines.length) h += `<div class="lines">${lines.join("\n")}</div>`; lines = []; };
  for (const r of rs) {
    if (r.kind == "out") { lines.push(ansi(r.label.replace(/^  │ /, ""))); continue; }
    close();
    if (r.kind == "chead") h += `<div class="chead">${esc(r.label)}</div>`;
    else if (r.kind == "cend") { const m = r.label.match(/^\s*╰ (\S+)(.*)$/);
      h += `<div class="cend">╰ <span class="st ${esc(r.status)}">${esc(m ? m[1] : r.status)}</span>${esc(m ? m[2] : "")}</div>`; }
    else if (r.label) h += `<div class="${r.kind == "broken" ? "broken" : "note"}">${esc(r.label.trim())}</div>`;
  }
  close(); return h;
}
const SVG = d => `<svg class="i" viewBox="0 0 16 16" aria-hidden="true">${d}</svg>`;
const ICONS = {
  machine: SVG('<rect x="1.5" y="2.5" width="13" height="8.5" rx="1.2"/><path d="M5.5 14h5M8 11v3"/>'),
  env: SVG('<path d="M8 1.6 14 4.6v6.8L8 14.4 2 11.4V4.6z"/><path d="M2 4.6 8 7.6l6-3M8 7.6v6.8"/>'),
  clock: SVG('<circle cx="8" cy="8" r="6.2"/><path d="M8 4.5V8l2.4 1.6"/>'),
  took: SVG('<path d="M4 1.8h8M4 14.2h8M5 1.8c0 3.4 6 3.4 6 6.2s-6 2.8-6 6.2M11 1.8c0 3.4-6 3.4-6 6.2s6 2.8 6 6.2"/>'),
  folder: SVG('<path d="M1.8 4.2c0-.7.5-1.2 1.2-1.2h3l1.5 1.6h5.5c.7 0 1.2.5 1.2 1.2v6.4c0 .7-.5 1.2-1.2 1.2H3c-.7 0-1.2-.5-1.2-1.2z"/>'),
  run: SVG('<path d="M1.8 4.2c0-.7.5-1.2 1.2-1.2h3l1.5 1.6h5.5c.7 0 1.2.5 1.2 1.2v6.4c0 .7-.5 1.2-1.2 1.2H3c-.7 0-1.2-.5-1.2-1.2z"/><path d="M7 7.2v3.6l3-1.8z"/>'),
  code: SVG('<path d="M9.5 1.8H4.2c-.7 0-1.2.5-1.2 1.2v10c0 .7.5 1.2 1.2 1.2h7.6c.7 0 1.2-.5 1.2-1.2V5.3z"/><path d="M9.5 1.8v3.5H13M6.6 8.2 5.2 9.8l1.4 1.6M9.4 8.2l1.4 1.6-1.4 1.6"/>'),
  file: SVG('<path d="M9.5 1.8H4.2c-.7 0-1.2.5-1.2 1.2v10c0 .7.5 1.2 1.2 1.2h7.6c.7 0 1.2-.5 1.2-1.2V5.3z"/><path d="M9.5 1.8v3.5H13"/>'),
  text: SVG('<path d="M9.5 1.8H4.2c-.7 0-1.2.5-1.2 1.2v10c0 .7.5 1.2 1.2 1.2h7.6c.7 0 1.2-.5 1.2-1.2V5.3z"/><path d="M9.5 1.8v3.5H13M5.6 8.5h4.8M5.6 11h3.4"/>'),
  console: SVG('<rect x="1.5" y="2.5" width="13" height="11" rx="1.2"/><path d="m4.5 6.3 2 1.7-2 1.7M8 10.2h3.5"/>'),
  image: SVG('<rect x="1.8" y="2.5" width="12.4" height="11" rx="1.2"/><circle cx="5.6" cy="6" r="1.2"/><path d="m2 12 3.8-3.6 2.6 2.4 2-1.8 3.8 3.2"/>'),
  page: SVG('<circle cx="8" cy="8" r="6.2"/><path d="M1.8 8h12.4M8 1.8c1.8 2 1.8 10.4 0 12.4M8 1.8c-1.8 2-1.8 10.4 0 12.4"/>'),
  host: SVG('<rect x="2" y="2" width="12" height="5" rx="1"/><rect x="2" y="9" width="12" height="5" rx="1"/><path d="M4.5 4.5h.01M4.5 11.5h.01"/>'),
};
function iconOf(name) {
  if (name == "console") return ICONS.console;
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(name)) return ICONS.image;
  if (/\.(html?|pdf)$/i.test(name)) return ICONS.page;
  if (/\.(txt|log|ya?ml|json|csv|md|out|err)$/i.test(name)) return ICONS.text;
  if (/\.(py|cpp|hpp|h|c|cu|cuh|sh|js|ts|rs|jl)$/i.test(name)) return ICONS.code;
  return ICONS.file;
}
function chip(icon, text, data, title) {
  const shownNow = data && data.path && view && view.path == data.path;
  const attrs = data ? Object.entries(data).map(([k, v]) => `data-${k}="${esc(v)}"`).join(" ") : "";
  return `<span class="chip${data ? " click" : ""}${shownNow ? " shown" : ""}" ${attrs} title="${esc(title || text)}">${ICONS[icon]}<span>${esc(text)}</span></span>`;
}
function hhmm(t, now) {
  const d = new Date(t * 1000), n = new Date(now * 1000), two = x => String(x).padStart(2, "0");
  const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
  return d.toDateString() == n.toDateString() ? time : `${d.toLocaleDateString(undefined, {day: "numeric", month: "short"})} ${time}`;
}
function badgeOf(f) {
  const s = f.status || f.state || "";
  const tone = /^PASS/.test(s) ? "ok" : /^(FAIL|ERROR|TIMEOUT)/.test(s) ? "bad" : /^running/.test(s) ? "run" : /^waiting/.test(s) ? "wait" : "";
  const word = /^waiting/.test(s) ? "waiting" : s.split(/[\s:]/)[0];
  return word ? `<span class="badge ${tone}" title="${esc(s)}">${{ok: "✓ ", bad: "✗ ", run: "● ", wait: "◌ "}[tone] || ""}${esc(word)}</span>` : "";
}
// a run, a process: the badge, then what it is as one grid of icons, each that can be acted on, clickable
const COVERED = new Set(["machine", "project", "what", "env", "status", "state", "started", "took", "leaf"]);
function runHead(f) {
  const what = f.what || det.title, name = what.includes("::") ? what.split("::").slice(1).join("::") : what;
  let h = `<div class="head">${badgeOf(f)}<h2 title="${esc(what)}">${esc(name)}</h2></div><div class="chips">`;
  const machine = det.machine || (f.machine || "").split(" ")[0];
  if (machine) h += chip("machine", f.machine || machine, {machine}, "the machine: its row, in the machines tab");
  if (f.env) h += chip("env", f.env, {env: f.env}, "its environment: every run in it ( the filter )");
  const took = f.took || (det.started && /^(running|waiting)/.test(f.state || "") ? ago(det.now - det.started) + " so far" : "");
  if (took) h += chip("took", took, null, (f.took ? "how long it took" : "how long it runs") +
                     (det.started ? ` · started ${hhmm(det.started, det.now)}, ${f.started || ""}` : ""));
  h += `<span class="br"></span>`;                       // where it is, on a line of its own
  if (f.project) h += chip("folder", f.project.split("/").pop(), {path: f.project, dir: 1}, f.project);
  if (det.file) h += chip("code", det.file.split("/").pop(), {path: det.file}, det.file);     // where the server found it
  if (f.leaf) h += chip("run", "run", {path: f.leaf, dir: 1}, f.leaf);
  return h + `</div>`;
}
function factHtml(r) {
  const v = isPath(r.v) ? `<span class="path${view && view.path == r.v ? " shown" : ""}" data-path="${esc(r.v)}" title="click: show · double-click: open · right-click: more">${esc(r.v)}</span>` : esc(r.v);
  return `<span class="k">${esc(r.k)}</span><span class="v">${v}</span>`;
}
function outputHtml(rs) {
  let h = "", n = 0;
  const said = det.rows.filter(r => r.kind == "out" && !/^\s*│ \( (no output|nothing yet) \)$/.test(r.label)).length, empties = [];
  const lines = said ? said + (said == 1 ? " line" : " lines") : "empty";
  for (const r of rs) {
    const i = n++, p = pathOf(r), size = (r.detail || "").split("  ")[0];
    if (r.path && size == "0 B") { empties.push([i, r, p]); continue; }
    const shownNow = view && (r.path ? view.path == p : view.console);
    h += `<div class="out${shownNow ? " sel" : ""}" data-out="${i}" data-path="${esc(p || "")}"${r.path ? "" : ` data-console="1"`} title="${esc(p || "")}">` +
         `<span class="n">${iconOf(r.label)}${esc(r.label)}</span><span class="d">${r.path ? esc(size) : lines}</span></div>`;
  }
  if (empties.length) h += `<div class="out empty"><span class="n">${ICONS.file}${empties.map(([i, r, p]) =>
      `<span class="e${view && view.path == p ? " sel" : ""}" data-out="${i}" data-path="${esc(p)}">${esc(r.label)}</span>`).join(", ")}</span><span class="d">empty</span></div>`;
  return h;
}
function drawDetail() {
  const d = $("detail");
  if (!sel) { put(d, `<span class="note">choose a row</span>`); return; }
  if (!det) { put(d, `<span class="note">reading…</span>`); return; }
  const can = det.can || {}, row = rows.find(r => r.key == sel);
  const facts = det.rows.filter(r => r.kind == "plain" && r.k !== undefined), f = Object.fromEntries(facts.map(r => [r.k, r.v]));
  const isWork = det.kind == "proc" || det.kind == "run";
  let h = isWork ? runHead(f) : `<h2>${esc(det.title)}</h2>`;
  let tools = "";
  if (can.kill) tools += `<button class="danger" data-act="kill">${row && (row.kind == "machine" || row.kind == "broken") ? "kill all" : "kill"}<kbd>k</kbd></button>`;
  if (can.watch) tools += `<button data-act="watch">${can.watch}<kbd>a</kbd></button>`;
  for (const how of can.caches || []) tools += `<button class="danger" data-act="cache_remove" data-how="${how}">${CACHE_ACTS[how][0]}<kbd>${CACHE_ACTS[how][1]}</kbd></button>`;
  if (can.hold) tools += `<button data-act="cache_hold">this machine holds it<kbd>h</kbd></button>`;
  if (can.caches) tools += `<button data-days="1">unused after ${cacheDays} d<kbd>n</kbd></button><button data-all="1">${cacheAll ? "dead and unused only" : "every entry"}<kbd>v</kbd></button>`;
  if (can.rename) tools += `<button data-act="rename">rename machine<kbd>r</kbd></button>`;
  if (can.forget) tools += `<button data-act="forget">forget<kbd>f</kbd></button>`;
  if (isWork && !JOB) tools += `<a class="btn" href="/job?${esc(new URLSearchParams({key: sel}))}" target="_blank" rel="noopener" title="this run as a page of its own: its outputs left, the one chosen right">page ↗</a>`;
  if (tools) h += `<div class="tools">${tools}</div>`;
  const shownFacts = facts.filter(r => !RARE.has(r.k) && !(isWork && COVERED.has(r.k)));
  const rare = facts.filter(r => RARE.has(r.k) || (isWork && COVERED.has(r.k) && isPath(r.v)) || (isWork && r.k == "what"))
                    .concat(isWork && det.started ? [{k: "started", v: `${hhmm(det.started, det.now)} · ${f.started || ""}`}] : []);
  if (shownFacts.length) h += `<div class="facts">${shownFacts.map(factHtml).join("")}</div>`;
  if (rare.length) h += (showMore ? `<div class="facts">${rare.map(factHtml).join("")}</div>` : "") +
    `<div class="more" id="more">${showMore ? "▾ less" : `▸ more: ${esc(rare.map(r => r.k).join(", "))}`}</div>`;
  const outs = [];
  for (const r of det.rows) {
    if (r.kind == "head") { if (outs.length) { h += outputHtml(outs); outs.length = 0; } h += `<h3>${esc(r.label)}</h3>`; continue; }
    if (r.kind == "output") { outs.push(r); continue; }
    if (outs.length) { h += outputHtml(outs); outs.length = 0; }
  }
  if (outs.length) h += outputHtml(outs);
  if (!isWork) h += consoleHtml(consoleRows());              // what else the detail says ( a note, an error )
  const top = d.scrollTop, stick = d.scrollTop + d.clientHeight >= d.scrollHeight - 4;
  if (put(d, h)) d.scrollTop = stick ? d.scrollHeight : top;           // the end of a console that grows stays in view
}
let detailing = false;
async function detail(now) {
  if (!sel) return drawDetail();
  if (detailing && !now) return; detailing = true;
  const key = sel;
  try {
    const got = await ask("/detail?" + new URLSearchParams({key}));
    if (key != sel) return;
    det = got; drawDetail();
    if (JOB) document.title = (ONLY && JOBQ.get("path") ? JOBQ.get("path").split("/").pop() + " · " : "") + det.title + " · errand";
    if (jobPath && jobPath == det.console) { showConsole(); jobPath = null; }     // the console, as the page draws it
    else if (jobPath) { show(jobPath, false); jobPath = null; }
    else if (!view || view.key != sel || view.console) showConsole(); else show(view.path, view.dir, true);
  } catch (e) { if (key == sel) { det = {title: e.message, rows: [], can: {}}; drawDetail(); } } finally { detailing = false; }
}

// ── the pane below: a file, a folder ───────────────────────────────────────
function closeView() { view = null; put($("vh"), ""); put($("vb"), ""); }
function consoleRows() {                                // what the detail rows say after the outputs: the console
  if (!det) return [];
  let after = false, heads = 0;
  const rest = [];
  for (const r of det.rows) {
    if (r.kind == "plain" && r.k !== undefined) continue;
    if (r.kind == "head") { heads++; continue; }
    if (r.kind == "output") { after = true; continue; }
    if (after || !heads) rest.push(r);
  }
  return rest;
}
function showConsole() { view = {key: sel, console: true}; drawView(); drawDetail(); }
async function show(path, dir, again) {
  if (!path || !sel) return;
  const key = sel;
  if (!again || !view || view.path != path) { view = {key, path, dir, got: null}; $("right").classList.add("viewing"); drawView(); drawDetail(); }
  try {
    let got;
    if (dir) got = {dir: await ask("/ls?" + new URLSearchParams({key, path}))};
    else {
      try { got = {file: await ask("/peek?" + new URLSearchParams({key, path, ...(ONLY ? {size: 1 << 20} : {})}))}; }
      catch (e) { if (/directory/i.test(e.message)) { view.dir = true; return show(path, true, again); } throw e; }
    }
    if (view && view.path == path) { view.got = got; drawView(); }
  } catch (e) { if (view && view.path == path) { view.got = {error: e.message}; drawView(); } }
}
function vbuttons(path, dir) {
  const here = det && det.here;
  return (dir ? "" : `<a class="btn" href="${esc(tabUrl(path))}" target="_blank" rel="noopener" title="open in a tab">↗</a>` +
          `<button data-v="edit" title="in an editor ( e )">✎</button>` +
          `<a class="btn" href="${esc(fileUrl(path, true))}" title="download ( d )">⤓</a>`) +
         (here ? `<button data-v="reveal" title="in the Finder">${dir ? "open folder" : "show in folder"}</button>` : "") +
         `<button data-v="copy" title="copy the path">copy path</button>` +
         (view && view.console ? "" : `<button data-v="close" title="back to the console ( esc )">×</button>`);
}
function drawView() {
  if (!view) return;
  const v = $("view");
  if (view.console) {                                     // the console: what is shown when nothing else is
    const isWork = det && (det.kind == "proc" || det.kind == "run"), path = det && det.console;
    const stick = v.scrollTop + v.clientHeight >= v.scrollHeight - 4;
    put($("vh"), `<div class="vhead"><span class="where"><b>console</b>${path ? " · " + esc(path.split("/").pop()) : ""}</span>` +
      (path ? vbuttons(path, false) : "") + `</div>`);
    if (put($("vb"), isWork ? consoleHtml(consoleRows()) : `<div class="note">a run's console shows here</div>`) && stick)
      v.scrollTop = v.scrollHeight;                     // the end of a console that grows stays in view
    return;
  }
  const {path, dir, got} = view, name = path.split("/").pop();
  const parent = path.slice(0, path.lastIndexOf("/")) || "/";
  put($("vh"), `<div class="vhead"><span class="where" title="${esc(path)}">&lrm;${esc(parent)}/<b>${esc(name)}</b>${dir ? "/" : ""}</span>${vbuttons(path, dir)}</div>`);
  let h = "";
  if (!got) h += `<div class="note">reading…</div>`;
  else if (got.error) h += `<div class="broken">${esc(got.error)}</div>`;
  else if (got.dir) {
    h += `<div class="ent dir" data-path="${esc(parent)}" data-dir="1"><span class="n">..</span><span></span><span></span></div>`;
    h += got.dir.entries.map(e => `<div class="ent${e.dir ? " dir" : ""}" data-path="${esc(path + "/" + e.name)}" data-dir="${e.dir ? 1 : ""}" title="click: show · double-click: open · right-click: more">` +
         `<span class="n">${esc(e.name)}${e.dir ? "/" : ""}</span><span class="s">${e.dir ? "" : size(e.size)}</span><span class="a">${ago(e.age)}</span></div>`).join("")
         || `<div class="note">empty</div>`;
  } else {
    const f = got.file, url = esc(fileUrl(path) + "&v=" + f.size);    // read again when it changed
    if (f.kind == "image") h += `<div class="peek"><img src="${url}" alt="${esc(name)}"></div>`;
    else if (f.kind == "page") h += `<div class="peek" style="height:100%"><iframe sandbox="allow-scripts allow-popups allow-downloads" src="${url}"></iframe></div>`;
    else if (f.kind == "binary") h += `<div class="note">binary, ${size(f.size)}: double-click opens it</div>`;
    else h += (f.text && !f.text.includes("\x1b[") && lang(name) ? `<div class="code">${highlight(f.text, lang(name))}</div>`
                                                                    : `<div class="lines">${ansi(f.text) || "( empty )"}</div>`) + (f.more ? `<div class="note">┆ … ${size(f.more)} more ( double-click: all of it )</div>` : "");
  }
  const stick = v.scrollTop > 0 && v.scrollTop + v.clientHeight >= v.scrollHeight - 4;
  if (put($("vb"), h) && stick) v.scrollTop = v.scrollHeight;   // a file that grows, read from its end: stays there
}
// open: what the hand expects of a double-click -- a page or an image in a tab, a text in an editor, a folder in the Finder
function open(path, dir) {
  if (!path) return say("no output yet");
  if (dir) return det && det.here ? act("reveal", {path}) : show(path, true);
  if (OPENED_IN_A_TAB.test(path)) return openTab(fileUrl(path));
  if (det && det.here) return act("edit", {path});
  openTab(tabUrl(path));
}
// a tab: a page, an image, a pdf as they are; a text in the job's page, highlighted
function tabUrl(path) { return OPENED_IN_A_TAB.test(path) ? fileUrl(path) : "/job?" + new URLSearchParams({key: sel, path, only: 1}); }
function openTab(url) {                                 // a link followed: what popup blockers let through
  const a = document.createElement("a"); a.href = url; a.target = "_blank"; a.rel = "noopener";
  document.body.appendChild(a); a.click(); a.remove();
}
function vAction(what, path, dir) {
  if (what == "tab") openTab(tabUrl(path));
  else if (what == "edit") act("edit", {path});
  else if (what == "download") location.href = fileUrl(path, true);
  else if (what == "reveal") act("reveal", {path});
  else if (what == "copy") navigator.clipboard.writeText(path).then(() => say("copied: " + path), () => say(path));
  else if (what == "show") show(path, dir);
  else if (what == "open") open(path, dir);
  else if (what == "close") showConsole();
}
function pick(n) {                                       // an output chosen with the keys: shown below
  const os = outputs(); if (!os.length) return;
  const o = os[Math.max(0, Math.min(os.length - 1, n))];
  o.path ? show(o.path, false) : showConsole();
  document.querySelector("#detail .out.sel, #detail .out .e.sel")?.scrollIntoView({block: "nearest"});
}
// the output shown below is the one chosen: one place says it, the keys move from it
function shownIndex() { return outputs().findIndex(o => view && (o.path ? view.path == o.path : view.console)); }
function chosenPath() { return view && !view.dir && !view.console ? view.path : det && det.console; }

// ── colours of a source ────────────────────────────────────────────────────
// a few languages, by their names; enough to read a script, a config, a record -- not a compiler
const KW = {
  py: "False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case self",
  sh: "if then else elif fi for while until do done case esac function in return export local set exit source",
  c: "auto bool break case catch char class const constexpr continue default delete do double else enum explicit extern false float for friend if inline int long namespace new nullptr operator private protected public return short signed sizeof static struct switch template this throw true try typedef typename union unsigned using virtual void volatile while __global__ __device__ __host__",
  js: "async await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof undefined var void while yield of",
  yaml: "true false null yes no on off", json: "true false null"};
function lang(name) {
  const e = (name.match(/\.([^.]+)$/) || [])[1] || "";
  return {py: "py", pyi: "py", sh: "sh", bash: "sh", zsh: "sh", c: "c", h: "c", cc: "c", cpp: "c", cxx: "c", hpp: "c", cu: "c", cuh: "c",
          js: "js", ts: "js", mjs: "js", yaml: "yaml", yml: "yaml", json: "json", jsonl: "json", toml: "yaml", cfg: "yaml", ini: "yaml"}[e] || null;
}
const RULES = {
  py: [["c", /#[^\n]*/], ["s", /[rbfuRBFU]{0,2}(?:"{3}[\s\S]*?"{3}|'{3}[\s\S]*?'{3}|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/],
       ["d", /@[\w.]+/], ["f", /(?<=\b(?:def|class)\s+)\w+/], ["n", /\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?j?\b/], ["k", /\b\w+\b/]],
  sh: [["c", /#[^\n]*/], ["s", /"(?:\\.|[^"\\])*"|'[^']*'/], ["d", /\$\{?[\w@#?*!-]+\}?/], ["n", /\b\d+\b/], ["k", /\b\w+\b/]],
  c:  [["c", /\/\/[^\n]*|\/\*[\s\S]*?\*\//], ["d", /^[ \t]*#[ \t]*\w+[^\n]*/], ["s", /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])'/],
       ["n", /\b(?:0x[\da-fA-F]+|\d+\.?\d*(?:[eE][+-]?\d+)?)[fFuUlL]*\b/], ["f", /\b\w+(?=\s*\()/], ["k", /\b\w+\b/]],
  js: [["c", /\/\/[^\n]*|\/\*[\s\S]*?\*\//], ["s", /`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'/],
       ["n", /\b\d+\.?\d*(?:[eE][+-]?\d+)?\b/], ["f", /\b\w+(?=\s*\()/], ["k", /\b\w+\b/]],
  yaml: [["c", /#[^\n]*/], ["key", /^[ \t-]*[\w.\-/ ]+?(?=[ \t]*[:=](?:[ \t]|$))/], ["s", /"(?:\\.|[^"\\\n])*"|'[^'\n]*'/],
         ["n", /\b-?\d+\.?\d*(?:[eE][+-]?\d+)?\b/], ["k", /\b\w+\b/]],
  json: [["key", /"(?:\\.|[^"\\\n])*"(?=\s*:)/], ["s", /"(?:\\.|[^"\\\n])*"/], ["n", /-?\b\d+\.?\d*(?:[eE][+-]?\d+)?\b/], ["k", /\b\w+\b/]],
};
function highlight(text, l) {
  const rules = RULES[l];
  if (!rules || text.length > 400000) return esc(text);
  const kw = new Set((KW[l] || "").split(" ")), all = new RegExp(rules.map(([, r]) => "(" + r.source + ")").join("|"), "gm");
  let out = "", last = 0, m;
  while ((m = all.exec(text))) {
    if (m[0] === "") { all.lastIndex++; continue; }
    const i = m.slice(1).findIndex(x => x !== undefined);
    let kind = rules[i] && rules[i][0];
    if (kind == "k" && !kw.has(m[0])) kind = null;          // a word that is no keyword: as it is
    out += esc(text.slice(last, m.index)) + (kind ? `<span class="tk-${kind}">${esc(m[0])}</span>` : esc(m[0]));
    last = all.lastIndex;
  }
  return out + esc(text.slice(last));
}

// ── the menu ───────────────────────────────────────────────────────────────
function menu(x, y, path, dir) {
  const here = det && det.here, m = $("menu");
  const items = [["show", "show below", "click"], ["open", dir ? (here ? "open in the Finder" : "show below") : OPENED_IN_A_TAB.test(path) ? "open in a tab" : here ? "open in the editor" : "open in a tab", "double-click"]];
  if (!dir) items.push(["tab", "open in a tab", ""], ["edit", "edit ( on this machine )", "e"], ["download", "download", "d"]);
  items.push(["reveal", dir ? "open in the Finder" : "show in the Finder", "", !here], ["copy", "copy the path", ""]);
  m.innerHTML = items.map(([w, t, k, off]) => `<div data-m="${w}" class="${off ? "off" : ""}">${esc(t)}<kbd>${esc(k)}</kbd></div>`).join("");
  m.onclick = e => { const it = e.target.closest("[data-m]"); if (it) { hideMenu(); vAction(it.dataset.m, path, dir); } };
  m.classList.add("on");
  const r = m.getBoundingClientRect();
  m.style.left = Math.min(x, innerWidth - r.width - 8) + "px"; m.style.top = Math.min(y, innerHeight - r.height - 8) + "px";
}
function hideMenu() { $("menu").classList.remove("on"); }
document.addEventListener("click", e => { if (!e.target.closest("#menu")) hideMenu(); });

// ── windows ────────────────────────────────────────────────────────────────
function closeBox() { modal = null; $("veil").classList.remove("on"); }
function confirmBox(c, go) {
  modal = {enter: () => { closeBox(); go(); }};
  $("box").className = "box" + (c.danger ? " danger" : "");
  $("box").innerHTML = `<h4>${esc(c.title)}</h4><ul>${c.lines.map(l => `<li>${esc(l)}</li>`).join("")}</ul>` +
    `<div class="keys"><button id="no">nothing<kbd>esc</kbd></button><button id="yes" class="${c.danger ? "danger" : "primary"}">${esc(c.verb)}<kbd>enter</kbd></button></div>`;
  $("veil").classList.add("on"); $("yes").onclick = modal.enter; $("no").onclick = () => { closeBox(); say("nothing done"); };
  $("yes").focus();
}
function promptBox(p, go) {
  $("box").className = "box";
  $("box").innerHTML = `<h4>${esc(p.title)}</h4><input id="typed" value="${esc(p.text)}" spellcheck="false">` +
    `<div class="keys"><button id="no">nothing<kbd>esc</kbd></button><button id="yes" class="primary">keep it<kbd>enter</kbd></button></div>`;
  modal = {enter: () => { const v = $("typed").value; closeBox(); go(v); }};
  $("veil").classList.add("on"); $("yes").onclick = modal.enter; $("no").onclick = () => { closeBox(); say("nothing done"); };
  $("typed").focus(); $("typed").select();
}
function helpBox() {
  $("box").className = "box";
  $("box").innerHTML = `<h4>keys</h4><div class="help">${KEYS.map(([k, w]) => `<kbd>${esc(k)}</kbd><span>${esc(w)}</span>`).join("")}</div>` +
    `<div class="keys"><button id="yes" class="primary">close<kbd>esc</kbd></button></div>`;
  modal = {enter: closeBox}; $("veil").classList.add("on"); $("yes").onclick = closeBox;
}

// ── what the hand does ─────────────────────────────────────────────────────
function setFocus(f) {
  focus = f; $("list").classList.toggle("focus", f == "list"); $("detail").classList.toggle("focus", f == "detail");

}
function setTab(t) { if (t == tab) return; tab = t; keep("tab", t); sel = null; det = null; closeView(); setFocus("list"); refresh(); }
function refresh() { state(); }
function askDays() {                                      // the caches tab: unused after how many days ( ADR 0022 )
  promptBox({title: "unused after how many days?", text: String(cacheDays)}, t => {
    const d = Number(t); if (!(d > 0)) return say(`${t}: a number of days, above 0`);
    cacheDays = d; keep("cacheDays", d); say(`unused: not used for ${d} days`); refresh(); });
}
function toggleAll() { cacheAll = !cacheAll; keep("cacheAll", cacheAll); say(cacheAll ? "every entry" : "the dead and unused entries only"); refresh(); }
const opening = e => e.detail >= 2 || (MAC ? e.metaKey : e.ctrlKey);

document.addEventListener("keydown", e => {
  if (modal) {
    if (e.key == "Escape") { closeBox(); say("nothing done"); e.preventDefault(); }
    else if (e.key == "Enter") { modal.enter(); e.preventDefault(); }
    return;
  }
  if (e.key == "Escape" && $("menu").classList.contains("on")) { hideMenu(); return; }
  if (e.target == $("q")) {
    if (e.key == "Escape") { $("q").value = ""; query = ""; refresh(); $("q").blur(); }
    else if (e.key == "Enter") $("q").blur();
    return;
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key, inList = focus == "list";
  const page = Math.max(1, Math.floor($("list").clientHeight / 21) - 1);
  let done = true;
  if (k == "ArrowDown") inList ? move(1) : pick(shownIndex() + 1);
  else if (k == "ArrowUp") inList ? move(-1) : pick(Math.max(0, shownIndex() - 1));
  else if (k == "PageDown") inList ? move(page) : $("detail").scrollBy(0, $("detail").clientHeight - 40);
  else if (k == "PageUp") inList ? move(-page) : $("detail").scrollBy(0, -$("detail").clientHeight + 40);
  else if (k == "Home") inList ? choose(rows[0]?.key) : pick(0);
  else if (k == "End") inList ? choose(rows[rows.length - 1]?.key) : pick(1e9);
  else if (k == "ArrowRight") inList && fold(true);
  else if (k == "ArrowLeft") inList && fold(false);
  else if (k == "Tab") JOB || setFocus(inList ? "detail" : "list");
  else if ((k == "1" || k == "2" || k == "3") && !JOB) setTab({"1": "runs", "2": "machines", "3": "caches"}[k]);
  else if (tab == "caches" && "iudD".includes(k) && !JOB) act("cache_remove", {how: {i: "dead", u: "unused", d: "flagged", D: "everywhere"}[k]});
  else if (tab == "caches" && k == "h" && !JOB) act("cache_hold");
  else if (tab == "caches" && k == "n" && !JOB) askDays();
  else if (tab == "caches" && k == "v" && !JOB) toggleAll();
  else if (k == "Enter") {
    if (!inList) open(chosenPath(), view && view.dir);
    else { const r = rows.find(r => r.key == sel); if (r && (r.open !== null || r.kind == "more")) toggle(r); else setFocus("detail"); }
  }
  else if (k == "o") open(chosenPath(), view && view.dir);
  else if (k == "e") { const p = chosenPath(); p ? act("edit", {path: p}) : say("e: on a run, an output"); }
  else if (k == "d") { const p = chosenPath(); p ? (location.href = fileUrl(p, true)) : say("d: on a run, an output"); }
  else if (k == "k") act("kill");
  else if (k == "f") act("forget");
  else if (k == "a") act("watch");
  else if (k == "r") act("rename");
  else if (k == "R") act("refresh");
  else if (k == "/") $("q").focus();
  else if (k == "?") helpBox();
  else if (k == "Escape") { if (view && !view.console) showConsole(); else { query = ""; $("q").value = ""; refresh(); } }
  else done = false;
  if (done) e.preventDefault();
});
$("list").addEventListener("click", e => {
  const el = e.target.closest(".row"); if (!el) return;
  const r = rows.find(r => r.key == el.dataset.key); if (!r) return;
  setFocus("list"); choose(r.key, false);
  if (e.target.closest(".fold") || r.kind == "day" || r.kind == "group" || r.kind == "more" || (r.open !== null && e.detail == 2)) toggle(r);
});
function pathClick(e, el) {
  const path = el.dataset.path, dir = !!el.dataset.dir;
  if (!path) return say("no output yet");
  if (opening(e)) open(path, dir); else show(path, dir);
}
$("detail").addEventListener("click", e => {
  if (e.target.closest("button[data-days]")) return askDays();
  if (e.target.closest("button[data-all]")) return toggleAll();
  const b = e.target.closest("button[data-act]"); if (b) return act(b.dataset.act, b.dataset.how ? {how: b.dataset.how} : undefined);
  if (e.target.closest("#more")) { showMore = !showMore; keep("more", showMore); return drawDetail(); }
  const c = e.target.closest(".chip.click");
  if (c && c.dataset.machine) { const key = `["machine", ${JSON.stringify(c.dataset.machine)}, null]`;
    tab = "machines"; keep("tab", tab); sel = key; det = null; closeView(); setFocus("list"); return refresh(); }
  if (c && c.dataset.env) { query = c.dataset.env; $("q").value = query; return refresh(); }
  if (c && c.dataset.path) return pathClick(e, c);
  const o = e.target.closest(".out .e, .out:not(.empty)");
  if (o) { setFocus("detail"); return o.dataset.console && !opening(e) ? showConsole() : pathClick(e, o); }
  const p = e.target.closest(".path"); if (p) return pathClick(e, p);
});
$("view").addEventListener("click", e => {
  const b = e.target.closest("button[data-v]"); if (b) return vAction(b.dataset.v, view.path, view.dir);
  const ent = e.target.closest(".ent"); if (ent) return pathClick(e, ent);
});
for (const pane of ["detail", "view"]) $(pane).addEventListener("contextmenu", e => {
  const el = e.target.closest(".out .e, .out:not(.empty), .path, .ent, .chip[data-path]"); if (!el || !el.dataset.path) return;
  e.preventDefault(); menu(e.clientX, e.clientY, el.dataset.path, !!el.dataset.dir);
});
$("detail").addEventListener("focus", () => focus != "detail" && setFocus("detail"));
document.querySelectorAll(".tab").forEach(b => b.onclick = () => setTab(b.dataset.tab));
$("refresh").onclick = () => act("refresh");
$("helpb").onclick = helpBox;
let typing; $("q").addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => { query = $("q").value; refresh(); }, 150); });
$("veil").addEventListener("click", e => { if (e.target == $("veil")) closeBox(); });
if (JOB) {
  sel = JOBQ.get("key"); focus = "detail";
  document.body.classList.add("job");
  if (ONLY) document.body.classList.add("only");
  $("main").insertBefore($("detail"), $("vsplit"));     // the detail where the list was, the viewer all the right
  $("list").classList.remove("focus"); $("detail").classList.add("focus");
}
foot(); refresh();
setInterval(() => { if (!document.hidden) { state(); foot(); } }, EVERY);
</script>
</body>
</html>
"""
