// Factory — the hosted dashboard's whole front end.
//
// Everything a person changes here ends up as a small edit to a file in the
// repository, committed through /api/commit. Settings are edited in place
// (lib/yamledit.js) so the comments in each config survive.
import { parseBank, serializeBank } from "/lib/bank.js";
import { campaignFiles, slugify } from "/lib/template.js";
import { replaceTop, setList, setScalar, yamlString } from "/lib/yamledit.js";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const yaml = (text) => {
  try { return window.jsyaml.load(text || "", { schema: window.jsyaml.CORE_SCHEMA }) || {}; }
  catch { return {}; }
};

const ICON = {
  Schedule: '<svg viewBox="0 0 24 24"><rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/></svg>',
  Content: '<svg viewBox="0 0 24 24"><rect x="3.5" y="4" width="17" height="16" rx="2.5"/><path d="m10 9 5 3-5 3z"/></svg>',
  Plan: '<svg viewBox="0 0 24 24"><path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></svg>',
  Setup: '<svg viewBox="0 0 24 24"><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></svg>',
  Jobs: '<svg viewBox="0 0 24 24"><path d="M13 3 5 13h6l-1 8 8-10h-6z"/></svg>',
};
const TABS = Object.keys(ICON);

let STATE = null;
let TAB = "Schedule";
const ASSETS = new Map();

// ------------------------------------------------------------------ plumbing

async function api(path, { method = "GET", body } = {}) {
  const init = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") {
    init.headers["content-type"] = "application/json";
    init.headers["x-ugc"] = "1";
    init.body = JSON.stringify(body || {});
  }
  const res = await fetch(`/api/${path}`, init);
  let data = {};
  try { data = await res.json(); } catch { /* an empty body is fine */ }
  if (res.status === 401 && path !== "login") { showLogin(); throw new Error("Sign in to continue."); }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status}).`);
  return data;
}

let toastTimer = 0;
function toast(text, bad = false) {
  $$(".toast").forEach((t) => t.remove());
  const el = document.createElement("div");
  el.className = `toast${bad ? " bad" : ""}`;
  el.setAttribute("role", "status");
  el.textContent = text;
  document.body.append(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.remove(), bad ? 9000 : 3500);
}

function showLogin(message = "") {
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-msg").textContent = message;
}

function sheet(html) {
  $("#overlay").innerHTML = `<div class="sheet-back"><div class="sheet" role="dialog" aria-modal="true">${html}</div></div>`;
  const back = $(".sheet-back");
  back.addEventListener("click", (e) => { if (e.target === back) closeSheet(); });
  return $(".sheet");
}
const closeSheet = () => { $("#overlay").innerHTML = ""; };

async function busy(button, work) {
  const label = button.textContent;
  button.disabled = true;
  try { return await work(); }
  catch (err) { toast(err.message, true); return undefined; }
  finally { button.disabled = false; button.textContent = label; }
}

// --------------------------------------------------------------------- state

const slug = () => $("#campaign").value;
const file = (path) => STATE.files.find((f) => f.path === path);
const cpath = (name) => `campaigns/${slug()}/${name}`;
const ctext = (name) => (file(cpath(name)) || {}).text || "";
const conf = () => yaml(ctext("config.yaml"));
const accounts = () => (yaml((file("accounts.yaml") || {}).text).accounts || []).filter((a) => a.enabled !== false);
const creatives = () => {
  const list = conf().creatives;
  return Array.isArray(list) && list.length ? list : [{ name: "default" }];
};
const isMusic = () => Number((conf().composition || {}).clip_volume ?? 1) === 0;
const setWord = () => (isMusic() ? "song" : "set");
const tagFor = (c) => c.assets_release || conf().assets_release || `assets-${slug()}`;

async function commit(files, message, extra = {}) {
  const payload = files.map((f) => ({ path: f.path, text: f.text, sha: (file(f.path) || {}).sha || "" }));
  const res = await api("commit", { method: "POST", body: { files: payload, message, ...extra } });
  for (const saved of res.files) {
    const existing = file(saved.path);
    if (existing) Object.assign(existing, saved); else STATE.files.push(saved);
  }
  return res;
}

// The campaign's own library: the videos every song that shares the pool cuts from.
const poolTag = () => conf().assets_release || `assets-${slug()}`;
const videoTagFor = (c) => (c.shared_videos ? poolTag() : tagFor(c));

async function tagAssets(tag, fresh = false) {
  if (fresh) ASSETS.delete(tag);
  if (!ASSETS.has(tag)) {
    const get = async (t) => { try { return (await api(`assets?tag=${encodeURIComponent(t)}`)).assets; } catch { return []; } };
    const inbox = `inbox-${tag.slice(7)}`;
    const [library, held] = await Promise.all([get(tag), get(inbox)]);
    ASSETS.set(tag, { library, held: held.map((h) => ({ ...h, inbox })) });
  }
  return ASSETS.get(tag);
}

// Videos from wherever this song's videos live, music from its own library.
// `waiting` are uploads not yet checked; `refused` are ones the check turned down.
async function assetsFor(creative, fresh = false) {
  const ownTag = tagFor(creative);
  const videoTag = videoTagFor(creative);
  const own = await tagAssets(ownTag, fresh);
  const pool = videoTag === ownTag ? own : await tagAssets(videoTag, fresh);
  const by = (lib, prefix) => lib.library.filter((a) => a.name.toLowerCase().startsWith(prefix)).sort((x, y) => x.name.localeCompare(y.name));
  const held = [
    ...pool.held.filter((h) => /^(rejected__)?(hook|body)__/.test(h.name)),
    ...own.held.filter((h) => /^(rejected__)?music__/.test(h.name)),
  ];
  const hooks = by(pool, "hook");
  const bodies = by(pool, "body");
  return { hooks, bodies, clips: [...hooks, ...bodies], music: by(own, "music"),
    waiting: held.filter((h) => !h.name.startsWith("rejected__")),
    refused: held.filter((h) => h.name.startsWith("rejected__")) };
}

// "hook__1a2b3c4d__my clip.mp4" -> "my clip.mp4"
const droppedName = (name) => name.replace(/^rejected__/, "").replace(/^(hook|body|music)__[0-9a-f]{8}__/, "");

const roster = () => { try { return JSON.parse(ctext("clips.json") || "{}").disabled || []; } catch { return []; } };

// One file at a time, so a phone on a weak connection is not juggling five
// uploads, and each gets a real progress bar.
function sendFile(tag, kind, f, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/upload?tag=${encodeURIComponent(tag)}&kind=${kind}&name=${encodeURIComponent(f.name)}`);
    xhr.setRequestHeader("x-ugc", "1");
    xhr.setRequestHeader("content-type", "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText); } catch { /* handled below */ }
      if (xhr.status === 200) resolve(data);
      else reject(new Error(data.error || `${f.name} could not be uploaded (${xhr.status}).`));
    };
    xhr.onerror = () => reject(new Error(`${f.name} could not be uploaded. Check your connection.`));
    xhr.send(f);
  });
}

async function load() {
  try { STATE = await api("state"); }
  catch (err) { showLogin(err.message === "Sign in to continue." ? "" : err.message); return; }
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  const picked = slug() || localStorage.getItem("campaign") || "";
  $("#campaign").innerHTML = STATE.campaigns.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")
    + `<option value="+">New campaign…</option>`;
  if (STATE.campaigns.includes(picked)) $("#campaign").value = picked;
  $("#tabs").innerHTML = TABS.map((t) => `<button type="button" data-tab="${t}">${ICON[t]}<span>${t}</span></button>`).join("");
  render();
}

function mode() {
  const posting = conf().posting || {};
  if (posting.paused) return { key: "paused", label: "Paused", dot: "hold" };
  if (posting.dry_run) return { key: "test", label: "Test mode", dot: "standby" };
  return { key: "live", label: "Live", dot: "go" };
}

function render() {
  if ($("#campaign").value === "+") { viewNewCampaign(); return; }
  try { localStorage.setItem("campaign", slug()); } catch { /* private mode */ }
  const m = mode();
  $("#mode .dot").className = `dot ${m.dot}`;
  $("#mode-label").textContent = m.label;
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === TAB));
  window.scrollTo(0, 0);
  ({ Schedule: viewSchedule, Content: viewContent, Plan: viewPlan, Setup: viewSetup, Jobs: viewJobs })[TAB]();
}

