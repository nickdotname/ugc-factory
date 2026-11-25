"""Print the Instagram account id of each handle in cqconnect/slots.json (or the handles given).

    python scripts/ig_lookup.py [handle ...]      (needs IG_TOKEN; asks through @close__quarters' business_discovery)
    python scripts/ig_lookup.py --profiles        every account in accounts.yaml and slots.json: picture, bio, link,
                                                  name, followers, posts (public profile fields only)

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


DEFAULT_PIC = ('44884218_345707102882519_2446069589734326272_n', '464760996_1254146839119862_3605321457742435801_n')


def profile(handle: str, via: str, token: str) -> None:
    f = 'id,username,name,biography,website,profile_picture_url,followers_count,media_count'
    q = urllib.parse.urlencode({'fields': f'business_discovery.username({handle}){{{f}}}', 'access_token': token})
    try:
        with urllib.request.urlopen(f'{GRAPH}/{via}?{q}', timeout=30) as r:
            d = json.load(r)['business_discovery']
    except Exception as exc:  # noqa: BLE001
        print(f'{handle:28} NOT FOUND ({type(exc).__name__})'); return
    pic = d.get('profile_picture_url') or ''
    pic = 'none' if not pic else ('DEFAULT' if any(k in pic for k in DEFAULT_PIC) else 'ok')
    bio = (d.get('biography') or '').replace('\n', ' / ')
    print(f"{handle:28} pic={pic:7} name={d.get('name') or '-'!s:24} link={d.get('website') or 'NONE'} "
          f"followers={d.get('followers_count')} posts={d.get('media_count')} bio={bio[:70] or 'NONE'!r}")


def main() -> int:
    import yaml
    token = os.environ.get('IG_TOKEN', '')
    if not token: print('IG_TOKEN missing'); return 1
    via = next(str(a['channel_id']) for a in yaml.safe_load((ROOT / 'accounts.yaml').read_text())['accounts']
               if a.get('name') == 'close_quarters_ig')
    if sys.argv[1:] == ['--profiles']:
        sys.path.insert(0, str(ROOT / 'scripts')); from dash_data import HANDLES  # noqa: E402
        names = [h for h in HANDLES.values() if h and not h.startswith('the.loose')]
        for h in dict.fromkeys(names + list(json.loads((ROOT / 'cqconnect' / 'slots.json').read_text()))):
            profile(h, via, token)
        return 0
    handles = sys.argv[1:] or list(json.loads((ROOT / 'cqconnect' / 'slots.json').read_text()))
    for h in handles:
        i = lookup(h, via, token)
        if i: print(f'{h}: {i}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
