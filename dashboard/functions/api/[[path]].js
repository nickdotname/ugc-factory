// The hosted dashboard's whole server side: a small, deliberately narrow
// bridge between a logged-in browser and this repository on GitHub.
//
// It can do exactly five things, each against an allowlist: read campaign
// files, commit changes to the handful of files a person edits, list a
// clip library, start a workflow, and list recent runs. It holds the only credential (a GitHub token scoped to
// this one repo) and never sends it to the browser.
//
// Environment (Cloudflare Pages → Settings → Variables and Secrets):
//   DASH_PASSWORD   required. The login password.
//   GITHUB_TOKEN    required. Fine-grained token for this repo with
//                   Contents: read/write and Actions: read/write.
//   GITHUB_REPO     optional. Defaults to nickdotname/ugc-factory.
//   GITHUB_BRANCH   optional. Defaults to main.
//
// Anything missing fails closed: no password configured means nobody gets in.

import { streamAsset } from "../../lib/media.js";

const DEFAULT_REPO = "nickdotname/ugc-factory";
const SESSION_DAYS = 7;
const COOKIE = "ugc_session";

// Files the dashboard may READ for a campaign.
const READABLE = [
  /^accounts\.yaml$/,
  /^campaigns\/[a-z0-9_-]+\/(config\.yaml|queue\.json|lineup\.yaml|captions\.txt|clips\.json|quota\.json)$/,
  /^campaigns\/[a-z0-9_-]+\/captions\/(instagram|tiktok|youtube)\.txt$/,
  /^campaigns\/[a-z0-9_-]+\/creatives\/[a-z0-9_]+\/(captions\.txt|LICENSES\.md)$/,
  /^campaigns\/[a-z0-9_-]+\/creatives\/[a-z0-9_]+\/captions\/(instagram|tiktok|youtube)\.txt$/,
];

// Files it may WRITE. Narrower on purpose: queue.json and the like are the
// pipeline's own state, and accounts.yaml is changed with `ugc connect`.
const WRITABLE = [
  /^campaigns\/[a-z0-9_-]+\/(config\.yaml|lineup\.yaml|captions\.txt|clips\.json)$/,
  /^campaigns\/[a-z0-9_-]+\/captions\/(instagram|tiktok|youtube)\.txt$/,
  /^campaigns\/[a-z0-9_-]+\/creatives\/[a-z0-9_]+\/(captions\.txt|LICENSES\.md)$/,
  /^campaigns\/[a-z0-9_-]+\/creatives\/[a-z0-9_]+\/captions\/(instagram|tiktok|youtube)\.txt$/,
];

// Workflows it may start, and the only inputs each accepts.
const WORKFLOWS = {
  render: ["campaign", "dry_run", "count"],
  topup: ["campaign", "dry_run"],
  preflight: ["campaign"],
  metrics: ["campaign"],
  diagnose: ["campaign"],
  queue: ["campaign", "discard", "video_id", "account"],
  ingest: ["campaign", "creative"],
};

const INPUT_SHAPE = {
  campaign: /^[a-z0-9_-]{1,64}$/,
  dry_run: /^(true|false)$/,
  count: /^[0-9]{1,2}$/,
  discard: /^(pending|pushed|all)$/,
  video_id: /^[0-9a-f-]{4,36}$/,
  account: /^[a-z0-9_]{1,64}$/,
  creative: /^[a-z0-9_]{1,64}$/,
};

// Files a brand-new campaign needs that nobody edits by hand. Their content
// is fixed here; whatever the browser sends for them is ignored.
const SEEDED = {
  "queue.json": '{\n  "generated_at": "1970-01-01T00:00:00Z",\n  "items": []\n}\n',
  "history.json": '{\n  "entries": []\n}\n',
};
const SLUG = /^[a-z][a-z0-9_]{1,40}$/;
const ASSET_TAG = /^(assets|inbox)-[a-z0-9_-]{1,80}$/;
const MEDIA_TAG = /^(assets|inbox|render)-[a-z0-9_-]{1,80}$/;
const MEDIA_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]{0,180}\.(mp4|mov|m4v|webm|mp3|m4a|wav|aac|ogg)$/;
const LIBRARY_TAG = /^assets-[a-z0-9_-]{1,80}$/;

