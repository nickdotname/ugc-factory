// Close Quarters "Connect Instagram": closequarters.vip/connect*  (Cloudflare Worker "cq-connect")
//
// Lets an Instagram account be connected to the posting engine without anyone copying a token:
//   1. /connect?u=<handle>  sends the person to Meta's login (Unified login, the app's Instagram-compatible
//      configuration). They pick the account and tap Allow.
//   2. Meta sends them back to /connect/callback with a code (or, for the Instagram-compatible configuration,
//      the token in the URL fragment, which the page's script posts back here at once and strips from the URL).
//   3. The token is made long-lived, checked (whose account is it?), then ENCRYPTED to the GitHub job's public key
//      (cqconnect/public.pem in the repo: RSA-OAEP wraps a fresh AES-GCM key) and held in KV. This worker can
//      never read it again.
//   4. GitHub's "connect" job (scripts/connect_pickup.py) fetches /connect/pickup, decrypts with its private key,
//      saves the token as the account's secret, and deletes the item with the proof that only decryption reveals.
//
// Bindings: KV namespace CONNECT_KV. Secrets: META_APP_SECRET (the app's secret, Settings > Basic).
// Nothing secret lives in this file; the repo is public.

const APP_ID = '1880800686386898';
const CONFIG_ID = '1196481663031292';              // "Instagram API (Unified Login)", Instagram Login Compatible
const GRAPH = 'https://graph.facebook.com/v21.0';
const REPO_RAW = 'https://raw.githubusercontent.com/nickdotname/ugc-factory/main/';
const HOLD_SECONDS = 7 * 24 * 3600;

const page = (title, body, status = 200) => new Response(
  `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title>
<style>body{font:17px/1.45 -apple-system,system-ui,sans-serif;max-width:30em;margin:3em auto;padding:0 1.2em;color:#111}
h1{font-size:1.4em}code{background:#f2f2f2;padding:.1em .3em;border-radius:4px}a.b{display:inline-block;background:#111;color:#fff;
padding:.7em 1.2em;border-radius:10px;text-decoration:none}</style><h1>${title}</h1>${body}`,
  { status, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'referrer-policy': 'no-referrer' } });

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function getJSON(url, init) {
  const r = await fetch(url, init);
  let body = {};
  try { body = await r.json(); } catch (_) { /* not json */ }
  return { ok: r.ok, status: r.status, body };
}

function b64(buf) { return btoa(String.fromCharCode(...new Uint8Array(buf))); }

async function encryptForGitHub(payload) {
  const pem = await (await fetch(REPO_RAW + 'cqconnect/public.pem', { cf: { cacheTtl: 300 } })).text();
  const der = Uint8Array.from(atob(pem.replace(/-----[^-]+-----|\s/g, '')), (c) => c.charCodeAt(0));
  const rsa = await crypto.subtle.importKey('spki', der, { name: 'RSA-OAEP', hash: 'SHA-256' }, false, ['encrypt']);
  const aes = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, true, ['encrypt']);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, aes, new TextEncoder().encode(JSON.stringify(payload)));
  const key = await crypto.subtle.encrypt({ name: 'RSA-OAEP' }, rsa, await crypto.subtle.exportKey('raw', aes));
  return { key: b64(key), iv: b64(iv), data: b64(data) };
}

async function longLived(token, env) {
  // Facebook-format tokens (what Unified login gives) are exchanged with the app secret; Instagram-format ones
  // with ig_exchange_token. Either way, if the exchange is refused the token we have is kept as it is.
  const fb = await getJSON(`${GRAPH}/oauth/access_token?grant_type=fb_exchange_token&client_id=${APP_ID}`
    + `&client_secret=${encodeURIComponent(env.META_APP_SECRET)}&fb_exchange_token=${encodeURIComponent(token)}`);
  if (fb.ok && fb.body.access_token) return fb.body.access_token;
  const ig = await getJSON(`https://graph.instagram.com/access_token?grant_type=ig_exchange_token`
    + `&client_secret=${encodeURIComponent(env.META_APP_SECRET)}&access_token=${encodeURIComponent(token)}`);
  if (ig.ok && ig.body.access_token) return ig.body.access_token;
  return token;
}

async function whoIs(token) {
  // The Instagram professional account behind the token: try the Instagram host, then the Facebook host.
  const a = await getJSON(`https://graph.instagram.com/v21.0/me?fields=user_id,username&access_token=${encodeURIComponent(token)}`);
  if (a.ok && a.body.username) return { ig_id: String(a.body.user_id || a.body.id), username: a.body.username, host: 'instagram' };
  const b = await getJSON(`${GRAPH}/me?fields=id,username,name&access_token=${encodeURIComponent(token)}`);
  if (b.ok && b.body.username) return { ig_id: String(b.body.id), username: b.body.username, host: 'facebook' };
  const c = await getJSON(`${GRAPH}/me/accounts?fields=instagram_business_account{id,username}&access_token=${encodeURIComponent(token)}`);
  const iba = c.ok && (c.body.data || []).map((p) => p.instagram_business_account).filter(Boolean);
  if (iba && iba.length === 1) return { ig_id: String(iba[0].id), username: iba[0].username, host: 'facebook-page' };
  return null;
}

