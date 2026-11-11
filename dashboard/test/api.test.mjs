// Run with: node --test dashboard/test
//
// The function is the only thing standing between the internet and a token
// that can change what posts. These tests are about what it refuses.
import assert from "node:assert/strict";
import { test } from "node:test";

import { onRequest } from "../functions/api/[[path]].js";

const env = { DASH_PASSWORD: "correct horse", GITHUB_TOKEN: "ghp_secret" };

function call(path, { method = "GET", body, cookie, headers = {}, e = env } = {}) {
  const init = { method, headers: { ...headers } };
  if (cookie) init.headers.cookie = cookie;
  if (method !== "GET") {
    init.headers["content-type"] ??= "application/json";
    init.headers["x-ugc"] ??= "1";
    init.body = JSON.stringify(body ?? {});
  }
  return onRequest({ request: new Request(`https://x.test/api/${path}`, init), env: e });
}

async function login() {
  const res = await call("login", { method: "POST", body: { password: env.DASH_PASSWORD } });
  assert.equal(res.status, 200);
  return res.headers.get("set-cookie").split(";")[0];
}

function mockGithub(handler) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return handler(String(url), init);
  };
  return calls;
}

const ok = (body) => new Response(JSON.stringify(body), { status: 200 });

test("fails closed when nothing is configured", async () => {
  const res = await call("state", { e: {} });
  assert.equal(res.status, 503);
});

test("nothing is readable or writable without signing in", async () => {
  for (const path of ["state", "runs", "assets?tag=assets-a"]) assert.equal((await call(path)).status, 401);
  const write = await call("commit", { method: "POST", body: { files: [{ path: "campaigns/a/config.yaml", text: "x" }] } });
  assert.equal(write.status, 401);
});

test("a wrong password is refused and sets no cookie", async () => {
  const res = await call("login", { method: "POST", body: { password: "nope" } });
  assert.equal(res.status, 401);
  assert.equal(res.headers.get("set-cookie"), null);
});

test("a forged or expired cookie is refused", async () => {
  const future = Date.now() + 1e9;
  assert.equal((await call("state", { cookie: `ugc_session=${future}.deadbeef` })).status, 401);
  const real = await login();
  const sig = real.split(".")[1];
  assert.equal((await call("state", { cookie: `ugc_session=${Date.now() - 1}.${sig}` })).status, 401);
});

test("the session cookie is locked down", async () => {
  const res = await call("login", { method: "POST", body: { password: env.DASH_PASSWORD } });
  const cookie = res.headers.get("set-cookie");
  for (const flag of ["HttpOnly", "Secure", "SameSite=Strict"]) assert.ok(cookie.includes(flag));
});

test("a cross-site style write is refused even when signed in", async () => {
  const cookie = await login();
  const res = await call("commit", {
    method: "POST", cookie, headers: { "x-ugc": "0" },
    body: { files: [{ path: "campaigns/a/config.yaml", text: "x" }] },
  });
  assert.equal(res.status, 400);
});

// A stand-in for the Git data API: one branch, a few existing files.
function repo(existing = {}) {
  const writes = [];
  const calls = mockGithub((url, init) => {
    const method = init.method || "GET";
    if (url.includes("/git/ref/")) return ok({ object: { sha: "head1" } });
    if (url.includes("/git/commits/head1")) return ok({ tree: { sha: "tree1" } });
    if (url.includes("/git/trees/tree1")) {
      return ok({ tree: Object.entries(existing).map(([path, sha]) => ({ path, sha, type: "blob" })) });
    }
    if (url.endsWith("/git/trees") && method === "POST") { writes.push(JSON.parse(init.body)); return ok({ sha: "tree2" }); }
    if (url.endsWith("/git/commits") && method === "POST") return ok({ sha: "commit2" });
    if (url.includes("/git/refs/heads/") && method === "PATCH") return ok({});
    return new Response("{}", { status: 404 });
  });
  return { calls, writes };
}

const save = (cookie, body) => call("commit", { method: "POST", cookie, body });