const head = (title, sub, action = "") =>
  `<div class="page-head"><div class="grow"><h2>${esc(title)}</h2>${sub ? `<p>${sub}</p>` : ""}</div>${action}</div>`;

// -------------------------------------------------------------- on/off sheet

function openMode() {
  if ($("#campaign").value === "+") return;
  const now = mode().key;
  const el = sheet(`<h2>Is ${esc(slug())} posting?</h2><div class="stack" style="margin-top:16px">
    ${[
      ["paused", "hold", "Paused", "Nothing is made and nothing is sent. Posts already sitting in Buffer still go out."],
      ["test", "standby", "Test mode", "Videos are made so you can watch them, but nothing is sent to your accounts."],
      ["live", "go", "Live", "Videos are made and posted to your accounts for real."],
    ].map(([key, dot, name, text]) => `<button type="button" class="choice ${key === now ? "on" : ""}" data-mode="${key}">
      <span class="dot ${dot}"></span><span><b>${name}</b><span>${text}</span></span></button>`).join("")}
    <button type="button" class="btn quiet" data-close>Cancel</button></div>`);
  $("[data-close]", el).addEventListener("click", closeSheet);
  $$("[data-mode]", el).forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const key = b.dataset.mode;
    if (key === now) { closeSheet(); return; }
    if (key === "live" && !confirm(`Go live? ${slug()} will start posting to your accounts.`)) return;
    let text = ctext("config.yaml");
    text = setScalar(text, ["posting", "paused"], key === "paused");
    text = setScalar(text, ["posting", "dry_run"], key !== "live");
    await commit([{ path: cpath("config.yaml"), text }], `${slug()} → ${key}`);
    closeSheet();
    render();
    toast({ paused: "Paused.", test: "Test mode on.", live: "Live. The next render and push will post." }[key]);
  })));
}

// ------------------------------------------------------------------ schedule

function viewSchedule() {
  let items = [];
  try { items = JSON.parse(ctext("queue.json") || "{}").items || []; } catch { /* shown as empty */ }
  items.sort((a, b) => String(a.scheduled_for).localeCompare(String(b.scheduled_for)));
  const tz = conf().timezone || undefined;
  const fmt = (iso, opts) => { try { return new Date(iso).toLocaleString("en-US", { timeZone: tz, ...opts }); } catch { return ""; } };
  const light = (s) => ({ pushed: "go", pending: "standby", claimed: "standby", failed: "hold", cancelled: "" }[s] ?? "");
  const word = (s) => ({ pushed: "In Buffer", pending: "Waiting", claimed: "Sending", failed: "Failed", cancelled: "Pulled" }[s] || s);

  let lastDay = "";
  const rows = items.map((i) => {
    const day = fmt(i.scheduled_for, { weekday: "long", month: "long", day: "numeric" });
    const dayHead = day !== lastDay ? `<div class="day">${esc(day)}</div>` : "";
    lastDay = day;
    const [clock, ampm] = fmt(i.scheduled_for, { hour: "numeric", minute: "2-digit" }).split(" ");
    const parts = i.parts || {};
    const clips = [parts.hook, ...(parts.bodies || "").split(",")].filter(Boolean).join(" + ");
    const music = parts.music ? `${parts.music} from ${parts.music_offset_sec || 0}s` : "no music";
    const where = (i.posts || []).map((p) => `<span class="tag ${light(p.status)}">${esc(p.account)} · ${esc(word(p.status))}</span>`).join("")
      || (i.accounts ? i.accounts.map((a) => `<span class="tag">${esc(a)}</span>`).join("") : "");
    const versions = Object.entries(i.variants || {}).map(([name, v]) => `<div class="version">
        <div class="row"><b class="grow">${esc(name)}</b>
          ${v.video_url ? `<button type="button" class="btn compact" data-watch="${esc(v.video_url)}">Watch</button>` : ""}
          <button type="button" class="btn compact danger" data-pull="${esc(i.id)}" data-account="${esc(name)}">Pull</button></div>
        ${v.overlay ? `<div class="small">“${esc(v.overlay)}”</div>` : ""}
        <div class="small muted">${esc((v.parts || {}).hook || "")}${(v.parts || {}).music ? `, song from ${esc(v.parts.music_offset_sec)}s` : ""}</div>
        ${v.caption ? `<div class="caption small">${esc(v.caption)}</div>` : ""}
      </div>`).join("");
    return `${dayHead}<article class="slot">
      <div><div class="time">${esc(clock)}<small>${esc(ampm || "")}</small></div>
        <div class="state"><span class="dot ${light(i.status)}"></span>${esc(word(i.status))}</div></div>
      <div style="min-width:0">
        ${i.overlay ? `<div class="onscreen">“${esc(i.overlay)}”</div>` : ""}
        <div class="what">${esc(i.creative)}${i.lineup_id ? ", hand-picked" : ""} · ${esc(clips)} · ${esc(music)}</div>
        <div class="where">${where}</div>
        <details><summary>${versions ? `Caption and ${Object.keys(i.variants).length} versions` : "Caption"}</summary>
          ${versions || `<div class="caption">${esc(i.caption)}</div>`}
          ${i.first_comment ? `<p class="small muted" style="margin-top:8px">First comment: ${esc(i.first_comment)}</p>` : ""}
        </details>
        <div class="row" style="margin-top:12px">
          ${i.video_url ? `<button type="button" class="btn compact" data-watch="${esc(i.video_url)}">Watch</button>` : ""}
          <button type="button" class="btn compact danger" data-pull="${esc(i.id)}">Pull everywhere</button>
        </div>
      </div></article>`;
  }).join("");

  const live = mode().key === "live";
  $("#view").innerHTML = head("Schedule", `${items.length ? `${items.length} video${items.length === 1 ? "" : "s"} lined up` : "Nothing lined up"} for ${esc(slug())}.`,
    `<button type="button" class="btn compact" data-reload>Refresh</button>`)
    + (live ? "" : `<section class="panel" id="steps"><h3>Getting ${esc(slug())} ready</h3><div data-steps class="muted small" style="margin-top:8px">Checking…</div></section>`)
    + (rows || (live ? `<div class="panel empty"><b>Nothing is scheduled</b>The next batch is made overnight. To make it now, open Jobs and tap “Make videos now”.</div>` : ""));
  if (!live) checklist(items.length);

  $("[data-reload]").addEventListener("click", (e) => busy(e.target, load));
  $$("[data-watch]").forEach((b) => b.addEventListener("click", () => {
    const next = b.closest(".row").nextElementSibling;
    if (next && next.tagName === "VIDEO") { next.remove(); return; }
    const v = document.createElement("video");
    v.controls = true; v.playsInline = true; v.autoplay = true; v.src = b.dataset.watch;
    b.closest(".row").after(v);
  }));
  $$("[data-pull]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const account = b.dataset.account || "";
    if (!confirm(`Pull this video${account ? ` from ${account}` : " from every account"}? It is removed from the schedule and from Buffer.`)) return;
    await api("run", { method: "POST", body: { workflow: "queue", inputs: { campaign: slug(), discard: "all", video_id: b.dataset.pull, account } } });
    toast("Pulling. Refresh in about a minute to see it gone.");
  })));
}

