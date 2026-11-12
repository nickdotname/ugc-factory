// Local preview: `node dashboard/test/dev-server.mjs`, then open
// http://localhost:8788 (password: dev).
//
// Serves the page and runs the real function, with GitHub replaced by this
// checkout's own files. Saves land in memory only: nothing is written to
// disk and nothing touches the network, so it is safe to click everything.
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { onRequest } from "../functions/api/[[path]].js";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const site = join(here, "..");
const env = { DASH_PASSWORD: process.env.DASH_PASSWORD || "dev", GITHUB_TOKEN: "local" };
const port = Number(process.env.PORT || 8788);

export const saved = new Map();      // path -> text, for anything "committed" this run
const trees = new Map();      // fake tree sha -> entries waiting on a commit
const staged = new Map();     // inbox tag -> files dropped, not yet checked
const holding = new Map();    // release id -> inbox tag
const library = new Map();    // assets tag -> files added this run
let assetIds = 0;
const ingestRuns = [];        // what the upload check has done, oldest first
export const log = [];        // what the page asked GitHub to do

const sha = (text) => createHash("sha1").update(`blob ${Buffer.byteLength(text)}\0${text}`).digest("hex");
const read = (path) => (saved.has(path) ? saved.get(path) : readFileSync(join(root, path), "utf8"));

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if ([".git", "work", "inbox", ".venv", "node_modules"].includes(name)) continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out); else out.push(relative(root, full));
  }
  return out;
}

const listing = () => [...new Set([...walk(root).filter((p) => /^(campaigns\/|accounts\.yaml$)/.test(p)), ...saved.keys()])]
  .map((path) => ({ type: "blob", path, sha: sha(read(path)) }));

