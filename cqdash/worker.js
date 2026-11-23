// dashboard.closequarters.vip: a Cloudflare Worker that serves this folder's page and numbers straight from the
// repository's main branch, so a change to the page is live as soon as it is merged and the numbers are as fresh as
// the publish job's last run (it rewrites cqdash/data.json every 15 minutes).
// Sign-in is Cloudflare Access in front of the domain (Zero Trust -> Access -> Applications): only the allowed emails
// get a one-time code. The workers.dev address is switched off, and anything not arriving on the dashboard's own
// host through Access is refused here too.
const RAW = 'https://raw.githubusercontent.com/nickdotname/ugc-factory/main/cqdash/';
const HOST = 'dashboard.closequarters.vip';

export default {
  async fetch(req) {
    const url = new URL(req.url);
    if (url.hostname !== HOST || !req.headers.get('cf-access-jwt-assertion')) return new Response('Not found', { status: 404 });
    const file = url.pathname === '/data.json' ? 'data.json' : 'index.html';
    const r = await fetch(RAW + file + '?t=' + Math.floor(Date.now() / 60000), { cf: { cacheTtl: 60 } });
    if (!r.ok) return new Response('The dashboard could not be loaded (' + r.status + '). Try again in a minute.', { status: 502 });
    return new Response(r.body, { headers: {
      'content-type': file === 'data.json' ? 'application/json; charset=utf-8' : 'text/html; charset=utf-8',
      'cache-control': 'no-store', 'x-robots-tag': 'noindex, nofollow', 'referrer-policy': 'no-referrer' } });
  },
};
