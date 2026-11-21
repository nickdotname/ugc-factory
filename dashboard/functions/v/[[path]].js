// Rendered videos (and carousel slides), readable without a login: /v/<release tag>/<file>.mp4|.jpg
//
// Buffer, Instagram, TikTok and YouTube all fetch a post's video by URL, and
// none of them can sign in to a private repository. This is the address the
// pipeline hands them instead of the GitHub link.
//
// Deliberately narrow: finished renders only (never the clip library or the
// upload holding area), read only, and only by exact name. A render's name
// is a random 122-bit id, so a link cannot be guessed, and nothing here
// lists what exists.

import { streamAsset } from "../../lib/media.js";

const DEFAULT_REPO = "nickdotname/ugc-factory";
const TAG = /^render-[a-z0-9_-]{1,64}-\d{4}-\d{2}-\d{2}$/;
const NAME = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(-[a-z0-9_]{1,64})?\.(mp4|jpg)$/;

export async function onRequest({ request, env }) {
  const text = (body, status) => new Response(body, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
  if (!["GET", "HEAD"].includes(request.method)) return text("Method not allowed", 405);
  if (!env.GITHUB_TOKEN) return text("Not set up", 503);

  const parts = new URL(request.url).pathname.split("/").filter(Boolean);   // ["v", tag, name]
  if (parts.length !== 3 || !TAG.test(parts[1]) || !NAME.test(parts[2])) return text("Not found", 404);

  const repo = env.GITHUB_REPO || DEFAULT_REPO;
  const gh = (path, init = {}) => fetch(`https://api.github.com/repos/${repo}${path}`, {
    ...init,
    headers: {
      authorization: `Bearer ${env.GITHUB_TOKEN}`,
      accept: "application/vnd.github+json",
      "x-github-api-version": "2022-11-28",
      "user-agent": "ugc-factory-dashboard",
      ...(init.headers || {}),
    },
  });
  // A render never changes once uploaded, so anything in front may keep it.
  return streamAsset(gh, parts[1], parts[2], request, { cache: "public, max-age=86400, immutable" });
}
