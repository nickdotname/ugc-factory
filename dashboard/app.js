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

async function assetsFor(creative) {
  const tag = tagFor(creative);
  if (!ASSETS.has(tag)) {
    try { ASSETS.set(tag, (await api(`assets?tag=${encodeURIComponent(tag)}`)).assets); }
    catch { ASSETS.set(tag, []); }
  }
  const all = ASSETS.get(tag);
  return {
    clips: all.filter((a) => /^(hook|body)/i.test(a.name)),
    music: all.filter((a) => /^music/i.test(a.name)),
  };
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

  $("#view").innerHTML = head("Schedule", `${items.length ? `${items.length} video${items.length === 1 ? "" : "s"} lined up` : "Nothing lined up"} for ${esc(slug())}.`,
    `<button type="button" class="btn compact" data-reload>Refresh</button>`)
    + (rows || `<div class="panel empty"><b>Nothing is scheduled</b>${mode().key === "paused"
      ? "This campaign is paused. Tap “Paused” at the top to switch it on."
      : "The next batch is made overnight. To make it now, open Jobs and tap “Make videos now”."}</div>`);

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

// ------------------------------------------------------------------- content

function creativesBlock(list) {
  const lines = ["creatives:"];
  for (const c of list) {
    lines.push(`  - name: ${c.name}`);
    if (c.title) lines.push(`    title: ${yamlString(c.title)}`);
    if (c.link) lines.push(`    link: ${yamlString(c.link)}`);
    if (c.weight && Number(c.weight) !== 1) lines.push(`    weight: ${Number(c.weight)}`);
    if (c.assets_release) lines.push(`    assets_release: ${c.assets_release}`);
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

function viewContent() {
  const word = setWord();
  const cards = creatives().map((c, index) => {
    const bank = parseBank((file(bankPathFor(c)) || {}).text || "");
    const shared = !file(cpath(`creatives/${c.name}/captions.txt`));
    const cues = Object.values(c.music_cues || {}).flat();
    return `<div class="panel" data-creative="${index}">
      <div class="row"><h3 class="grow">${esc(c.title || c.name)}</h3>
        ${Number(c.weight || 1) !== 1 ? `<span class="tag">posts ${Number(c.weight)}× as often</span>` : ""}</div>
      <p class="muted small" data-library>Checking clips…</p>
      <p class="small" style="margin-top:6px">${bank.records.length} caption${bank.records.length === 1 ? "" : "s"}${shared ? " (shared with the campaign)" : ""}
        · ${cues.length ? `starts at ${cues.map((s) => `${s}s`).join(", ")}` : "starts anywhere in the track"}
        · ${(c.accounts || []).length ? `posts to ${c.accounts.join(", ")}` : "posts to every account"}</p>
      <div class="row" style="margin-top:12px">
        <button type="button" class="btn compact" data-captions="${index}">Captions</button>
        <button type="button" class="btn compact" data-edit="${index}">Details</button>
      </div></div>`;
  }).join("");
  $("#view").innerHTML = head("Content", `Each ${word} has its own clips, track and captions.`,
    `<button type="button" class="btn primary compact" data-add>Add a ${word}</button>`) + cards
    + `<p class="note" style="margin-top:14px">Clips and tracks are uploaded from your computer (run <b>./ugc web</b> and drop them in). Everything else about a ${word} is edited here.</p>`;

  creatives().forEach(async (c, index) => {
    const { clips, music } = await assetsFor(c);
    const el = $(`[data-creative="${index}"] [data-library]`);
    if (!el) return;
    el.textContent = clips.length || music.length
      ? `${clips.length} clip${clips.length === 1 ? "" : "s"}, ${music.length} track${music.length === 1 ? "" : "s"} uploaded`
      : "No clips uploaded yet.";
  });
  $("[data-add]").addEventListener("click", () => editCreative(-1));
  $$("[data-edit]").forEach((b) => b.addEventListener("click", () => editCreative(Number(b.dataset.edit))));
  $$("[data-captions]").forEach((b) => b.addEventListener("click", () => editCaptions(creatives()[Number(b.dataset.captions)])));
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
        const base = cpath(`creatives/${updated.name}`);
        extra.push({ path: `${base}/captions.txt`, text: `# Captions for ${title}.\n\noverlay: ${isMusic() ? "this part. | every single time." : "wait for it"}\ntitle: ${title}\n${title}\n` });
        extra.push({ path: `${base}/LICENSES.md`, text: `# Music licences — ${slug()} / ${updated.name}\n\n| file | source | licence |\n|---|---|---|\n` });
        list.push(updated);
      } else list[index] = updated;
      await save(list, `${isNew ? "add" : "update"} ${updated.name}`, extra);
      toast(isNew ? `Added. Now write its captions and upload its clips.` : "Saved.");
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
    const light = (r) => (r.conclusion === "success" ? "go" : r.conclusion === "failure" ? "hold" : "standby");
    const word = (r) => (r.conclusion === "success" ? "Done" : r.conclusion === "failure" ? "Failed" : r.conclusion || "Running");
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
      toast("Created, and switched off. Add its clips and captions next.");
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
