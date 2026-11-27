// Close Quarters bio links: one short link per Instagram account, each counting its own taps.
//
//   https://<worker>/<source>        counts a tap for <source>, then sends the visitor on to TARGET (the listen page)
//   https://<worker>/stats           the last 7 days as JSON (?days=14 for more, 14 at most):
//                                      { "<yyyy-mm-dd>": { "<source>": taps },      one entry per day, {} when nobody tapped
//                                        "week": { "<source>": taps in the window },
//                                        "last": { "<source>": { "at": "<iso time>", "app": "instagram" | "browser" } } }
//                                    "last" is how a dead counter is told from a quiet week: it is the time of the latest
//                                    tap (studio/clicks.json held one day, 2026-11-22, for a week and nothing said why).
//
// Sources are one short name per campaign (the table in README.md); anything else is counted as "other", the bare
// host as "direct", and every path redirects to the same place. Link-preview robots (Instagram's own, search
// engines) are sent on without being counted. Needs a KV namespace bound as CLICKS. TARGET is a plain-text
// variable; it defaults to the band site.

const SOURCES = new Set([
  "cq", "dc", "psy", "nostalgia", "math", "glitch", "ascii", "physics", "earth", "retro", "rocket", "loose",
  "vintage", "nyc", "tinycode", "cinema", "petri", "illusions", "races", "8bit", "notes", "toon", "zoom", "date",
  "lowpoly", "college", "eyetrick", "fourier", "her", "him",
]);
const ROBOT = /bot|crawl|spider|facebookexternalhit|meta-externalagent|preview|slurp|curl|python|wget/i;
const KEEP = 120 * 86400;        // seconds a day's counts stay in KV (the clients keep their own history)
const MAX_DAYS = 14;             // a Worker may do 1,000 KV operations per request: 14 days x 30 sources fits

const day = (t) => new Date(t).toISOString().slice(0, 10);

async function count(env, src, ua) {
  const key = `${day(Date.now())}|${src}`;
  const n = Number(await env.CLICKS.get(key)) || 0;
  await env.CLICKS.put(key, String(n + 1), { expirationTtl: KEEP });
  // the latest tap per source: when, and from which kind of app (never who)
  const app = /instagram/i.test(ua) ? "instagram" : "browser";
  await env.CLICKS.put(`last|${src}`, JSON.stringify({ at: new Date().toISOString(), app }), { expirationTtl: KEEP });
}

async function stats(env, url) {
  const days = Math.min(MAX_DAYS, Math.max(1, Number(url.searchParams.get("days")) || 7));
  const out = {}, week = {};
  for (let k = days - 1; k >= 0; k--) {
    const d = day(Date.now() - k * 86400e3);
    out[d] = {};
    const page = await env.CLICKS.list({ prefix: d + "|" });      // fewer than 1,000 keys a day: one page
    for (const key of page.keys) {
      const src = key.name.slice(d.length + 1);
      const n = Number(await env.CLICKS.get(key.name)) || 0;
      out[d][src] = n;
      week[src] = (week[src] || 0) + n;
    }
  }
  const last = {};
  for (const key of (await env.CLICKS.list({ prefix: "last|" })).keys) {
    try { last[key.name.slice(5)] = JSON.parse(await env.CLICKS.get(key.name)); } catch (e) { /* an old or odd value */ }
  }
  return new Response(JSON.stringify({ ...out, week, last }, null, 1), {
    headers: { "content-type": "application/json", "cache-control": "no-store", "access-control-allow-origin": "*" },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/+|\/+$/g, "").toLowerCase();
    const target = env.TARGET || "https://closequarters.vip/";

    if (path === "stats") return stats(env, url);
    if (path === "favicon.ico" || path === "robots.txt") return new Response("", { status: 404 });

    const src = SOURCES.has(path) ? path : path ? "other" : "direct";
    const ua = request.headers.get("user-agent") || "";
    if (!ROBOT.test(ua) && request.method === "GET") ctx.waitUntil(count(env, src, ua));
    const dest = new URL(target);
    dest.searchParams.set("ref", src);
    return Response.redirect(dest.toString(), 302);
  },
};
