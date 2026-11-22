// Close Quarters bio links: one short link per Instagram account, each counting its own clicks.
//
//   https://<worker>/<source>        counts a click for <source>, then sends the visitor on to TARGET
//   https://<worker>/stats           the counts as JSON: { "<yyyy-mm-dd>": { "<source>": clicks } }
//
// Sources are the accounts' short names (psy, nostalgia, cq, dc); anything else is counted as "other".
// Link-preview robots (Instagram's own, search engines) are sent on without being counted.
// Needs a KV namespace bound as CLICKS. TARGET is a plain-text variable; it defaults to the band site.

const SOURCES = new Set(["psy", "nostalgia", "cq", "dc"]);
const ROBOT = /bot|crawl|spider|facebookexternalhit|meta-externalagent|preview|slurp|curl|python|wget/i;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/+|\/+$/g, "").toLowerCase();
    const target = env.TARGET || "https://closequarters.vip/";

    if (path === "stats") {
      const out = {};
      let cursor;
      do {
        const page = await env.CLICKS.list({ cursor });
        for (const k of page.keys) {
          const [day, src] = k.name.split("|");
          (out[day] = out[day] || {})[src] = Number(await env.CLICKS.get(k.name)) || 0;
        }
        cursor = page.list_complete ? undefined : page.cursor;
      } while (cursor);
      return new Response(JSON.stringify(out, null, 1), {
        headers: { "content-type": "application/json", "cache-control": "no-store", "access-control-allow-origin": "*" },
      });
    }
    if (path === "favicon.ico" || path === "robots.txt") return new Response("", { status: 404 });

    const src = SOURCES.has(path) ? path : path ? "other" : "direct";
    const ua = request.headers.get("user-agent") || "";
    if (!ROBOT.test(ua) && request.method === "GET") {
      const day = new Date().toISOString().slice(0, 10);
      const key = `${day}|${src}`;
      ctx.waitUntil((async () => {
        const n = Number(await env.CLICKS.get(key)) || 0;
        await env.CLICKS.put(key, String(n + 1));
      })());
    }
    const dest = new URL(target);
    dest.searchParams.set("ref", src);
    return Response.redirect(dest.toString(), 302);
  },
};