test("only the editable files can be committed", async () => {
  const cookie = await login();
  const { calls } = repo();
  const refused = [
    "accounts.yaml", "campaigns/a/queue.json", "campaigns/a/history.json",
    "src/cli.py", ".github/workflows/render.yml", "campaigns/a/../../src/cli.py",
    "campaigns/a/config.yaml/../../../src/cli.py", "ugc", "dashboard/app.js",
  ];
  for (const path of refused) {
    const res = await save(cookie, { files: [{ path, text: "x: 1" }] });
    assert.equal(res.status, 403, path);
  }
  // One bad file refuses the whole save.
  const mixed = await save(cookie, { files: [{ path: "campaigns/a/lineup.yaml", text: "posts: []" }, { path: "src/cli.py", text: "x" }] });
  assert.equal(mixed.status, 403);
  assert.equal(calls.length, 0, "nothing reached GitHub");
});

test("several files land in one commit, on top of the version that was edited", async () => {
  const cookie = await login();
  const { calls, writes } = repo({ "campaigns/cq/config.yaml": "sha-old" });
  const res = await save(cookie, {
    message: "add a song\nwith a second line",
    files: [
      { path: "campaigns/cq/config.yaml", text: "slug: cq", sha: "sha-old" },
      { path: "campaigns/cq/creatives/song_a/captions.txt", text: "hello" },
    ],
  });
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.files.length, 2);
  assert.match(body.files[0].sha, /^[0-9a-f]{40}$/);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].base_tree, "tree1");
  assert.deepEqual(writes[0].tree.map((t) => [t.path, t.content]), [
    ["campaigns/cq/config.yaml", "slug: cq\n"],
    ["campaigns/cq/creatives/song_a/captions.txt", "hello\n"],
  ]);
  const made = JSON.parse(calls.find((c) => c.url.endsWith("/git/commits")).init.body);
  assert.equal(made.message, "dashboard: add a song with a second line");
  assert.deepEqual(made.parents, ["head1"]);
  const moved = JSON.parse(calls.find((c) => c.init.method === "PATCH").init.body);
  assert.equal(moved.force, false);
});

test("the blob sha it reports is the one git would compute", async () => {
  const cookie = await login();
  repo();
  const res = await save(cookie, { files: [{ path: "campaigns/a/lineup.yaml", text: "hello" }] });
  // git hash-object for "hello\n"
  assert.equal((await res.json()).files[0].sha, "ce013625030ba8dba906f756967f9e9ca394464a");
});

test("a stale edit is refused, never forced", async () => {
  const cookie = await login();
  const { writes } = repo({ "campaigns/a/lineup.yaml": "sha-new" });
  const stale = await save(cookie, { files: [{ path: "campaigns/a/lineup.yaml", text: "posts: []", sha: "sha-old" }] });
  assert.equal(stale.status, 409);
  // Creating a file that turns out to exist already is the same mistake.
  const clobber = await save(cookie, { files: [{ path: "campaigns/a/lineup.yaml", text: "posts: []" }] });
  assert.equal(clobber.status, 409);
  assert.equal(writes.length, 0);
});

test("an empty save is refused", async () => {
  const cookie = await login();
  repo();
  assert.equal((await save(cookie, { files: [] })).status, 400);
  assert.equal((await save(cookie, { files: [{ path: "campaigns/a/lineup.yaml", text: "  " }] })).status, 400);
});

test("a new campaign gets its seed files, and cannot overwrite an existing one", async () => {
  const cookie = await login();
  const { writes } = repo({ "campaigns/clubs/config.yaml": "s1" });
  const files = [{ path: "campaigns/demo/config.yaml", text: "slug: demo" }];
  const res = await save(cookie, { new_campaign: "demo", files });
  assert.equal(res.status, 200);
  const written = Object.fromEntries(writes[0].tree.map((t) => [t.path, t.content]));
  assert.deepEqual(JSON.parse(written["campaigns/demo/queue.json"]).items, []);
  assert.deepEqual(JSON.parse(written["campaigns/demo/history.json"]).entries, []);

  const taken = await save(cookie, { new_campaign: "clubs", files: [{ path: "campaigns/clubs/config.yaml", text: "slug: clubs" }] });
  assert.equal(taken.status, 409);
  const elsewhere = await save(cookie, { new_campaign: "demo2", files: [
    { path: "campaigns/demo2/config.yaml", text: "slug: demo2" },
    { path: "campaigns/clubs/captions.txt", text: "hijack" },
  ] });
  assert.equal(elsewhere.status, 403);
  for (const bad of ["../x", "Demo", "a b", "_parked"]) {
    assert.equal((await save(cookie, { new_campaign: bad, files })).status, 400, bad);
  }
});

