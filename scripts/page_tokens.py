"""Mint never-expiring Page tokens for every Instagram account on Dylan's Facebook Pages.

A Page token taken from a long-lived user token does not expire. IG_TOKEN is that user
token, so this needs no app secret and no logins: it reads me/accounts and stores
{instagram id: page token} as the IG_PAGE_TOKENS secret, which the publisher prefers.
Any account linked to a Page (and granted to the app, which takes all Pages) is covered.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request

GRAPH = 'https://graph.facebook.com/v21.0'
REPO = os.environ.get('GITHUB_REPOSITORY', 'nickdotname/ugc-factory')


def mask(value: str) -> None:
    if value and os.environ.get('GITHUB_ACTIONS'):
        print('::add-mask::' + value)


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def main() -> int:
    user = os.environ.get('IG_TOKEN', '')
    if not user or not os.environ.get('SECRETS_PAT'):
        print('IG_TOKEN or SECRETS_PAT missing'); return 1
    mask(user)
    url = GRAPH + '/me/accounts?' + urllib.parse.urlencode({
        'fields': 'name,access_token,instagram_business_account{id,username}', 'limit': 100, 'access_token': user})
    tokens: dict[str, str] = {}
    while url:
        try:
            body = get(url)
        except urllib.error.HTTPError as exc:
            print('me/accounts failed: %s' % exc.read().decode()[:300]); return 1
        for page in body.get('data', []):
            iba = page.get('instagram_business_account') or {}
            if not iba.get('id'):
                print('page %s: no Instagram account linked' % page.get('name'))
            if iba.get('id') and page.get('access_token'):
                mask(page['access_token'])
                tokens[str(iba['id'])] = page['access_token']
                print('@%s (page %s)' % (iba.get('username'), page.get('name')))
        url = (body.get('paging') or {}).get('next')
    if not tokens:
        print('no Instagram accounts found on the Pages: IG_PAGE_TOKENS left as it was'); return 1
    subprocess.run(['gh', 'secret', 'set', 'IG_PAGE_TOKENS', '--repo', REPO], input=json.dumps(tokens).encode(),
                   check=True, env=dict(os.environ, GH_TOKEN=os.environ['SECRETS_PAT']), stdout=subprocess.DEVNULL)
    print('IG_PAGE_TOKENS saved: %d accounts' % len(tokens))
    return 0


if __name__ == '__main__':
    sys.exit(main())