// What can be dropped in, by the role it will play. The same lists the
// engine's own ingest accepts (src/assets.py).
const UPLOADS = {
  hook: [".mp4", ".mov", ".m4v", ".webm"],
  body: [".mp4", ".mov", ".m4v", ".webm"],
  music: [".mp3", ".m4a", ".wav"],
};
// A Pages Function holds the whole file in memory on its way through.
const MAX_UPLOAD_BYTES = 95 * 1024 * 1024;

const MAX_FILE_BYTES = 400_000;
const MAX_FILES_PER_COMMIT = 12;

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...headers,
    },
  });
}

function matches(list, path) {
  return typeof path === "string" && !path.includes("..") && list.some((re) => re.test(path));
}

// ------------------------------------------------------------------ sessions

async function hmac(key, message) {
  const enc = new TextEncoder();
  const k = await crypto.subtle.importKey(
    "raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", k, enc.encode(message));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Compare through an HMAC so the comparison takes the same time whatever
// the two strings have in common.
async function same(a, b, key) {
  const [x, y] = await Promise.all([hmac(key, a), hmac(key, b)]);
  let diff = x.length ^ y.length;
  for (let i = 0; i < x.length && i < y.length; i++) diff |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return diff === 0;
}

async function sessionCookie(env) {
  const expires = Date.now() + SESSION_DAYS * 86400_000;
  // Signed with the password itself: changing it signs everyone out.
  const sig = await hmac(env.DASH_PASSWORD, `session:${expires}`);
  return `${COOKIE}=${expires}.${sig}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_DAYS * 86400}`;
}

async function signedIn(request, env) {
  const cookie = request.headers.get("cookie") || "";
  const found = cookie.split(/;\s*/).find((c) => c.startsWith(`${COOKIE}=`));
  if (!found) return false;
  const [expires, sig] = found.slice(COOKIE.length + 1).split(".");
  if (!expires || !sig || !/^[0-9]+$/.test(expires) || Number(expires) < Date.now()) return false;
  return same(sig, await hmac(env.DASH_PASSWORD, `session:${expires}`), env.DASH_PASSWORD);
}

// -------------------------------------------------------------------- github

function gh(env, path, init = {}) {
  const repo = env.GITHUB_REPO || DEFAULT_REPO;
  return fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "ugc-factory-dashboard",
      ...(init.headers || {}),
    },
  });
}

