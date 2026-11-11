// The hosted dashboard's whole server side: a small, deliberately narrow
// bridge between a logged-in browser and this repository on GitHub.
//
// It can do exactly four things, each against an allowlist: read campaign
// files, write the handful of files a person edits, start a workflow, and
// list recent runs. It holds the only credential (a GitHub token scoped to
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
  /^campaigns\/[a-z0-9_-]+\/(config\.yaml|lineup\.yaml|captions\.txt)$/,
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
};

const INPUT_SHAPE = {
  campaign: /^[a-z0-9_-]{1,64}$/,
  dry_run: /^(true|false)$/,
  count: /^[0-9]{1,2}$/,
  discard: /^(pending|pushed|all)$/,
  video_id: /^[0-9a-f-]{4,36}$/,
  account: /^[a-z0-9_]{1,64}$/,
};

const MAX_FILE_BYTES = 400_000;

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
  if (method !== "GET") {
    if (request.headers.get("x-ugc") !== "1"
        || !(request.headers.get("content-type") || "").includes("application/json")) {
      return json({ error: "bad request" }, 400);
    }
  }

  let body = {};
  if (method !== "GET") {
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

    if (route === "file" && method === "PUT") {
      const { path, text, sha } = body;
      if (!matches(WRITABLE, path)) return json({ error: "that file cannot be edited here" }, 403);
      if (typeof text !== "string" || !text.trim()) return json({ error: "refusing to save an empty file" }, 400);
      if (new TextEncoder().encode(text).length > MAX_FILE_BYTES) return json({ error: "too large" }, 413);
      const res = await gh(env, `/contents/${path}`, {
        method: "PUT",
        body: JSON.stringify({
          message: `dashboard: update ${path}`,
          content: b64encode(text.endsWith("\n") ? text : `${text}\n`),
          branch,
          // The version the editor loaded. If the file moved on since — a
          // workflow, another tab — GitHub refuses rather than overwriting.
          ...(typeof sha === "string" && sha ? { sha } : {}),
        }),
      });
      if (res.status === 409 || res.status === 422) {
        return json({ error: "this file changed since you opened it — reload and redo the edit" }, 409);
      }
      if (!res.ok) return json({ error: `GitHub ${res.status} saving ${path}` }, 502);
      const saved = await res.json();
      return json({ ok: true, sha: saved.content.sha });
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
      const res = await gh(env, `/actions/runs?per_page=20&branch=${encodeURIComponent(branch)}`);
      if (!res.ok) return json({ error: `GitHub ${res.status} listing runs` }, 502);
      const runs = (await res.json()).workflow_runs.map((r) => ({
        name: r.name, event: r.event, status: r.status, conclusion: r.conclusion,
        started: r.run_started_at, url: r.html_url,
      }));
      return json({ runs });
    }
  } catch (err) {
    return json({ error: String(err && err.message ? err.message : err) }, 502);
  }

  return json({ error: "not found" }, 404);
}