// What stands between a campaign and its first post, in order, each with the
// one button that deals with it.
async function checklist(queued) {
  const here = slug();
  const libs = await Promise.all(creatives().map((c) => assetsFor(c)));
  const el = $("[data-steps]");
  if (!el || slug() !== here || TAB !== "Schedule") return;
  const config = conf();
  const music = isMusic();
  const videos = libs.reduce((n, l) => n + l.hooks.length, 0);
  const tracks = libs.reduce((n, l) => n + l.music.length, 0);
  const waiting = libs.reduce((n, l) => n + l.waiting.length, 0);
  const captions = creatives().reduce((n, c) => n + parseBank((file(bankPathFor(c)) || {}).text || "").records.length, 0);
  const link = (config.funnel || {}).link || creatives().some((c) => c.link);
  const m = mode().key;
  const steps = [
    [videos > 0, "Add your videos", videos ? `${videos} added` : waiting ? "Being checked…" : "Drop in the clips to post", "Content", "Add videos"],
    ...(music ? [[tracks > 0, "Add your song clips", tracks ? `${tracks} added` : waiting ? "Being checked…" : "The audio that plays over them", "Content", "Add song clips"]] : []),
    [captions > 0, "Write captions", captions ? `${captions} written` : "The words on the video and under it", "Content", "Write captions"],
    [Boolean(link), "Add your link", link ? "Set" : "Where every post sends people", "Setup", "Add link"],
    [m !== "paused", "Switch to Test mode", m !== "paused" ? "On" : "Makes videos without posting them", "mode", "Switch on"],
    [queued > 0, "Make test videos and watch them", queued ? `${queued} made — they're below` : "See exactly what would go out", "render", "Make videos"],
    [false, "Go live", "Start posting for real", "mode", "Go live"],
  ];
  const next = steps.findIndex(([done]) => !done);
  el.className = "";
  el.innerHTML = steps.map(([done, title, text, go, label], i) => `<div class="step ${done ? "done" : ""} ${i === next ? "next" : ""}">
      <span class="mark">${done ? "✓" : i + 1}</span>
      <span class="grow"><b>${title}</b><span>${esc(text)}</span></span>
      ${i === next ? `<button type="button" class="btn primary compact" data-go="${go}">${label}</button>` : ""}</div>`).join("");
  const btn = $("[data-go]", el);
  if (btn) btn.addEventListener("click", () => busy(btn, async () => {
    const go = btn.dataset.go;
    if (go === "mode") { openMode(); return; }
    if (go === "render") {
      await api("run", { method: "POST", body: { workflow: "render", inputs: { campaign: here, dry_run: "true" } } });
      toast("Making them now. Tap Refresh in about five minutes.");
      return;
    }
    TAB = go; render();
  }));
}

// ------------------------------------------------------------------- content

function creativesBlock(list) {
  const lines = ["creatives:"];
  for (const c of list) {
    lines.push(`  - name: ${c.name}`);
    if (c.title) lines.push(`    title: ${yamlString(c.title)}`);
    if (c.link) lines.push(`    link: ${yamlString(c.link)}`);
    if (c.weight && Number(c.weight) !== 1) lines.push(`    weight: ${Number(c.weight)}`);
    if (c.assets_release) lines.push(`    assets_release: ${c.assets_release}`);
    if (c.shared_videos) lines.push("    shared_videos: true");
    const cues = Object.entries(c.music_cues || {}).filter(([, v]) => Array.isArray(v) && v.length);
    if (cues.length) {
      lines.push("    music_cues:");
      for (const [track, at] of cues) lines.push(`      ${yamlString(track)}: [${at.join(", ")}]`);
    }
    if ((c.accounts || []).length) {
      lines.push("    accounts:");
      for (const a of c.accounts) lines.push(`      - ${a}`);
    }
  }
  return lines.join("\n");
}

function bankPathFor(creative) {
  const own = cpath(`creatives/${creative.name}/captions.txt`);
  return file(own) ? own : cpath("captions.txt");
}

let SET = 0;          // which song/set the Content tab is showing
let watchTimer = 0;

const ZONES = {
  hook: { accept: ".mp4,.mov,.m4v,.webm,video/*", exts: [".mp4", ".mov", ".m4v", ".webm"] },
  body: { accept: ".mp4,.mov,.m4v,.webm,video/*", exts: [".mp4", ".mov", ".m4v", ".webm"] },
  music: { accept: ".mp3,.m4a,.wav,audio/*", exts: [".mp3", ".m4a", ".wav"] },
};

// When this page last started the upload check for a song, and how often,
// so a check that never ran is retried a couple of times and then reported.
const KICKS = new Map();

async function startCheck(c) {
  const k = KICKS.get(c.name) || { count: 0, at: 0 };
  KICKS.set(c.name, { count: k.count + 1, at: Date.now() });
  await api("run", { method: "POST", body: { workflow: "ingest", inputs: { campaign: slug(), creative: c.name } } });
}

// What to tell someone whose uploads are still waiting, and whether to act.
async function checkProgress(c, manual = false) {
  let last = null;
  try { last = (await api("runs?workflow=ingest")).runs[0] || null; } catch { /* say what we can */ }
  const k = KICKS.get(c.name) || { count: 0, at: 0 };
  const justStarted = Date.now() - k.at < 90000;
  if ((last && last.status !== "completed") || (justStarted && !manual)) return { state: "checking" };
  if (manual || k.count < 2) {
    try { await startCheck(c); return { state: "checking" }; }
    catch (err) { return { state: "stuck", why: `The check couldn't start: ${err.message}`, url: last && last.url }; }
  }
  const failed = last && last.conclusion !== "success";
  return { state: "stuck", url: last && last.url,
    why: failed ? "The check stopped before it finished." : "The check ran but left these behind." };
}