function b64decode(text) {
  const bin = atob(text.replace(/\n/g, ""));
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

function b64encode(text) {
  let bin = "";
  for (const byte of new TextEncoder().encode(text)) bin += String.fromCharCode(byte);
  return btoa(bin);
}

async function readFile(env, path, branch) {
  const res = await gh(env, `/contents/${path}?ref=${encodeURIComponent(branch)}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`GitHub ${res.status} reading ${path}`);
  const body = await res.json();
  // Files over 1 MB come back without content; none of the readable ones
  // should be, and guessing would be worse than saying so.
  if (typeof body.content !== "string" || body.encoding !== "base64") {
    throw new Error(`${path} is too large to read here`);
  }
  return { path, sha: body.sha, text: b64decode(body.content) };
}

async function state(env, branch) {
  const tree = await gh(env, `/git/trees/${encodeURIComponent(branch)}?recursive=1`);
  if (!tree.ok) throw new Error(`GitHub ${tree.status} listing the repository`);
  const paths = (await tree.json()).tree
    .filter((n) => n.type === "blob" && matches(READABLE, n.path))
    // Parked campaigns (a leading underscore) are not running; leave them out.
    .filter((n) => !/^campaigns\/_/.test(n.path))
    .map((n) => n.path);
  const files = (await Promise.all(paths.map((p) => readFile(env, p, branch)))).filter(Boolean);
  const campaigns = [...new Set(
    files.map((f) => (f.path.match(/^campaigns\/([^/]+)\//) || [])[1]).filter(Boolean),
  )].sort();
  return { repo: env.GITHUB_REPO || DEFAULT_REPO, branch, campaigns, files };
}

// What git itself would call this content, so the browser knows the new
// version of a file without asking again.
async function blobSha(text) {
  const body = new TextEncoder().encode(text);
  const head = new TextEncoder().encode(`blob ${body.length}\0`);
  const all = new Uint8Array(head.length + body.length);
  all.set(head); all.set(body, head.length);
  const digest = await crypto.subtle.digest("SHA-1", all);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

class Refused extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

// One commit for any number of edited files: either every change lands or
// none does, and the checks on push run once.
async function commit(env, branch, body) {
  const files = Array.isArray(body.files) ? body.files : [];
  if (!files.length) throw new Refused(400, "nothing to save");
  if (files.length > MAX_FILES_PER_COMMIT) throw new Refused(400, "too many files in one save");

  const fresh = typeof body.new_campaign === "string" ? body.new_campaign : "";
  if (fresh && !SLUG.test(fresh)) throw new Refused(400, "campaign name must be lowercase letters, digits and underscores");

  const wanted = new Map();
  for (const f of files) {
    if (!f || !matches(WRITABLE, f.path)) throw new Refused(403, "that file cannot be edited here");
    if (fresh && !f.path.startsWith(`campaigns/${fresh}/`)) throw new Refused(403, "a new campaign can only write its own files");
    if (typeof f.text !== "string" || !f.text.trim()) throw new Refused(400, `refusing to save an empty file: ${f.path}`);
    if (new TextEncoder().encode(f.text).length > MAX_FILE_BYTES) throw new Refused(413, "too large");
    wanted.set(f.path, { text: f.text.endsWith("\n") ? f.text : `${f.text}\n`, sha: f.sha || "" });
  }
  if (fresh) {
    if (!wanted.has(`campaigns/${fresh}/config.yaml`)) throw new Refused(400, "a new campaign needs its config");
    for (const [name, text] of Object.entries(SEEDED)) {
      wanted.set(`campaigns/${fresh}/${name}`, { text, sha: "", seeded: true });
    }
  }

  const ref = await gh(env, `/git/ref/heads/${encodeURIComponent(branch)}`);
  if (!ref.ok) throw new Error(`GitHub ${ref.status} reading the branch`);
  const head = (await ref.json()).object.sha;
  const parent = await gh(env, `/git/commits/${head}`);
  if (!parent.ok) throw new Error(`GitHub ${parent.status} reading the latest commit`);
  const baseTree = (await parent.json()).tree.sha;
  const listing = await gh(env, `/git/trees/${baseTree}?recursive=1`);
  if (!listing.ok) throw new Error(`GitHub ${listing.status} listing the repository`);
  const current = new Map((await listing.json()).tree.map((n) => [n.path, n.sha]));

  if (fresh && current.has(`campaigns/${fresh}/config.yaml`)) {
    throw new Refused(409, `a campaign called ${fresh} already exists`);
  }
  for (const [path, file] of wanted) {
    const existing = current.get(path) || "";
    // The version the editor loaded must still be the version on the
    // branch: a workflow or another tab may have moved it on since.
    if (existing !== file.sha) {
      throw new Refused(409, existing
        ? `${path} changed since you opened it. Reload, then make the change again.`
        : `${path} no longer exists. Reload.`);
    }
  }

  const tree = await gh(env, "/git/trees", {
    method: "POST",
    body: JSON.stringify({
      base_tree: baseTree,
      tree: [...wanted].map(([path, f]) => ({ path, mode: "100644", type: "blob", content: f.text })),
    }),
  });
  if (!tree.ok) throw new Error(`GitHub ${tree.status} writing the files`);
  const note = String(body.message || "update").replace(/[\r\n]+/g, " ").slice(0, 100);
  const made = await gh(env, "/git/commits", {
    method: "POST",
    body: JSON.stringify({ message: `dashboard: ${note}`, tree: (await tree.json()).sha, parents: [head] }),
  });
  if (!made.ok) throw new Error(`GitHub ${made.status} creating the commit`);
  const moved = await gh(env, `/git/refs/heads/${encodeURIComponent(branch)}`, {
    method: "PATCH",
    body: JSON.stringify({ sha: (await made.json()).sha, force: false }),
  });
  if (!moved.ok) {
    // Something else committed in the last second (the pipeline does, all
    // day). Nothing was overwritten; the save just has to be tried again.
    throw new Refused(409, "The repository changed while saving. Nothing was lost — save again.");
  }
  return {
    ok: true,
    files: await Promise.all([...wanted].map(async ([path, f]) => ({ path, sha: await blobSha(f.text), text: f.text }))),
  };
}

// A dropped file goes to a holding area — a release named inbox-<library> —
// not into the library itself. The ingest job picks it up from there, checks
// that it really is a playable clip or track, gives it its proper name and
// only then adds it to the library the renderer draws from. Nothing a browser
// sends is trusted to be what its filename says.
async function upload(env, url, request) {
  const tag = url.searchParams.get("tag") || "";
  const kind = url.searchParams.get("kind") || "";
  const original = url.searchParams.get("name") || "";
  if (!LIBRARY_TAG.test(tag)) throw new Refused(400, "bad library name");
  if (!UPLOADS[kind]) throw new Refused(400, "bad file role");
  const dot = original.lastIndexOf(".");
  const ext = dot === -1 ? "" : original.slice(dot).toLowerCase();
  if (!UPLOADS[kind].includes(ext)) {
    throw new Refused(415, `${original || "that file"} can't be used here. Use ${UPLOADS[kind].join(", ")}.`);
  }
  const declared = Number(request.headers.get("content-length") || 0);
  if (declared > MAX_UPLOAD_BYTES) throw new Refused(413, `${original} is over 95 MB. Export it smaller and try again.`);
  const bytes = await request.arrayBuffer();
  if (!bytes.byteLength) throw new Refused(400, `${original} is empty`);
  if (bytes.byteLength > MAX_UPLOAD_BYTES) throw new Refused(413, `${original} is over 95 MB. Export it smaller and try again.`);

  const holding = `inbox-${tag.slice("assets-".length)}`;
  let release = await gh(env, `/releases/tags/${holding}`);
  if (release.status === 404) {
    release = await gh(env, "/releases", {
      method: "POST",
      body: JSON.stringify({
        tag_name: holding, name: holding, prerelease: true,
        body: "Files dropped into the dashboard, waiting to be checked and added to the library.",
      }),
    });
    // Two files dropped at once can both try to create it; the loser reads it.
    if (release.status === 422) release = await gh(env, `/releases/tags/${holding}`);
  }
  if (!release.ok) throw new Error(`GitHub ${release.status} opening the upload area`);
  const id = (await release.json()).id;

  const stem = original.slice(0, dot).replace(/[^A-Za-z0-9_-]+/g, "_").slice(0, 60) || "file";
  const unique = crypto.randomUUID().slice(0, 8);
  const name = `${kind}__${unique}__${stem}${ext}`;
  const repo = env.GITHUB_REPO || DEFAULT_REPO;
  const sent = await fetch(
    `https://uploads.github.com/repos/${repo}/releases/${id}/assets?name=${encodeURIComponent(name)}`,
    {
      method: "POST",
      body: bytes,
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`,
        accept: "application/vnd.github+json",
        "content-type": "application/octet-stream",
        "user-agent": "ugc-factory-dashboard",
      },
    },
  );
  if (!sent.ok) throw new Error(`GitHub ${sent.status} storing ${original}`);
  return { ok: true, name };
}

// --------------------------------------------------------------------- routes

export async function onRequest({ request, env }) {
  const url = new URL(request.url);
  const route = url.pathname.replace(/^\/api\/?/, "").replace(/\/$/, "");
  const method = request.method.toUpperCase();
  const branch = env.GITHUB_BRANCH || "main";

  if (!env.DASH_PASSWORD || !env.GITHUB_TOKEN) {
    return json({ error: "not configured: set DASH_PASSWORD and GITHUB_TOKEN" }, 503);
  }

  // Anything that changes something must be a deliberate request from this
  // page: a JSON body and a header no cross-site form can send.
  // An upload carries the file itself as its body, so it is the one request
  // that is not JSON. The custom header still has to be there.
  const isUpload = route === "upload" && method === "POST";
  if (method !== "GET") {
    if (request.headers.get("x-ugc") !== "1"
        || (!isUpload && !(request.headers.get("content-type") || "").includes("application/json"))) {
      return json({ error: "bad request" }, 400);
    }
  }

  let body = {};
  if (method !== "GET" && !isUpload) {
    try {
      const raw = await request.text();
      if (raw.length > MAX_FILE_BYTES + 2000) return json({ error: "too large" }, 413);
      body = raw ? JSON.parse(raw) : {};
    } catch {
      return json({ error: "body is not JSON" }, 400);
    }
  }

  if (route === "login" && method === "POST") {
    const given = typeof body.password === "string" ? body.password : "";
    if (!(await same(given, env.DASH_PASSWORD, env.DASH_PASSWORD))) {
      // Slow guessing down without keeping any state.
      await new Promise((r) => setTimeout(r, 1200));
      return json({ error: "wrong password" }, 401);
    }
    return json({ ok: true }, 200, { "set-cookie": await sessionCookie(env) });
  }

  if (route === "logout" && method === "POST") {
    return json({ ok: true }, 200, {
      "set-cookie": `${COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`,
    });
  }

  if (!(await signedIn(request, env))) return json({ error: "sign in" }, 401);

  try {
    if (route === "state" && method === "GET") {
      return json(await state(env, branch));
    }

    if (isUpload) {
      return json(await upload(env, url, request));
    }

    if (route === "commit" && method === "POST") {
      return json(await commit(env, branch, body));
    }

    if (route === "assets" && method === "GET") {
      const tag = url.searchParams.get("tag") || "";
      if (!ASSET_TAG.test(tag)) return json({ error: "bad library name" }, 400);
      const res = await gh(env, `/releases/tags/${tag}`);
      // No release yet just means nothing has been uploaded.
      if (res.status === 404) return json({ assets: [] });
      if (!res.ok) return json({ error: `GitHub ${res.status} listing the library` }, 502);
      const assets = ((await res.json()).assets || []).map((a) => ({
        // Played through this site: the repository's own links only open
        // for someone signed in to GitHub.
        name: a.name, size: a.size, note: a.label || "",
        url: `/api/media?tag=${encodeURIComponent(tag)}&name=${encodeURIComponent(a.name)}`,
      }));
      return json({ assets });
    }

    // Play one clip from a library, a holding area or a day's renders.
    if (route === "media" && (method === "GET" || method === "HEAD")) {
      const tag = url.searchParams.get("tag") || "";
      const name = url.searchParams.get("name") || "";
      if (!MEDIA_TAG.test(tag) || !MEDIA_NAME.test(name)) return json({ error: "bad file" }, 400);
      return streamAsset((path, init) => gh(env, path, init), tag, name, request);
    }

    // Clear away a file the check refused, once its owner has read why.
    if (route === "discard" && method === "POST") {
      const tag = String(body.tag || "");
      const name = String(body.name || "");
      if (!ASSET_TAG.test(tag) || !tag.startsWith("inbox-") || !name.startsWith("rejected__")) {
        return json({ error: "only a refused upload can be cleared" }, 400);
      }
      const res = await gh(env, `/releases/tags/${tag}`);
      if (!res.ok) return json({ error: `GitHub ${res.status} finding the upload` }, 502);
      const asset = ((await res.json()).assets || []).find((a) => a.name === name);
      if (asset) {
        const gone = await gh(env, `/releases/assets/${asset.id}`, { method: "DELETE" });
        if (!gone.ok && gone.status !== 404) return json({ error: `GitHub ${gone.status} clearing the upload` }, 502);
      }
      return json({ ok: true });
    }

    if (route === "run" && method === "POST") {
      const allowed = WORKFLOWS[body.workflow];
      if (!allowed) return json({ error: "unknown workflow" }, 400);
      const inputs = {};
      for (const [key, value] of Object.entries(body.inputs || {})) {
        if (value === "" || value === null || value === undefined) continue;
        const text = String(value);
        if (!allowed.includes(key) || !INPUT_SHAPE[key].test(text)) {
          return json({ error: `bad input: ${key}` }, 400);
        }
        inputs[key] = text;
      }
      const res = await gh(env, `/actions/workflows/${body.workflow}.yml/dispatches`, {
        method: "POST",
        body: JSON.stringify({ ref: branch, inputs }),
      });
      if (!res.ok) return json({ error: `GitHub ${res.status} starting ${body.workflow}` }, 502);
      return json({ ok: true });
    }

    if (route === "runs" && method === "GET") {
      const only = url.searchParams.get("workflow") || "";
      if (only && !WORKFLOWS[only]) return json({ error: "unknown workflow" }, 400);
      const res = await gh(env, `/actions${only ? `/workflows/${only}.yml` : ""}/runs?per_page=${only ? 5 : 20}&branch=${encodeURIComponent(branch)}`);
      if (!res.ok) return json({ error: `GitHub ${res.status} listing runs` }, 502);
      const runs = (await res.json()).workflow_runs.map((r) => ({
        name: r.name, event: r.event, status: r.status, conclusion: r.conclusion,
        started: r.run_started_at || r.created_at, url: r.html_url,
      }));
      return json({ runs });
    }
  } catch (err) {
    const status = err instanceof Refused ? err.status : 502;
    return json({ error: String(err && err.message ? err.message : err) }, status);
  }

  return json({ error: "not found" }, 404);
}
