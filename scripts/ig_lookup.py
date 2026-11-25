"""Print the Instagram account id of each handle in cqconnect/slots.json (or the handles given).

    python scripts/ig_lookup.py [handle ...]      (needs IG_TOKEN; asks through @close__quarters' business_discovery)

Tokens from Facebook Login for Business are system-user tokens that cannot list their own Instagram account, so a
new account's channel_id comes from here. Prints handles and ids only.
"""
import json, os, sys, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH = 'https://graph.facebook.com/v21.0'


def lookup(handle: str, via: str, token: str) -> str | None:
    q = urllib.parse.urlencode({'fields': f'business_discovery.username({handle}){{id,username}}', 'access_token': token})
    try:
        with urllib.request.urlopen(f'{GRAPH}/{via}?{q}', timeout=30) as r:
            return str(json.load(r)['business_discovery']['id'])
    except Exception as exc:  # noqa: BLE001
        print(f'{handle}: not found ({type(exc).__name__})'); return None


def main() -> int:
    import yaml
    token = os.environ.get('IG_TOKEN', '')
    if not token: print('IG_TOKEN missing'); return 1
    via = next(str(a['channel_id']) for a in yaml.safe_load((ROOT / 'accounts.yaml').read_text())['accounts']
               if a.get('name') == 'close_quarters_ig')
    handles = sys.argv[1:] or list(json.loads((ROOT / 'cqconnect' / 'slots.json').read_text()))
    for h in handles:
        i = lookup(h, via, token)
        if i: print(f'{h}: {i}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