function viewContent() {
  clearTimeout(watchTimer);
  const word = setWord();
  const sets = creatives();
  if (SET >= sets.length) SET = 0;
  const c = sets[SET];
  const music = isMusic();
  const shared = Boolean(c.shared_videos);
  const twoClips = Number((conf().composition || {}).bodies_per_video ?? 1) > 0;
  const bank = parseBank((file(bankPathFor(c)) || {}).text || "");
  const ownBank = bankPathFor(c) !== cpath("captions.txt");
  const off = roster();
  const label = c.title || c.name;

  const zone = (kind, title, help) => `<section class="panel" data-zone="${kind}">
      <div class="row"><h3 class="grow">${title}</h3><span class="tag" data-count></span></div>
      <p class="muted small" style="margin:2px 0 12px">${help}</p>
      <label class="drop" tabindex="0">
        <input type="file" multiple accept="${ZONES[kind].accept}" hidden>
        <b>Drop files here</b><span>or tap to choose them</span>
      </label>
      <div class="uploads"></div>
      <div class="files" data-files><p class="muted small">Looking…</p></div>
    </section>`;

  const videos = twoClips
    ? zone("hook", "Opening clips", `The first thing people see. One is picked to start each video.${shared ? ` Every ${word} uses these.` : ""}`)
      + zone("body", "Second clips", "What each video cuts to after the opening.")
    : zone("hook", "Videos", shared
      ? `One shared pool. Every ${word} picks its videos from here, so a clip you add works with all of them.`
      : "Every video you drop here goes into the pool. One is picked for each post.");
  const chips = `<div class="chips" role="tablist">${sets.map((x, i) => `<button type="button" class="chip ${i === SET ? "on" : ""}" data-set="${i}">${esc(x.title || x.name)}</button>`).join("")}
        <button type="button" class="chip add" data-add>+ Add a ${word}</button></div>`;

  $("#view").innerHTML = head("Content", shared
      ? `What ${esc(slug())} posts. Each video is one clip from the pool with one ${word} over it and one of that ${word}'s captions.`
      : `What ${esc(slug())} posts. Add as many as you like; each video is built from a random pick.`)
    + (shared ? videos + `<h3 style="margin:22px 0 8px">${music ? "Songs" : "Sets"}</h3>` + chips : chips + videos)
    + zone("music", music ? (shared ? `Audio for ${esc(label)}` : "Song clips") : "Music",
      music ? (shared ? "The part of the song that plays. Add more than one cut and each post picks one." : "The audio that plays over the videos. One is picked for each post.")
        : "Plays quietly under the clips. Optional.")
    + `<section class="panel"><div class="row"><h3 class="grow">${shared || ownBank ? `Captions for ${esc(label)}` : "Captions"}</h3><span class="tag">${bank.records.length} written</span></div>
        <p class="muted small" style="margin:2px 0 12px">The words on the video and under it. ${ownBank ? `Only ever posted with this ${word}.` : "One is picked for each post."}</p>
        <button type="button" class="btn" data-captions>Write captions</button></section>
      <section class="panel"><div class="row"><h3 class="grow">${esc(label)}</h3>
          ${Number(c.weight || 1) !== 1 ? `<span class="tag">posts ${Number(c.weight)}× as often</span>` : ""}</div>
        <p class="muted small" style="margin:2px 0 12px">${(c.accounts || []).length ? `Posts to ${esc(c.accounts.join(", "))}.` : "Posts to every account."}
          ${c.link ? ` Sends people to ${esc(c.link)}.` : ""}</p>
        <button type="button" class="btn" data-edit>Name, link, accounts and start points</button></section>`;

  $$("[data-set]").forEach((b) => b.addEventListener("click", () => { SET = Number(b.dataset.set); viewContent(); }));
  $("[data-add]").addEventListener("click", () => editCreative(-1));
  $("[data-edit]").addEventListener("click", () => editCreative(SET));
  $("[data-captions]").addEventListener("click", () => editCaptions(c));

  const fill = async (fresh = false, manual = false) => {
    const lib = await assetsFor(c, fresh);
    const progress = lib.waiting.length ? await checkProgress(c, manual) : null;
    if (TAB !== "Content" || creatives()[SET]?.name !== c.name) return lib;
    for (const [kind, list] of [["hook", lib.hooks], ["body", lib.bodies], ["music", lib.music]]) {
      const el = $(`[data-zone="${kind}"]`);
      if (!el) continue;
      const waiting = lib.waiting.filter((w) => w.name.startsWith(`${kind}__`));
      const refused = lib.refused.filter((w) => w.name.startsWith(`rejected__${kind}__`));
      const many = waiting.length !== 1;
      $("[data-count]", el).textContent = `${list.length} added`;
      $("[data-files]", el).innerHTML = (waiting.length ? (progress.state === "checking"
          ? `<p class="note">${waiting.length} file${many ? "s are" : " is"} being checked. ${many ? "They appear" : "It appears"} below in a minute or two.</p>`
          : `<div class="note bad"><b>${waiting.length} file${many ? "s are" : " is"} uploaded but not added yet.</b> ${esc(progress.why)}
              <div class="row" style="margin-top:8px"><button type="button" class="btn compact" data-recheck>Check again</button>
              ${progress.url ? `<a href="${esc(progress.url)}" target="_blank" rel="noopener">What went wrong</a>` : ""}</div></div>`) : "")
        + refused.map((r) => `<div class="file refused">
            <span class="grow name">${esc(droppedName(r.name))}<small>Not added. ${esc(r.note || "The check couldn't use this file.")}</small></span>
            <button type="button" class="btn compact" data-discard="${esc(r.name)}" data-inbox="${esc(r.inbox)}">Clear</button></div>`).join("")
        + (list.length ? list.map((a) => {
          const isOff = off.includes(a.name);
          return `<div class="file ${isOff ? "off" : ""}">
            <button type="button" class="play" data-play="${esc(a.url)}" data-audio="${kind === "music" ? 1 : ""}" aria-label="Play ${esc(a.name)}">▶</button>
            <span class="grow name">${esc(a.name)}<small>${isOff ? "Not being used" : `${(a.size / 1048576).toFixed(1)} MB`}</small></span>
            <button type="button" class="btn compact" data-toggle="${esc(a.name)}">${isOff ? "Use it" : "Stop using"}</button></div>`;
        }).join("") : waiting.length || refused.length ? "" : `<p class="muted small">Nothing here yet.</p>`);
    }
    $$("[data-recheck]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      await fill(true, true);
      toast("Checking again.");
    })));
    $$("[data-discard]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      await api("discard", { method: "POST", body: { tag: b.dataset.inbox, name: b.dataset.discard } });
      await fill(true);
    })));
    $$("[data-play]").forEach((b) => b.addEventListener("click", () => {
      const row = b.closest(".file");
      const open = row.nextElementSibling;
      if (open && open.classList.contains("player")) { open.remove(); return; }
      const media = document.createElement(b.dataset.audio ? "audio" : "video");
      media.className = "player"; media.controls = true; media.autoplay = true; media.playsInline = true; media.src = b.dataset.play;
      row.after(media);
    }));
    $$("[data-toggle]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const name = b.dataset.toggle;
      const next = roster().includes(name) ? roster().filter((n) => n !== name) : [...roster(), name].sort();
      await commit([{ path: cpath("clips.json"), text: `${JSON.stringify({ disabled: next }, null, 2)}\n` }], `${next.includes(name) ? "stop using" : "use"} ${name}`);
      viewContent();
    })));
    // Keep looking while something is still being checked.
    clearTimeout(watchTimer);
    if (lib.waiting.length && progress.state === "checking") watchTimer = setTimeout(() => fill(true), 20000);
    return lib;
  };
  fill();

  $$("[data-zone]").forEach((el) => {
    const kind = el.dataset.zone;
    const drop = $(".drop", el);
    const input = $("input", drop);
    const take = async (picked) => {
      const files = [...picked];
      if (!files.length) return;
      const bad = files.filter((f) => !ZONES[kind].exts.some((x) => f.name.toLowerCase().endsWith(x)));
      const big = files.filter((f) => f.size > 95 * 1024 * 1024);
      const good = files.filter((f) => !bad.includes(f) && !big.includes(f));
      const list = $(".uploads", el);
      const problems = [
        ...bad.map((f) => `${f.name} isn't a ${kind === "music" ? "song" : "video"} file this can use (${ZONES[kind].exts.join(", ")}).`),
        ...big.map((f) => `${f.name} is over 95 MB. Export it smaller.`),
      ];
      list.innerHTML = problems.map((t) => `<p class="small" style="color:var(--hold)">${esc(t)}</p>`).join("")
        + good.map((f, i) => `<div class="upload" data-u="${i}"><span class="grow name">${esc(f.name)}</span><span class="pct">Waiting</span><i></i></div>`).join("");
      let sent = 0;
      const dest = kind === "music" ? tagFor(c) : videoTagFor(c);
      for (const [i, f] of good.entries()) {
        const row = $(`[data-u="${i}"]`, list);
        try {
          await sendFile(dest, kind, f, (p) => { $(".pct", row).textContent = `${Math.round(p * 100)}%`; $("i", row).style.width = `${p * 100}%`; });
          $(".pct", row).textContent = "Uploaded"; $("i", row).style.width = "100%"; row.classList.add("done");
          sent += 1;
        } catch (err) { $(".pct", row).textContent = "Failed"; row.classList.add("failed"); toast(err.message, true); }
      }
      input.value = "";
      if (!sent) return;
      try {
        KICKS.delete(c.name);
        await startCheck(c);
        toast(`${sent} file${sent === 1 ? "" : "s"} uploaded. Checking ${sent === 1 ? "it" : "them"} now — about two minutes.`);
      } catch (err) { KICKS.delete(c.name); toast(`Uploaded, but the check didn't start: ${err.message}`, true); }
      setTimeout(() => { list.innerHTML = ""; fill(true); }, 2500);
    };
    input.addEventListener("change", () => take(input.files));
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
    ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
    drop.addEventListener("drop", (e) => take(e.dataTransfer.files));
  });
}

