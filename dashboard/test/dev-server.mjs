// Local preview: `node dashboard/test/dev-server.mjs` then open
// http://localhost:8788 (password: dev). Serves the page and runs the real
// function, with GitHub replaced by this checkout's own files — nothing is
// read from or written to the network, and "saving" only logs.
import { createServer } from "node:http";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, dirname, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { onRequest } from "../functions/api/[[path]].js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const env = { DASH_PASSWORD: process.env.DASH_PASSWORD || "dev", GITHUB_TOKEN: "local" };

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (name === ".git" || name === "work" || name === "inbox" || name === ".venv") continue;
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out); else out.push(relative(root, full));
  }
  return out;
}

globalThis.fetch = async (url, init = {}) => {
  const path = String(url).replace(/^https:\/\/api\.github\.com\/repos\/[^/]+\/[^/]+/, "");
  const reply = (body, status = 200) => new Response(JSON.stringify(body), { status });
  if (path.startsWith("/git/trees/")) {
    return reply({ tree: walk(root).map((p) => ({ type: "blob", path: p })) });
  }
  if (path.startsWith("/contents/") && (init.method || "GET") === "GET") {
    const file = decodeURIComponent(path.slice(10).split("?")[0]);
    return reply({ sha: "local", encoding: "base64", content: readFileSync(join(root, file)).toString("base64") });
  }
  if (path.startsWith("/contents/")) { console.log("would save", path); return reply({ content: { sha: "local2" } }); }
  if (path.includes("/dispatches")) { console.log("would run", path, init.body); return new Response(null, { status: 204 }); }
  if (path.startsWith("/actions/runs")) return reply({ workflow_runs: [] });
  return reply({}, 404);
};

createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost:8788");
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
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(readFileSync(join(root, "dashboard", "index.html")));
}).listen(8788, () => console.log("http://localhost:8788  (password: dev)"));
