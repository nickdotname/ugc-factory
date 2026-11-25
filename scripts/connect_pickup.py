"""Collect tokens from the "Connect Instagram" worker (cqconnect/worker.js) and save them as GitHub secrets.

    python scripts/connect_pickup.py          (GitHub Actions, the "connect" workflow; needs CONNECT_PRIVATE_KEY, SECRETS_PAT)

The worker holds each new token encrypted to cqconnect/public.pem (RSA-OAEP wrapping an AES-GCM key). Here it is
decrypted with the private key (a GitHub secret nobody has seen), matched to an account, written with
`gh secret set` (stdin, masked first) and deleted from the worker with the proof inside the payload. Which secret:
the account in accounts.yaml whose channel_id is the token's Instagram id, else cqconnect/slots.json (handle ->
secret name, for accounts not wired yet). A token for any other account is deleted unused. Nothing is printed
but handles and secret names.
"""
from __future__ import annotations

import base64, json, os, re, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get('CONNECT_URL', 'https://closequarters.vip/connect')
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory')
UA = {'User-Agent': 'cq-connect-pickup'}


def mask(v: str) -> None:
    if os.environ.get('GITHUB_ACTIONS'): print('::add-mask::' + v, flush=True)


def secret_for(ig_id: str, username: str) -> str | None:
    import yaml
    for a in (yaml.safe_load((ROOT / 'accounts.yaml').read_text()) or {}).get('accounts', []):
        if str(a.get('channel_id')) == ig_id and a.get('provider') == 'instagram': return a.get('api_key_secret')
    slots = json.loads((ROOT / 'cqconnect' / 'slots.json').read_text())
    return slots.get(username.lower())


def main() -> int:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    pem = os.environ.get('CONNECT_PRIVATE_KEY', '').encode()
    if not pem or not os.environ.get('SECRETS_PAT'): print('CONNECT_PRIVATE_KEY or SECRETS_PAT missing'); return 1
    key = serialization.load_pem_private_key(pem, password=None)
    with urllib.request.urlopen(urllib.request.Request(BASE + '/pickup', headers=UA), timeout=30) as r:
        items = json.load(r).get('items', [])
    if not items: print('nothing waiting'); return 0
    for it in items:
        try:
            aes = key.decrypt(base64.b64decode(it['key']), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
            p = json.loads(AESGCM(aes).decrypt(base64.b64decode(it['iv']), base64.b64decode(it['data']), None))
        except Exception as exc:
            print('item %s: cannot decrypt (%s)' % (it.get('id'), type(exc).__name__)); continue
        mask(p['token']); mask(p['proof'])
        name = secret_for(str(p['ig_id']), p['username'])
        if name and re.fullmatch(r'IG_TOKEN(_\d+)?', name):
            subprocess.run(['gh', 'secret', 'set', name, '--repo', REPO], input=p['token'].encode(), check=True,
                           env=dict(os.environ, GH_TOKEN=os.environ['SECRETS_PAT']), stdout=subprocess.DEVNULL)
            print('@%s -> %s saved (%s host)' % (p['username'], name, p.get('host')))
        else:
            print('@%s is not one of our accounts: dropped' % p['username'])
        req = urllib.request.Request(BASE + '/pickup/%s?proof=%s' % (it['id'], urllib.parse.quote(p['proof'])), method='DELETE', headers=UA)
        try: urllib.request.urlopen(req, timeout=30).read()
        except Exception as exc: print('  could not delete it from the worker: %s' % exc)
    return 0


if __name__ == '__main__':
    sys.exit(main())