async function editCreative(index) {
  const list = creatives().map((c) => ({ ...c }));
  const isNew = index < 0;
  const c = isNew ? { name: "", title: "", link: "", weight: 1, music_cues: {}, accounts: [] } : list[index];
  const word = setWord();
  const { music } = isNew ? { music: [] } : await assetsFor(c);
  const tracks = [...new Set([...music.map((m) => m.name), ...Object.keys(c.music_cues || {})])];
  const el = sheet(`<h2>${isNew ? `Add a ${word}` : esc(c.title || c.name)}</h2><form class="stack" style="margin-top:14px">
    <label class="field"><span class="label">${isMusic() ? "Song title" : "Name"}</span>
      <input type="text" name="title" value="${esc(c.title || (isNew ? "" : c.name))}" required>
      <span class="help">Shown in captions wherever you write {name}.</span></label>
    <label class="field"><span class="label">Link</span>
      <input type="url" name="link" value="${esc(c.link || "")}" placeholder="https://">
      <span class="help">Where this one sends people. Leave empty to use the campaign's link.</span></label>
    <label class="field"><span class="label">How often it posts</span>
      <select name="weight">${[[0.5, "Half as often"], [1, "Normal"], [2, "Twice as often"], [3, "Three times as often"]]
        .map(([v, l]) => `<option value="${v}" ${Number(c.weight || 1) === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
    ${tracks.map((t) => `<label class="field"><span class="label">Start points in ${esc(t)}</span>
      <input type="text" name="cue:${esc(t)}" value="${esc((c.music_cues?.[t] || []).join(", "))}" placeholder="42.5, 73" inputmode="decimal">
      <span class="help">Seconds into the track, separated by commas. Leave empty to start anywhere.</span></label>`).join("")}
    ${isNew ? "" : tracks.length ? "" : `<p class="note">Upload this ${word}'s track to choose exactly where it starts.</p>`}
    <div><span class="label" style="font-weight:550">Post it to</span>
      ${accounts().map((a) => `<label class="check"><input type="checkbox" name="account" value="${esc(a.name)}" ${!(c.accounts || []).length || c.accounts.includes(a.name) ? "checked" : ""}>
        <span>${esc(a.name)} <span class="muted small">${esc(a.network)}</span></span></label>`).join("")}</div>
    <div class="row" style="justify-content:flex-end">
      ${!isNew && list.length > 1 ? `<button type="button" class="btn danger" data-remove>Remove</button><span class="grow"></span>` : ""}
      <button type="button" class="btn" data-close>Cancel</button>
      <button type="submit" class="btn primary">${isNew ? `Add ${word}` : "Save"}</button></div></form>`);
  $("[data-close]", el).addEventListener("click", closeSheet);

  const save = async (next, message, extraFiles = []) => {
    const text = replaceTop(ctext("config.yaml"), "creatives", creativesBlock(next));
    await commit([{ path: cpath("config.yaml"), text }, ...extraFiles], message);
    closeSheet(); render();
  };
  const remove = $("[data-remove]", el);
  if (remove) remove.addEventListener("click", () => busy(remove, async () => {
    if (!confirm(`Remove ${c.title || c.name}? Its clips and captions stay in the repository; it just stops posting.`)) return;
    SET = 0;
    await save(list.filter((_, i) => i !== index), `remove ${c.name}`);
    toast("Removed.");
  }));
  $("form", el).addEventListener("submit", (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    busy($("button[type=submit]", el), async () => {
      const title = String(form.get("title")).trim();
      const picked = form.getAll("account");
      const everyone = picked.length === accounts().length;
      if (!picked.length) throw new Error("Pick at least one account.");
      const cues = {};
      for (const t of tracks) {
        const nums = String(form.get(`cue:${t}`) || "").split(/[,\s]+/).filter(Boolean).map(Number);
        if (nums.some((n) => !Number.isFinite(n) || n < 0)) throw new Error(`Start points for ${t} must be numbers of seconds.`);
        if (nums.length) cues[t] = nums;
      }
      const updated = { ...c, title, link: String(form.get("link")).trim(), weight: Number(form.get("weight")),
        music_cues: cues, accounts: everyone ? [] : picked };
      const extra = [];
      if (isNew) {
        updated.name = slugify(title);
        if (list.some((x) => x.name === updated.name)) throw new Error(`There is already one called ${updated.name}.`);
        updated.assets_release = `assets-${slug()}-${updated.name}`;
        // A song is a track and its captions over the campaign's shared videos.
        if (isMusic()) {
          updated.shared_videos = true;
          // The starter set only existed to hold the first videos. With no
          // track of its own it cannot post, so the first real song replaces it.
          const starter = list.findIndex((x) => x.name === "default" && !x.assets_release && !x.shared_videos);
          if (starter >= 0 && !(await assetsFor(list[starter])).music.length) list.splice(starter, 1);
        }
        const base = cpath(`creatives/${updated.name}`);
        extra.push({ path: `${base}/captions.txt`, text: `# Captions for ${title}. Only ever posted with this one.\n\noverlay: ${isMusic() ? "this part. | every single time." : "wait for it"}\ntitle: ${title}\n${title}\n` });
        extra.push({ path: `${base}/LICENSES.md`, text: `# Music licences — ${slug()} / ${updated.name}\n\n| file | source | licence |\n|---|---|---|\n` });
        list.push(updated);
      } else list[index] = updated;
      if (isNew) SET = list.length - 1;
      await save(list, `${isNew ? "add" : "update"} ${updated.name}`, extra);
      toast(isNew ? (updated.shared_videos ? "Added. Drop in its audio and write its captions." : "Added. Drop in its videos and song clips.") : "Saved.");
    });
  });
}

function editCaptions(creative) {
  const own = cpath(`creatives/${creative.name}/captions.txt`);
  const path = bankPathFor(creative);
  const shared = path !== own;
  const bank = parseBank((file(path) || {}).text || "");
  const draw = () => {
    $("#view").innerHTML = head(`Captions for ${creative.title || creative.name}`,
      shared ? "These are shared by everything in this campaign without captions of its own." : "One is picked for each post.",
      `<button type="button" class="btn compact" data-back>Back</button>`)
      + bank.records.map((r, i) => `<div class="record stack" data-i="${i}">
          <label class="field"><span class="label">On the video</span>
            <input type="text" data-k="overlay" value="${esc(r.overlay)}" placeholder="Nothing drawn on the video">
            <span class="help">Use | to break the line. No emoji.</span></label>
          <label class="field"><span class="label">Caption</span><textarea data-k="body">${esc(r.body)}</textarea></label>
          <label class="field"><span class="label">YouTube title</span>
            <input type="text" data-k="title" value="${esc(r.title)}" maxlength="100" placeholder="Uses the caption's first line"></label>
          <div class="row" style="justify-content:flex-end"><button type="button" class="btn compact danger" data-del="${i}">Delete</button></div>
        </div>`).join("")
      + `<div class="row" style="margin-top:12px"><button type="button" class="btn" data-more>Add a caption</button>
          ${shared ? `<button type="button" class="btn quiet" data-own>Give ${esc(creative.title || creative.name)} its own captions</button>` : ""}</div>
        <div class="savebar"><button type="button" class="btn primary" data-save>Save captions</button></div>`;
    const sync = () => $$(".record").forEach((el) => {
      const r = bank.records[Number(el.dataset.i)];
      $$("[data-k]", el).forEach((input) => { r[input.dataset.k] = input.value; });
    });
    $("[data-back]").addEventListener("click", () => render());
    $("[data-more]").addEventListener("click", () => { sync(); bank.records.push({ overlay: "", title: "", body: "" }); draw(); $$(".record").pop().scrollIntoView({ behavior: "smooth" }); });
    $$("[data-del]").forEach((b) => b.addEventListener("click", () => { sync(); bank.records.splice(Number(b.dataset.del), 1); draw(); }));
    const ownBtn = $("[data-own]");
    if (ownBtn) ownBtn.addEventListener("click", () => busy(ownBtn, async () => {
      sync();
      await commit([{ path: own, text: serializeBank(bank) }], `own captions for ${creative.name}`);
      toast("Done. These captions now belong to it alone.");
      editCaptions(creative);
    }));
    $("[data-save]").addEventListener("click", (e) => busy(e.target, async () => {
      sync();
      if (!bank.records.some((r) => r.body.trim())) throw new Error("Write at least one caption.");
      await commit([{ path, text: serializeBank(bank) }], `captions for ${creative.name}`);
      toast("Captions saved.");
    }));
  };
  draw();
}

// ---------------------------------------------------------------------- plan

