// Serving a stored clip out of a private repository.
//
// The repo's Releases hold every clip and every rendered video, and a private
// repo's download links only open for someone signed in to GitHub. So the
// site fetches the file with its own token and passes the bytes through.
// Used two ways: behind the login for previewing the library, and without a
// login for rendered videos, which Buffer and the networks have to fetch.

const TYPES = {
  mp4: "video/mp4", mov: "video/quicktime", m4v: "video/x-m4v", webm: "video/webm",
  mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav", aac: "audio/aac", ogg: "audio/ogg",
};

const plain = (text, status) => new Response(text, { status, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });

/**
 * Stream one release asset. `gh(path, init)` is the authenticated GitHub
 * fetch for this repo. Honours Range, so a player can seek and Safari, which
 * will not play a video it cannot range over, plays at all.
 */
export async function streamAsset(gh, tag, name, request, { cache = "private, max-age=300" } = {}) {
  const release = await gh(`/releases/tags/${tag}`);
  if (release.status === 404) return plain("Not found", 404);
  if (!release.ok) return plain(`GitHub ${release.status} finding the file`, 502);
  const asset = ((await release.json()).assets || []).find((a) => a.name === name);
  if (!asset) return plain("Not found", 404);

  const type = TYPES[name.split(".").pop().toLowerCase()] || "application/octet-stream";
  const headers = {
    "content-type": type,
    "accept-ranges": "bytes",
    "cache-control": cache,
    "x-content-type-options": "nosniff",
    "content-disposition": "inline",
  };
  if (request.method === "HEAD") {
    return new Response(null, { status: 200, headers: { ...headers, "content-length": String(asset.size) } });
  }

  // GitHub answers with a redirect to a short-lived signed address. Follow it
  // by hand: the token must not travel there, and the Range header must.
  const hop = await gh(`/releases/assets/${asset.id}`, { headers: { accept: "application/octet-stream" }, redirect: "manual" });
  const signed = hop.headers.get("location");
  const range = request.headers.get("range");
  let upstream = hop;
  if (signed) upstream = await fetch(signed, { headers: range ? { range } : {} });
  if (!upstream.ok) return plain(`GitHub ${upstream.status} sending the file`, 502);

  for (const h of ["content-length", "content-range", "etag", "last-modified"]) {
    const v = upstream.headers.get(h);
    if (v) headers[h] = v;
  }
  return new Response(upstream.body, { status: upstream.status === 206 ? 206 : 200, headers });
}