async function keep(token, expected, env) {
  const t = await longLived(token, env);
  const who = await whoIs(t);
  if (!who) return page('Could not read the account', '<p>Meta gave a token, but it does not say which Instagram account it is for. Nothing was kept.</p>', 400);
  if (expected && who.username.toLowerCase() !== expected.toLowerCase()) {
    return page('Wrong account', `<p>This link was for <b>@${esc(expected)}</b>, but you allowed <b>@${esc(who.username)}</b>. Nothing was kept. `
      + `Open the link again and pick <b>@${esc(expected)}</b>.</p>`, 400);
  }
  const proof = b64(crypto.getRandomValues(new Uint8Array(24)));
  const id = crypto.randomUUID();
  const sealed = await encryptForGitHub({ token: t, username: who.username, ig_id: who.ig_id, host: who.host, proof, at: new Date().toISOString() });
  const proofHash = b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(proof)));
  await env.CONNECT_KV.put('item:' + id, JSON.stringify({ ...sealed, proofHash }), { expirationTtl: HOLD_SECONDS });
  return page('Connected ✓', `<p><b>@${esc(who.username)}</b> is connected. GitHub picks the token up within a few minutes and saves it; `
    + `nobody sees it. You can close this page.</p>`);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '');
    const redirect = `${url.origin}/connect/callback`;

    if (path === '/connect') {
      const u = (url.searchParams.get('u') || '').replace(/^@/, '').trim();
      const state = b64(new TextEncoder().encode(JSON.stringify({ u, n: crypto.randomUUID() })));
      const login = `https://www.facebook.com/v21.0/dialog/oauth?client_id=${APP_ID}&config_id=${CONFIG_ID}`
        + `&redirect_uri=${encodeURIComponent(redirect)}&response_type=code&override_default_response_type=true&display=popup`
        + `&state=${encodeURIComponent(state)}`;
      if (url.searchParams.get('go') === '1') return Response.redirect(login, 302);
      return page(u ? `Connect @${esc(u)}` : 'Connect an Instagram account',
        `<p>You will be sent to Instagram/Meta. ${u ? `Pick <b>@${esc(u)}</b> and` : 'Pick the account and'} tap <b>Allow</b>. `
        + `The token goes straight from Meta into GitHub, encrypted; nobody has to copy anything.</p>`
        + `<p><a class="b" href="${esc(login)}">Continue to Instagram</a></p>`);
    }

    if (path === '/connect/callback') {
      let expected = '';
      try { expected = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(url.searchParams.get('state') || ''), (c) => c.charCodeAt(0)))).u || ''; } catch (_) { /* no state */ }
      if (url.searchParams.get('error')) return page('Not connected', `<p>${esc(url.searchParams.get('error_description') || url.searchParams.get('error'))}</p>`, 400);
      const code = url.searchParams.get('code');
      if (code) {
        const ex = await getJSON(`${GRAPH}/oauth/access_token?client_id=${APP_ID}&redirect_uri=${encodeURIComponent(redirect)}`
          + `&client_secret=${encodeURIComponent(env.META_APP_SECRET)}&code=${encodeURIComponent(code)}`);
        if (!ex.ok || !ex.body.access_token) return page('Not connected', `<p>Meta refused the code: ${esc(ex.body.error?.message || ex.status)}</p>`, 400);
        return keep(ex.body.access_token, expected, env);
      }
      // Some configurations return the token in the URL fragment, which never reaches a server: post it here.
      return page('Connecting…', `<p id="m">One moment…</p><script>
const h=new URLSearchParams(location.hash.slice(1));history.replaceState(null,'',location.pathname);
const t=h.get('long_lived_token')||h.get('access_token');
if(!t){document.getElementById('m').textContent='Meta sent nothing back. Open the connect link again.';}
else fetch('/connect/save',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({t,u:${JSON.stringify(expected)}})})
.then(r=>r.text()).then(x=>{document.open();document.write(x);document.close();});
</script>`);
    }

    if (path === '/connect/save' && request.method === 'POST') {
      const { t, u } = await request.json().catch(() => ({}));
      if (!t) return page('Not connected', '<p>No token arrived.</p>', 400);
      return keep(t, u, env);
    }

    if (path === '/connect/pickup' && request.method === 'GET') {
      const list = await env.CONNECT_KV.list({ prefix: 'item:' });
      const items = [];
      for (const k of list.keys) {
        const v = await env.CONNECT_KV.get(k.name);
        if (v) { const { proofHash, ...sealed } = JSON.parse(v); items.push({ id: k.name.slice(5), ...sealed }); }
      }
      return new Response(JSON.stringify({ items }), { headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });
    }

    const m = path.match(/^\/connect\/pickup\/([0-9a-f-]{36})$/);
    if (m && request.method === 'DELETE') {
      const v = await env.CONNECT_KV.get('item:' + m[1]);
      if (!v) return new Response('gone', { status: 404 });
      const proof = url.searchParams.get('proof') || '';
      const h = b64(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(proof)));
      if (h !== JSON.parse(v).proofHash) return new Response('no', { status: 403 });
      await env.CONNECT_KV.delete('item:' + m[1]);
      return new Response('deleted');
    }

    return new Response('not found', { status: 404 });
  },
};