function viewPlan() {
  const header = (ctext("lineup.yaml").match(/^(#.*\n)+/) || ["# Hand-picked posts. Each one is posted exactly once.\n"])[0];
  const posts = (yaml(ctext("lineup.yaml")).posts || []).map((p) => ({ ...p }));
  const word = setWord();

  const draw = async () => {
    const libs = {};
    for (const c of creatives()) libs[c.name] = await assetsFor(c);
    const pick = (name, value, options, empty) => `<select data-k="${name}">
      ${empty ? `<option value="">${empty}</option>` : ""}
      ${[...new Set([...options, value].filter(Boolean))].map((o) => `<option ${o === value ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
    $("#view").innerHTML = head("Plan", "Posts you spell out yourself. They go out before anything picked automatically.",
      `<button type="button" class="btn primary compact" data-add>Add a post</button>`)
      + (posts.length ? "" : `<div class="panel empty"><b>No hand-picked posts</b>Everything is being picked automatically. Add a post to choose the exact clip, moment, words and time.</div>`)
      + posts.map((p, i) => {
        const lib = libs[p.creative || creatives()[0].name] || { clips: [], music: [] };
        return `<details class="group" data-i="${i}" ${p._open ? "open" : ""}>
          <summary><b>${esc(p.overlay || String(p.caption || "").split("\n")[0] || "New post")}</b><span>${p.skip ? "held" : p.at ? esc(String(p.at).replace("T", " ")) : "next free slot"}</span></summary>
          <div class="body stack">
            <div class="grid2">
              <label class="field"><span class="label">Which ${word}</span>${pick("creative", p.creative || creatives()[0].name, creatives().map((c) => c.name))}</label>
              <label class="field"><span class="label">Clip</span>${lib.clips.length
                ? pick("hook", p.hook, lib.clips.map((a) => a.name), "Choose a clip")
                : `<input type="text" data-k="hook" value="${esc(p.hook || "")}" placeholder="hook_01.mp4">`}</label>
              <label class="field"><span class="label">Track</span>${lib.music.length
                ? pick("music", p.music, lib.music.map((a) => a.name), "No music")
                : `<input type="text" data-k="music" value="${esc(p.music || "")}" placeholder="music_01.mp3">`}</label>
              <label class="field"><span class="label">Start the track at (seconds)</span>
                <input type="number" data-k="music_start" value="${esc(p.music_start ?? 0)}" min="0" step="0.1" inputmode="decimal"></label>
            </div>
            <label class="field"><span class="label">On the video</span>
              <input type="text" data-k="overlay" value="${esc(p.overlay || "")}"><span class="help">Use | to break the line.</span></label>
            <label class="field"><span class="label">Caption</span><textarea data-k="caption">${esc(p.caption || "")}</textarea></label>
            <label class="field"><span class="label">When</span>
              <input type="datetime-local" data-k="at" value="${esc(p.at ? String(p.at).replace(" ", "T").slice(0, 16) : "")}">
              <span class="help">In ${esc(conf().timezone || "the campaign's time zone")}. Leave empty for the next free slot.</span></label>
            <div><span class="label" style="font-weight:550">Post it to</span>
              ${accounts().map((a) => `<label class="check"><input type="checkbox" data-account value="${esc(a.name)}" ${!(p.accounts || []).length || p.accounts.includes(a.name) ? "checked" : ""}><span>${esc(a.name)}</span></label>`).join("")}</div>
            <label class="check"><input type="checkbox" data-k="funnel" ${p.funnel === false ? "" : "checked"}><span>Add the campaign's closing line, first comment and end card</span></label>
            <label class="check"><input type="checkbox" data-k="skip" ${p.skip ? "checked" : ""}><span>Hold this post (keep it here, don't send it)</span></label>
            <div class="row" style="justify-content:flex-end"><button type="button" class="btn compact danger" data-del="${i}">Delete</button></div>
          </div></details>`;
      }).join("")
      + `<div class="savebar"><button type="button" class="btn primary" data-save>Save plan</button></div>`;

    const sync = () => $$("details.group").forEach((el) => {
      const p = posts[Number(el.dataset.i)];
      p._open = el.open;
      $$("[data-k]", el).forEach((input) => {
        p[input.dataset.k] = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value || 0) : input.value;
      });
      const picked = $$("[data-account]:checked", el).map((x) => x.value);
      p.accounts = picked.length === accounts().length ? [] : picked;
    });
    $("[data-add]").addEventListener("click", () => {
      sync();
      posts.push({ id: `post-${Date.now().toString(36)}`, creative: creatives()[0].name, hook: "", caption: "", _open: true });
      draw();
    });
    $$("[data-del]").forEach((b) => b.addEventListener("click", () => { sync(); posts.splice(Number(b.dataset.del), 1); draw(); }));
    $$('select[data-k="creative"]').forEach((s) => s.addEventListener("change", () => { sync(); draw(); }));
    $("[data-save]").addEventListener("click", (e) => busy(e.target, async () => {
      sync();
      const clean = posts.map((p) => {
        if (!p.hook) throw new Error(`Choose a clip for “${p.overlay || p.id}”.`);
        if (!String(p.caption || "").trim()) throw new Error(`Write a caption for “${p.overlay || p.id}”.`);
        const out = { id: p.id, creative: p.creative, hook: p.hook };
        if ((p.bodies || []).length) out.bodies = p.bodies;
        if (p.music) { out.music = p.music; out.music_start = Number(p.music_start || 0); }
        if (p.overlay) out.overlay = p.overlay;
        out.caption = String(p.caption).trim();
        if (p.title) out.title = p.title;
        if (p.captions && Object.keys(p.captions).length) out.captions = p.captions;
        if ((p.accounts || []).length) out.accounts = p.accounts;
        if (p.at) out.at = String(p.at);
        if (p.skip) out.skip = true;
        if (p.funnel === false) out.funnel = false;
        return out;
      });
      const text = header + window.jsyaml.dump({ posts: clean }, { lineWidth: -1, schema: window.jsyaml.CORE_SCHEMA });
      await commit([{ path: cpath("lineup.yaml"), text }], `plan for ${slug()}`);
      toast("Plan saved.");
    }));
  };
  draw();
}

// --------------------------------------------------------------------- setup

// Every simple setting: where it lives in the config, how it is shown, and
// what the engine uses when the config says nothing.
const SETTINGS = [
  { group: "When it posts", hint: "How many, and between which hours", fields: [
    { path: ["posting", "posts_per_day"], label: "Posts per day", kind: "number", min: 1, max: 24, fallback: 6 },
    { path: ["posting", "start_hour"], label: "First post of the day", kind: "hour", fallback: 9 },
    { path: ["posting", "end_hour"], label: "Stop posting at", kind: "hour", fallback: 22 },
    { path: ["selection", "auto_fill"], label: "Fill empty slots automatically", kind: "toggle", fallback: true,
      help: "Off means only the posts in Plan go out." },
  ] },
  { group: "Sound and length", hint: "Whose audio you hear", fields: [
    { path: ["composition", "music_volume"], label: "Music volume", kind: "percent", fallback: 0.1 },
    { path: ["composition", "clip_volume"], label: "The clips' own sound", kind: "percent", fallback: 1,
      help: "0% silences the clips, so only the music plays." },
    { path: ["composition", "bodies_per_video"], label: "One clip per video", kind: "flag", on: 0, off: 1, fallback: 1,
      help: "Off cuts from an opening clip to a second one." },
    { path: ["composition", "loop_to_min"], label: "Loop clips shorter than 5 seconds", kind: "toggle", fallback: false },
    { path: ["composition", "music_cleared"], label: "This music is mine to post everywhere", kind: "toggle", fallback: false },
  ] },
  { group: "A different video for each account", hint: "So accounts don't post the same thing", fields: [
    { path: ["variation", "enabled"], label: "Vary the videos", kind: "toggle", fallback: false },
    { path: ["variation", "per_account"], label: "Make a separate version for every account", kind: "toggle", fallback: false,
      help: "The setting that matters. Each account gets a different clip, different words and a different moment of the track, as far as there are spares." },
    { path: ["variation", "per_account_vary"], label: "What differs between accounts", kind: "checks", fallback: ["clip", "caption", "cue"],
      options: [["clip", "The clip"], ["caption", "The words (on screen and caption)"], ["cue", "The moment of the track"]] },
    { path: ["variation", "zoom_max"], label: "Zoom in, up to", kind: "slider", min: 0, max: 0.25, step: 0.01, unit: "%", scale: 100, fallback: 0.05 },
    { path: ["variation", "rotate_max_deg"], label: "Tilt, up to", kind: "slider", min: 0, max: 3, step: 0.1, unit: "°", fallback: 0.5 },
    { path: ["variation", "brightness_max"], label: "Brightness, up to", kind: "slider", min: 0, max: 0.3, step: 0.01, unit: "%", scale: 100, fallback: 0.04 },
    { path: ["variation", "saturation_max"], label: "Colour strength, up to", kind: "slider", min: 0, max: 0.5, step: 0.01, unit: "%", scale: 100, fallback: 0.08 },
    { path: ["variation", "hue_max_deg"], label: "Colour shift, up to", kind: "slider", min: 0, max: 30, step: 1, unit: "°", fallback: 4 },
    { path: ["variation", "grain_max"], label: "Film grain, up to", kind: "slider", min: 0, max: 40, step: 1, unit: "", fallback: 6 },
    { path: ["variation", "trim_start_max_sec"], label: "Trim the start, up to", kind: "slider", min: 0, max: 3, step: 0.1, unit: "s", fallback: 0 },
    { path: ["variation", "overlay_shift_max"], label: "Move the on-screen words, up to", kind: "slider", min: 0, max: 0.2, step: 0.01, unit: "%", scale: 100, fallback: 0 },
  ], note: "The sliders make two files different, not two videos: the platforms compare what a video shows and sounds like, and a zoom or a tint doesn't change that. A separate version per account does." },
  { group: "Where every post sends people", hint: "The link and the ask", fields: [
    { path: ["funnel", "name"], label: "What you're promoting", kind: "text", fallback: "", help: "Used wherever a line says {name}." },
    { path: ["funnel", "link"], label: "Link", kind: "url", fallback: "", help: "Used wherever a line says {link}. Put the same link in each account's bio." },
    { path: ["funnel", "cta"], label: "Closing lines for captions", kind: "lines", fallback: [], help: "One per line. They take turns." },
    { path: ["funnel", "cta_every"], label: "Add a closing line to", kind: "select", fallback: 1,
      options: [[1, "Every post"], [2, "Every other post"], [3, "Every third post"]] },
    { path: ["funnel", "first_comment"], label: "First comment (Instagram)", kind: "lines", fallback: [], help: "One per line." },
    { path: ["funnel", "end_card"], label: "Words on the last seconds of the video", kind: "text", fallback: "", help: "Use | to break the line." },
    { path: ["funnel", "end_card_sec"], label: "Show them for", kind: "slider", min: 0.5, max: 6, step: 0.5, unit: "s", fallback: 2 },
  ] },
];

const dig = (obj, path) => path.reduce((o, k) => (o == null ? undefined : o[k]), obj);
const hourName = (h) => `${((h + 11) % 12) + 1} ${h < 12 ? "am" : "pm"}`;

function fieldHtml(f, value) {
  const id = f.path.join(".");
  const help = f.help ? `<span class="help">${f.help}</span>` : "";
  const wrap = (inner) => `<label class="field"><span class="label">${f.label}</span>${inner}${help}</label>`;
  switch (f.kind) {
    case "toggle":
      return `<label class="check"><input type="checkbox" data-f="${id}" ${value ? "checked" : ""}><span>${f.label}${f.help ? `<span class="muted small" style="display:block">${f.help}</span>` : ""}</span></label>`;
    case "flag":
      return `<label class="check"><input type="checkbox" data-f="${id}" ${Number(value) === f.on ? "checked" : ""}><span>${f.label}${f.help ? `<span class="muted small" style="display:block">${f.help}</span>` : ""}</span></label>`;
    case "number":
      return wrap(`<input type="number" data-f="${id}" value="${esc(value)}" min="${f.min}" max="${f.max}" inputmode="numeric">`);
    case "hour":
      return wrap(`<select data-f="${id}">${[...Array(24).keys()].map((h) => `<option value="${h}" ${Number(value) === h ? "selected" : ""}>${hourName(h)}</option>`).join("")}</select>`);
    case "select":
      return wrap(`<select data-f="${id}">${f.options.map(([v, l]) => `<option value="${v}" ${String(value) === String(v) ? "selected" : ""}>${l}</option>`).join("")}</select>`);
    case "percent":
      return `<label class="field"><span class="label">${f.label}: <output>${Math.round(value * 100)}%</output></span>
        <input type="range" data-f="${id}" min="0" max="100" step="5" value="${Math.round(value * 100)}">${help}</label>`;
    case "slider": {
      const show = (v) => `${+(v * (f.scale || 1)).toFixed(2)}${f.unit}`;
      return `<label class="field"><span class="label">${f.label}: <output data-scale="${f.scale || 1}" data-unit="${f.unit}">${show(value)}</output></span>
        <input type="range" data-f="${id}" min="${f.min}" max="${f.max}" step="${f.step}" value="${value}"></label>`;
    }
    case "checks":
      return `<div><span class="label" style="font-weight:550">${f.label}</span>${f.options.map(([v, l]) =>
        `<label class="check"><input type="checkbox" data-f="${id}" value="${v}" ${(value || []).includes(v) ? "checked" : ""}><span>${l}</span></label>`).join("")}</div>`;
    case "lines":
      return wrap(`<textarea data-f="${id}">${esc((value || []).join("\n"))}</textarea>`);
    default:
      return wrap(`<input type="${f.kind === "url" ? "url" : "text"}" data-f="${id}" value="${esc(value)}">`);
  }
}

function readField(f) {
  const id = f.path.join(".");
  const inputs = $$(`[data-f="${id}"]`);
  const first = inputs[0];
  switch (f.kind) {
    case "toggle": return first.checked;
    case "flag": return first.checked ? f.on : f.off;
    case "number": case "hour": case "slider": return Number(first.value);
    case "select": return Number(first.value);
    case "percent": return Number(first.value) / 100;
    case "checks": return inputs.filter((i) => i.checked).map((i) => i.value);
    case "lines": return first.value.split("\n").map((l) => l.trim()).filter(Boolean);
    default: return first.value.trim();
  }
}

function viewSetup() {
  const config = conf();
  const filter = config.accounts || {};
  const reaches = (name) => (filter.mode === "allow" ? (filter.names || []).includes(name) : !(filter.names || []).includes(name));
  const current = (f) => { const v = dig(config, f.path); return v === undefined || v === null ? f.fallback : v; };

  $("#view").innerHTML = head("Setup", `How ${esc(slug())} runs.`)
    + SETTINGS.map((g, gi) => `<details class="group" ${gi === 0 ? "open" : ""}><summary><b>${g.group}</b><span>${g.hint}</span></summary>
        <div class="body stack">${g.fields.map((f) => fieldHtml(f, current(f))).join("")}${g.note ? `<p class="note">${g.note}</p>` : ""}</div></details>`).join("")
    + `<details class="group"><summary><b>Accounts</b><span>Where this campaign posts</span></summary><div class="body">
        ${accounts().map((a) => `<label class="check"><input type="checkbox" data-reach value="${esc(a.name)}" ${reaches(a.name) ? "checked" : ""}>
          <span>${esc(a.name)} <span class="muted small">${esc(a.network)}</span></span></label>`).join("") || `<p class="muted">No accounts connected.</p>`}
        <p class="note" style="margin-top:8px">To connect another Buffer login, run <b>./ugc connect</b> on your computer. It needs the Buffer key, which never comes near this page.</p></div></details>
      <details class="group" id="advanced"><summary><b>Everything else</b><span>The full settings file</span></summary><div class="body stack">
        <p class="muted small">Every setting, with notes on what each one does. Changes here are checked on GitHub after saving.</p>
        <textarea class="code" id="raw" spellcheck="false"></textarea>
        <div class="row" style="justify-content:flex-end"><button type="button" class="btn" data-save-raw>Save this file</button></div></div></details>
      <div class="savebar"><button type="button" class="btn primary" data-save>Save changes</button></div>
      <p style="margin-top:22px"><button type="button" class="btn quiet" data-signout>Sign out</button></p>`;
  $("#raw").value = ctext("config.yaml");
  $("[data-signout]").addEventListener("click", async () => { await api("logout", { method: "POST" }); showLogin(); });

  $$("input[type=range]").forEach((r) => r.addEventListener("input", () => {
    const out = $("output", r.closest("label"));
    out.textContent = out.dataset.unit !== undefined
      ? `${+(Number(r.value) * Number(out.dataset.scale)).toFixed(2)}${out.dataset.unit}` : `${r.value}%`;
  }));

  $("[data-save]").addEventListener("click", (e) => busy(e.target, async () => {
    let text = ctext("config.yaml");
    let changes = 0;
    for (const f of SETTINGS.flatMap((g) => g.fields)) {
      const next = readField(f);
      const was = current(f);
      if (JSON.stringify(next) === JSON.stringify(was)) continue;
      if (f.kind === "number" && (!Number.isFinite(next) || next < f.min || next > f.max)) throw new Error(`${f.label} must be between ${f.min} and ${f.max}.`);
      text = Array.isArray(next) ? setList(text, f.path, next) : setScalar(text, f.path, next);
      changes += 1;
    }
    const picked = $$("[data-reach]:checked").map((i) => i.value);
    const before = accounts().filter((a) => reaches(a.name)).map((a) => a.name);
    if (accounts().length && JSON.stringify(picked) !== JSON.stringify(before)) {
      if (!picked.length) throw new Error("Pick at least one account, or pause the campaign instead.");
      const everyone = picked.length === accounts().length;
      text = setScalar(text, ["accounts", "mode"], everyone ? "block" : "allow");
      text = setList(text, ["accounts", "names"], everyone ? [] : picked);
      changes += 1;
    }
    if (!changes) { toast("Nothing changed."); return; }
    await commit([{ path: cpath("config.yaml"), text }], `settings for ${slug()}`);
    toast(`Saved. Takes effect from the next batch.`);
    render();
  }));

  $("[data-save-raw]").addEventListener("click", (e) => busy(e.target, async () => {
    const text = $("#raw").value;
    try { window.jsyaml.load(text); }
    catch (err) { throw new Error(`Not saved. Line ${(err.mark || {}).line + 1 || "?"}: ${err.reason || err.message}`); }
    await commit([{ path: cpath("config.yaml"), text }], `settings file for ${slug()}`);
    toast("File saved.");
    render();
  }));
}

// ---------------------------------------------------------------------- jobs

function viewJobs() {
  const jobs = [
    ["render", "Make videos now", "Builds the next batch from your clips, tracks and captions."],
    ["topup", "Send to Buffer now", "Hands the waiting videos to Buffer to post at their times."],
    ["preflight", "Check everything", "Looks for anything that would stop the next batch."],
    ["metrics", "Refresh numbers", "Pulls the latest views for each post."],
    ["diagnose", "Why didn't it post?", "Asks Buffer what happened on every account."],
  ];
  const live = mode().key === "live";
  $("#view").innerHTML = head("Jobs", "These run on their own every day. Start one now if you don't want to wait.")
    + `<div class="panel">${jobs.map(([w, label, text]) => `<div class="row" style="padding:9px 0;flex-wrap:nowrap">
        <div class="grow"><b>${label}</b><div class="muted small">${text}</div></div>
        <button type="button" class="btn compact" data-run="${w}">Start</button></div>`).join("")}
        <p class="note" style="margin-top:8px">${live
          ? "This campaign is live: making and sending videos here posts for real."
          : "This campaign isn't live, so nothing started here reaches your accounts."}</p></div>
      <div class="panel"><h3>Recent</h3><div id="runs" class="muted" style="margin-top:8px">Loading…</div></div>`;
  $$("[data-run]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
    const workflow = b.dataset.run;
    const inputs = { campaign: slug() };
    if (workflow === "render" || workflow === "topup") {
      inputs.dry_run = String(!live);
      if (live && !confirm(`${b.closest(".row").querySelector("b").textContent} for ${slug()}? This is live.`)) return;
    }
    await api("run", { method: "POST", body: { workflow, inputs } });
    toast("Started. It appears below in a few seconds.");
    setTimeout(runs, 5000);
  })));
  runs();
}

