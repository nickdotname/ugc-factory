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

test("nothing is readable without signing in", async () => {
  for (const path of ["state", "runs"]) assert.equal((await call(path)).status, 401);
  const write = await call("file", { method: "PUT", body: { path: "campaigns/a/config.yaml", text: "x" } });
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
  const res = await call("file", {
    method: "PUT", cookie, headers: { "x-ugc": "0" },
    body: { path: "campaigns/a/config.yaml", text: "x" },
  });
  assert.equal(res.status, 400);
});

test("only the editable files can be written", async () => {
  const cookie = await login();
  const calls = mockGithub(() => ok({ content: { sha: "new" } }));
  const refused = [
    "accounts.yaml", "campaigns/a/queue.json", "campaigns/a/history.json",
    "src/cli.py", ".github/workflows/render.yml", "campaigns/a/../../src/cli.py",
    "campaigns/a/config.yaml/../../../src/cli.py", "ugc",
  ];
  for (const path of refused) {
    const res = await call("file", { method: "PUT", cookie, body: { path, text: "x: 1" } });
    assert.equal(res.status, 403, path);
  }
  assert.equal(calls.length, 0, "nothing reached GitHub");

  const allowed = [
    "campaigns/closequarters/config.yaml", "campaigns/closequarters/lineup.yaml",
    "campaigns/closequarters/creatives/song_a/captions.txt",
    "campaigns/clubs/captions/tiktok.txt",
  ];
  for (const path of allowed) {
    const res = await call("file", { method: "PUT", cookie, body: { path, text: "x: 1", sha: "old" } });
    assert.equal(res.status, 200, path);
  }
  const sent = JSON.parse(calls[0].init.body);
  assert.equal(sent.sha, "old");
  assert.equal(sent.branch, "main");
  assert.equal(calls[0].init.headers.authorization, "Bearer ghp_secret");
});

test("an empty save is refused", async () => {
  const cookie = await login();
  const res = await call("file", { method: "PUT", cookie, body: { path: "campaigns/a/lineup.yaml", text: "  " } });
  assert.equal(res.status, 400);
});

test("a stale edit is reported, not forced", async () => {
  const cookie = await login();
  mockGithub(() => new Response("{}", { status: 409 }));
  const res = await call("file", { method: "PUT", cookie, body: { path: "campaigns/a/lineup.yaml", text: "posts: []", sha: "old" } });
  assert.equal(res.status, 409);
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