globalThis.fetch = async (url, init = {}) => {
  const path = String(url).replace(/^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+/, "");
  const method = init.method || "GET";
  const reply = (body, status = 200) => new Response(JSON.stringify(body), { status });
  if (method !== "GET" && typeof init.body === "string") log.push({ method, path, body: JSON.parse(init.body) });

  if (path.startsWith("/git/ref/")) return reply({ object: { sha: "head" } });
  if (path.startsWith("/git/commits/")) return reply({ tree: { sha: "base" } });
  if (path.startsWith("/git/trees/") && method === "GET") return reply({ tree: listing() });
  if (path === "/git/trees") {
    const id = `tree${trees.size + 1}`;
    trees.set(id, JSON.parse(init.body).tree);
    return reply({ sha: id }, 201);
  }
  if (path === "/git/commits") return reply({ sha: JSON.parse(init.body).tree }, 201);
  if (path.startsWith("/git/refs/")) {
    for (const entry of trees.get(JSON.parse(init.body).sha) || []) saved.set(entry.path, entry.content);
    return reply({});
  }
  if (path.startsWith("/contents/")) {
    const file = decodeURIComponent(path.slice(10).split("?")[0]);
    const text = read(file);
    return reply({ sha: sha(text), encoding: "base64", content: Buffer.from(text).toString("base64") });
  }
  if (String(url).startsWith("https://uploads.github.com/")) {
    const name = new URL(String(url)).searchParams.get("name");
    const tag = holding.get(Number(String(url).match(/releases\/(\d+)\//)[1]));
    staged.get(tag).push({ id: ++assetIds, name, size: init.body.byteLength, browser_download_url: `https://example.test/${name}` });
    log.push({ method: "UPLOAD", path: name, bytes: init.body.byteLength });
    return reply({ name }, 201);
  }
  if (path === "/releases" && method === "POST") {
    const tag = JSON.parse(init.body).tag_name;
    if (!staged.has(tag)) { staged.set(tag, []); holding.set(holding.size + 1, tag); }
    return reply({ id: [...holding].find(([, t]) => t === tag)[0] }, 201);
  }
  if (path.startsWith("/releases/tags/")) {
    const tag = decodeURIComponent(path.slice("/releases/tags/".length));
    if (tag.startsWith("inbox-")) {
      if (!staged.has(tag)) return reply({}, 404);
      return reply({ id: [...holding].find(([, t]) => t === tag)[0], assets: staged.get(tag) });
    }
    // The existing campaign has a library; anything new starts empty.
    const seeded = tag.startsWith("assets-clubs") ? ["hook_01.mp4", "hook_02.mp4", "body_01.mp4", "music_01.mp3"] : [];
    return reply({ assets: [...seeded.map((name) => ({ name, size: 4_200_000, browser_download_url: `https://example.test/${name}` })), ...(library.get(tag) || [])] });
  }
  if (path.startsWith("/releases/assets/") && method === "DELETE") {
    const id = Number(path.split("/").pop());
    for (const files of staged.values()) {
      const at = files.findIndex((f) => f.id === id);
      if (at >= 0) files.splice(at, 1);
    }
    return new Response(null, { status: 204 });
  }
  if (path.includes("/workflows/ingest.yml/runs")) {
    return reply({ workflow_runs: ingestRuns.slice(-5).reverse() });
  }
  if (path.includes("/workflows/ingest.yml/dispatches") && process.env.INGEST_BROKEN) {
    // The job that never gets going: recorded, fails at startup, moves nothing.
    ingestRuns.push({ name: "ingest", event: "workflow_dispatch", status: "completed", conclusion: "startup_failure", created_at: new Date().toISOString(), html_url: "https://example.test/ingest" });
    return new Response(null, { status: 204 });
  }
  if (path.includes("/workflows/ingest.yml/dispatches")) {
    // Stand in for the ingest job: a moment later, everything staged has
    // been checked, renamed and added to the library.
    const run = { name: "ingest", event: "workflow_dispatch", status: "in_progress", conclusion: null, run_started_at: new Date().toISOString(), html_url: "https://example.test/ingest" };
    ingestRuns.push(run);
    setTimeout(() => {
      run.status = "completed"; run.conclusion = "success";
      for (const [tag, files] of staged) {
        const dest = `assets-${tag.slice(6)}`;
        const have = library.get(dest) || [];
        for (const f of files.splice(0)) {
          if (f.name.startsWith("rejected__")) { files.push(f); continue; }
          // A file with "broken" in its name stands in for one ffprobe refuses.
          if (f.name.includes("broken")) {
            files.push({ ...f, id: f.id, name: `rejected__${f.name}`, label: "This file has no video in it." });
            continue;
          }
          const kind = f.name.split("__")[0];
          const n = have.filter((x) => x.name.startsWith(kind)).length + 1;
          const name = `${kind}_${String(n).padStart(2, "0")}${f.name.slice(f.name.lastIndexOf("."))}`;
          have.push({ name, size: f.size, browser_download_url: `https://example.test/${name}` });
        }
        library.set(dest, have);
      }
    }, Number(process.env.INGEST_MS || 1500));
    return new Response(null, { status: 204 });
  }
  if (path.includes("/dispatches")) return new Response(null, { status: 204 });
  if (path.startsWith("/actions/runs")) {
    return reply({ workflow_runs: [
      { name: "render", event: "schedule", status: "completed", conclusion: "success", run_started_at: new Date().toISOString(), html_url: "https://example.test/1" },
      { name: "metrics", event: "schedule", status: "completed", conclusion: "failure", run_started_at: new Date().toISOString(), html_url: "https://example.test/2" },
    ] });
  }
  return reply({}, 404);
};

const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json" };

export const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${port}`);
  if (url.pathname.startsWith("/api/")) {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const request = new Request(url, {
      method: req.method, headers: req.headers,
      body: ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks),
    });
    const out = await onRequest({ request, env });
    res.writeHead(out.status, Object.fromEntries(out.headers));
    res.end(await out.text());
    return;
  }
  const file = join(site, url.pathname === "/" ? "index.html" : url.pathname);
  if (!file.startsWith(site) || !existsSync(file) || statSync(file).isDirectory()) { res.writeHead(404); res.end("not found"); return; }
  res.writeHead(200, { "content-type": `${TYPES[extname(file)] || "application/octet-stream"}; charset=utf-8` });
  res.end(readFileSync(file));
}).listen(port, () => console.log(`http://localhost:${port}  (password: dev)`));
