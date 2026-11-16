// Run with: node --test dashboard/test
//
// The function is the only thing standing between the internet and a token
// that can change what posts. These tests are about what it refuses.
import assert from "node:assert/strict";
import { test } from "node:test";

import { onRequest } from "../functions/api/[[path]].js";
import { onRequest as publicVideo } from "../functions/v/[[path]].js";

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
  assert.deepEqual(await res.json(), { assets: [{ name: "hook_01.mp4", size: 5, note: "", url: "/api/media?tag=assets-clubs&name=hook_01.mp4" }] });
  assert.deepEqual(await (await call("assets?tag=assets-none", { cookie })).json(), { assets: [] });
  for (const tag of ["render-clubs-2026-11-10", "v1.0", "assets-../x", "inbox-../x", ""]) {
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

// ------------------------------------------------------------------ uploads

function drop(path, { cookie, bytes = new Uint8Array([1, 2, 3]), headers = {} } = {}) {
  const init = { method: "POST", body: bytes, headers: { "x-ugc": "1", "content-type": "application/octet-stream", ...headers } };
  if (cookie) init.headers.cookie = cookie;
  return onRequest({ request: new Request(`https://x.test/api/${path}`, init), env });
}

test("an upload needs a session and the page's own header", async () => {
  assert.equal((await drop("upload?tag=assets-a&kind=hook&name=a.mp4")).status, 401);
  const cookie = await login();
  assert.equal((await drop("upload?tag=assets-a&kind=hook&name=a.mp4", { cookie, headers: { "x-ugc": "" } })).status, 400);
});

test("only video and audio files are taken, each in its own place", async () => {
  const cookie = await login();
  const calls = mockGithub(() => ok({ id: 7 }));
  const refused = [
    "upload?tag=assets-a&kind=hook&name=notes.pdf",
    "upload?tag=assets-a&kind=hook&name=song.mp3",       // audio in a video slot
    "upload?tag=assets-a&kind=music&name=clip.mp4",      // video in a music slot
    "upload?tag=assets-a&kind=hook&name=evil.mp4.exe",
    "upload?tag=assets-a&kind=hook&name=noextension",
  ];
  for (const path of refused) assert.equal((await drop(path, { cookie })).status, 415, path);
  for (const path of [
    "upload?tag=inbox-a&kind=hook&name=a.mp4",           // straight into a holding area
    "upload?tag=render-a-2026&kind=hook&name=a.mp4",
    "upload?tag=assets-a&kind=script&name=a.mp4",
  ]) assert.equal((await drop(path, { cookie })).status, 400, path);
  assert.equal((await drop("upload?tag=assets-a&kind=hook&name=a.mp4", { cookie, bytes: new Uint8Array(0) })).status, 400);
  assert.equal(calls.length, 0, "nothing reached GitHub");
});

test("a dropped file lands in the holding area, never the library", async () => {
  const cookie = await login();
  const calls = mockGithub((url, init) => {
    if (url.includes("/releases/tags/inbox-cq-song")) return new Response("{}", { status: 404 });
    if (url.endsWith("/releases") && init.method === "POST") return ok({ id: 42 });
    if (url.startsWith("https://uploads.github.com/")) return ok({ name: "x" });
    return new Response("{}", { status: 500 });
  });
  const res = await drop("upload?tag=assets-cq-song&kind=music&name=" + encodeURIComponent("My Song (final) v2!.MP3"), { cookie });
  assert.equal(res.status, 200);
  const { name } = await res.json();
  assert.match(name, /^music__[0-9a-f]{8}__My_Song_final_v2_\.mp3$/);
  assert.equal(JSON.parse(calls[1].init.body).tag_name, "inbox-cq-song");
  const sent = calls[2];
  assert.ok(sent.url.startsWith("https://uploads.github.com/repos/nickdotname/ugc-factory/releases/42/assets?name=music__"));
  assert.equal(sent.init.body.byteLength, 3);
  assert.equal(sent.init.headers.authorization, "Bearer ghp_secret");
});

test("the ingest job can be started for one creative only with clean names", async () => {
  const cookie = await login();
  const calls = mockGithub(() => new Response(null, { status: 204 }));
  assert.equal((await call("run", { method: "POST", cookie, body: { workflow: "ingest", inputs: { campaign: "cq", creative: "x; ls" } } })).status, 400);
  assert.equal((await call("run", { method: "POST", cookie, body: { workflow: "ingest", inputs: { campaign: "cq", creative: "sunday_song" } } })).status, 200);
  assert.equal(calls.length, 1);
});

test("only a refused upload can be cleared, and only from a holding area", async () => {
  const cookie = await login();
  const calls = mockGithub((url, init) => (init.method === "DELETE"
    ? new Response(null, { status: 204 })
    : ok({ assets: [{ id: 7, name: "rejected__hook__1a2b3c4d__clip.mp4" }, { id: 8, name: "hook__5e6f7a8b__fine.mp4" }] })));
  const bad = [
    { tag: "assets-clubs", name: "rejected__hook__1a2b3c4d__clip.mp4" },
    { tag: "inbox-clubs", name: "hook__5e6f7a8b__fine.mp4" },
    { tag: "inbox-../x", name: "rejected__x.mp4" },
    { tag: "render-clubs-2026-11-10", name: "rejected__x.mp4" },
  ];
  for (const body of bad) {
    assert.equal((await call("discard", { method: "POST", cookie, body })).status, 400, JSON.stringify(body));
  }
  assert.equal(calls.length, 0);
  assert.equal((await call("discard", { method: "POST", body: bad[0] })).status, 401);

  const res = await call("discard", { method: "POST", cookie, body: { tag: "inbox-clubs", name: "rejected__hook__1a2b3c4d__clip.mp4" } });
  assert.equal(res.status, 200);
  assert.equal(calls.at(-1).init.method, "DELETE");
  assert.ok(calls.at(-1).url.endsWith("/releases/assets/7"));
});

test("the run history can be narrowed to one known job", async () => {
  const cookie = await login();
  const calls = mockGithub(() => ok({ workflow_runs: [
    { name: "ingest", event: "workflow_dispatch", status: "completed", conclusion: "startup_failure", run_started_at: null, created_at: "2026-11-11T20:33:18Z", html_url: "https://x/1" },
  ] }));
  assert.equal((await call("runs?workflow=../../x", { cookie })).status, 400);
  assert.equal(calls.length, 0);
  const res = await call("runs?workflow=ingest", { cookie });
  assert.ok(calls[0].url.includes("/actions/workflows/ingest.yml/runs?"));
  assert.deepEqual((await res.json()).runs[0], {
    name: "ingest", event: "workflow_dispatch", status: "completed", conclusion: "startup_failure",
    started: "2026-11-11T20:33:18Z", url: "https://x/1",
  });
});

// A private repository's files, as GitHub serves them: the release lists the
// asset, the asset answers with a redirect, the redirect serves the bytes.
function mockStore(bytes = "0123456789") {
  return mockGithub((url, init) => {
    if (url.includes("/releases/tags/")) {
      return ok({ assets: [
        { id: 11, name: "hook_01.mp4", size: bytes.length },
        { id: 12, name: "11111111-2222-3333-4444-555555555555.mp4", size: bytes.length },
      ] });
    }
    if (url.includes("/releases/assets/")) return new Response(null, { status: 302, headers: { location: "https://signed.test/file?sig=abc" } });
    if (url.startsWith("https://signed.test/")) {
      const range = new Headers(init.headers || {}).get("range");
      return range
        ? new Response(bytes.slice(0, 2), { status: 206, headers: { "content-range": `bytes 0-1/${bytes.length}`, "content-length": "2", "content-type": "application/octet-stream" } })
        : new Response(bytes, { status: 200, headers: { "content-length": String(bytes.length), "content-type": "application/octet-stream" } });
    }
    return new Response("unexpected", { status: 500 });
  });
}

test("a clip plays through the site, with the token kept off the signed address", async () => {
  const cookie = await login();
  assert.equal((await call("media?tag=assets-clubs&name=hook_01.mp4")).status, 401);

  const calls = mockStore();
  const res = await call("media?tag=assets-clubs&name=hook_01.mp4", { cookie });
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "video/mp4");
  assert.equal(res.headers.get("accept-ranges"), "bytes");
  assert.equal(await res.text(), "0123456789");
  const signed = calls.find((c) => c.url.startsWith("https://signed.test/"));
  assert.equal(new Headers(signed.init.headers || {}).get("authorization"), null);
  assert.equal(calls.find((c) => c.url.includes("/releases/assets/11")).init.redirect, "manual");

  const part = await call("media?tag=assets-clubs&name=hook_01.mp4", { cookie, headers: { range: "bytes=0-1" } });
  assert.equal(part.status, 206);
  assert.equal(part.headers.get("content-range"), "bytes 0-1/10");
  assert.equal(await part.text(), "01");
});