test("clip libraries are listed by name only for asset releases", async () => {
  const cookie = await login();
  const calls = mockGithub((url) => (url.includes("assets-none")
    ? new Response("{}", { status: 404 })
    : ok({ assets: [{ name: "hook_01.mp4", size: 5, browser_download_url: "https://x/hook_01.mp4", uploader: { login: "n" } }] })));
  const res = await call("assets?tag=assets-clubs", { cookie });
  assert.deepEqual(await res.json(), { assets: [{ name: "hook_01.mp4", size: 5, url: "https://x/hook_01.mp4" }] });
  assert.deepEqual(await (await call("assets?tag=assets-none", { cookie })).json(), { assets: [] });
  for (const tag of ["render-clubs-2026-11-10", "v1.0", "assets-../x", ""]) {
    assert.equal((await call(`assets?tag=${encodeURIComponent(tag)}`, { cookie })).status, 400, tag);
  }
  assert.equal(calls.length, 2);
});

test("only known workflows start, with only well-formed inputs", async () => {
  const cookie = await login();
  const calls = mockGithub(() => new Response(null, { status: 204 }));
  const bad = [
    { workflow: "cleanup", inputs: {} },
    { workflow: "render", inputs: { campaign: "a; rm -rf /" } },
    { workflow: "render", inputs: { discard: "all" } },
    { workflow: "queue", inputs: { video_id: "$(curl evil)" } },
    { workflow: "queue", inputs: { account: "a b" } },
    { workflow: "../../x", inputs: {} },
  ];
  for (const body of bad) {
    assert.equal((await call("run", { method: "POST", cookie, body })).status, 400, JSON.stringify(body));
  }
  assert.equal(calls.length, 0);

  const res = await call("run", {
    method: "POST", cookie,
    body: { workflow: "queue", inputs: { campaign: "clubs", discard: "pushed", video_id: "3eb6087b", account: "nickdotname_tt" } },
  });
  assert.equal(res.status, 200);
  assert.ok(calls[0].url.endsWith("/actions/workflows/queue.yml/dispatches"));
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    ref: "main",
    inputs: { campaign: "clubs", discard: "pushed", video_id: "3eb6087b", account: "nickdotname_tt" },
  });
});

test("state returns campaign files and never the token", async () => {
  const cookie = await login();
  mockGithub((url) => {
    if (url.includes("/git/trees/")) {
      return ok({ tree: [
        { type: "blob", path: "accounts.yaml" },
        { type: "blob", path: "campaigns/clubs/config.yaml" },
        { type: "blob", path: "campaigns/clubs/history.json" },
        { type: "blob", path: "campaigns/_parked/config.yaml" },
        { type: "blob", path: "src/cli.py" },
        { type: "blob", path: ".env" },
      ] });
    }
    return ok({ sha: "abc", encoding: "base64", content: Buffer.from("slug: clubs — ok\n").toString("base64") });
  });
  const res = await call("state", { cookie });
  const text = await res.text();
  assert.equal(res.status, 200);
  assert.ok(!text.includes("ghp_secret"));
  const body = JSON.parse(text);
  assert.deepEqual(body.campaigns, ["clubs"]);
  assert.deepEqual(body.files.map((f) => f.path), ["accounts.yaml", "campaigns/clubs/config.yaml"]);
  assert.equal(body.files[1].text, "slug: clubs — ok\n");
});
