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
  if (method !== "GET") log.push({ method, path, body: init.body ? JSON.parse(init.body) : null });

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
  if (path.startsWith("/releases/tags/")) {
    return reply({ assets: ["hook_01.mp4", "hook_02.mp4", "hook_03.mp4", "music_01.mp3"].map((name) => ({
      name, size: 1_000_000, browser_download_url: `https://example.test/${name}`,
    })) });
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