async function runs() {
  const el = $("#runs");
  if (!el) return;
  try {
    const { runs: list } = await api("runs");
    const bad = (r) => ["failure", "startup_failure", "timed_out"].includes(r.conclusion);
    const light = (r) => (r.conclusion === "success" ? "go" : bad(r) ? "hold" : "standby");
    const word = (r) => (r.conclusion === "success" ? "Done" : r.conclusion === "startup_failure" ? "Didn't start" : bad(r) ? "Failed" : r.conclusion === "cancelled" ? "Cancelled" : r.conclusion || "Running");
    el.innerHTML = list.length ? `<table>${list.map((r) => `<tr>
      <td><span class="row" style="gap:8px;flex-wrap:nowrap"><span class="dot ${light(r)}"></span><b>${esc(r.name)}</b></span>
        <div class="muted small">${esc(new Date(r.started).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" }))} · ${word(r)}</div></td>
      <td style="text-align:right"><a href="${esc(r.url)}" target="_blank" rel="noopener">Details</a></td></tr>`).join("")}</table>` : "Nothing has run yet.";
  } catch (err) { el.textContent = err.message; }
}

// -------------------------------------------------------------- new campaign

function viewNewCampaign() {
  $$("#tabs button").forEach((b) => b.classList.remove("on"));
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "America/New_York";
  $("#view").innerHTML = head("New campaign", "It starts switched off, so nothing posts until you say so.")
    + `<form class="panel stack" id="new">
      <label class="field"><span class="label">What are you promoting?</span>
        <input type="text" name="title" required placeholder="Education by Close Quarters">
        <span class="help">A song, an album, an app, a product.</span></label>
      <div><span class="label" style="font-weight:550">What kind of videos?</span>
        <label class="check"><input type="radio" name="kind" value="music" checked><span>Music<span class="muted small" style="display:block">The track plays at full volume over silent clips.</span></span></label>
        <label class="check"><input type="radio" name="kind" value="talk"><span>Talking clips<span class="muted small" style="display:block">The clips' own sound, with quiet music underneath. For apps and products.</span></span></label></div>
      <label class="field"><span class="label">Link</span><input type="url" name="link" placeholder="https://">
        <span class="help">Where every post sends people. You can add it later.</span></label>
      <div class="grid2">
        <label class="field"><span class="label">Posts per day</span><input type="number" name="posts" value="3" min="1" max="24" inputmode="numeric"></label>
        <label class="field"><span class="label">Time zone</span><input type="text" name="zone" value="${esc(zone)}"></label>
        <label class="field"><span class="label">First post of the day</span><select name="start">${[...Array(24).keys()].map((h) => `<option value="${h}" ${h === 11 ? "selected" : ""}>${hourName(h)}</option>`).join("")}</select></label>
        <label class="field"><span class="label">Stop posting at</span><select name="end">${[...Array(24).keys()].map((h) => `<option value="${h}" ${h === 23 ? "selected" : ""}>${hourName(h)}</option>`).join("")}</select></label>
      </div>
      <div><span class="label" style="font-weight:550">Post to</span>
        ${accounts().map((a) => `<label class="check"><input type="checkbox" name="account" value="${esc(a.name)}" checked><span>${esc(a.name)} <span class="muted small">${esc(a.network)}</span></span></label>`).join("")}</div>
      <div class="row" style="justify-content:flex-end">
        <button type="button" class="btn" data-cancel>Cancel</button>
        <button type="submit" class="btn primary">Create campaign</button></div></form>`;
  $("[data-cancel]").addEventListener("click", () => { $("#campaign").value = STATE.campaigns[0] || ""; render(); });
  $("#new").addEventListener("submit", (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    busy($("#new button[type=submit]"), async () => {
      const title = String(form.get("title")).trim();
      const name = slugify(title);
      if (STATE.campaigns.includes(name)) throw new Error(`There is already a campaign called ${name}.`);
      const picked = form.getAll("account");
      if (!picked.length) throw new Error("Pick at least one account.");
      const all = accounts();
      const primary = all.find((a) => a.name === picked[0]);
      const files = campaignFiles({
        slug: name, kind: form.get("kind"), title, link: String(form.get("link")).trim(),
        timezone: String(form.get("zone")).trim(), postsPerDay: Number(form.get("posts")),
        startHour: Number(form.get("start")), endHour: Number(form.get("end")),
        accounts: picked.length === all.length ? [] : picked, primary,
      });
      await api("commit", { method: "POST", body: { files, message: `new campaign ${name}`, new_campaign: name } });
      await load();
      $("#campaign").value = name;
      TAB = "Content";
      render();
      toast("Created, and switched off. Drop in your videos to start.");
    });
  });
}

// ---------------------------------------------------------------------- wire

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-msg").textContent = "";
  try {
    await api("login", { method: "POST", body: { password: $("#password").value } });
    $("#password").value = "";
    await load();
  } catch (err) { $("#login-msg").textContent = err.message; }
});
$("#campaign").addEventListener("change", () => render());
$("#mode").addEventListener("click", openMode);
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tab]");
  if (!b) return;
  if ($("#campaign").value === "+") $("#campaign").value = STATE.campaigns[0] || "";
  TAB = b.dataset.tab;
  render();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

load();