test("the media route only reaches clips, by plain file name", async () => {
  const cookie = await login();
  const calls = mockStore();
  for (const q of [
    "tag=v1.0&name=hook_01.mp4", "tag=assets-../x&name=hook_01.mp4", "tag=assets-clubs&name=../config.yaml",
    "tag=assets-clubs&name=hook_01.exe", "tag=assets-clubs&name=", "tag=assets-clubs&name=a/b.mp4",
  ]) assert.equal((await call(`media?${q}`, { cookie })).status, 400, q);
  assert.equal(calls.length, 0);
  assert.equal((await call("media?tag=assets-clubs&name=missing.mp4", { cookie })).status, 404);
});

const video = (path, init = {}, e = env) => publicVideo({ request: new Request(`https://x.test${path}`, init), env: e });
const RENDER = "/v/render-clubs-2026-11-11/11111111-2222-3333-4444-555555555555.mp4";

test("a rendered video is readable without signing in, so Buffer can fetch it", async () => {
  mockStore();
  const res = await video(RENDER);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get("content-type"), "video/mp4");
  assert.equal(await res.text(), "0123456789");

  const head = await video(RENDER, { method: "HEAD" });
  assert.equal(head.status, 200);
  assert.equal(head.headers.get("content-length"), "10");

  const part = await video(RENDER, { headers: { range: "bytes=0-1" } });
  assert.equal(part.status, 206);
});

test("the public address serves finished renders and nothing else", async () => {
  const calls = mockStore();
  for (const path of [
    "/v/assets-clubs/hook_01.mp4",                                   // the clip library
    "/v/inbox-clubs/hook__1a2b3c4d__x.mp4",                          // the holding area
    "/v/render-clubs-2026-11-11/hook_01.mp4",                        // not a render's name
    "/v/render-clubs-2026-11-11/..%2F..%2Fconfig.yaml",
    "/v/render-clubs-2026-11-11",                                    // no listing
    "/v/render-clubs-2026-11-11/11111111-2222-3333-4444-555555555555.mp4/extra",
  ]) assert.equal((await video(path)).status, 404, path);
  assert.equal(calls.length, 0);
  assert.equal((await video(RENDER, { method: "POST" })).status, 405);
  assert.equal((await video(RENDER, { method: "DELETE" })).status, 405);
  assert.equal((await video(RENDER, {}, {})).status, 503);
  // A well-formed name that does not exist is a plain 404, not an error page.
  assert.equal((await video("/v/render-clubs-2026-11-11/99999999-2222-3333-4444-555555555555.mp4")).status, 404);
});
