#!/usr/bin/env python3
"""Collab posts between our own accounts, and accepting the invites they send.

A collab post shows on every collaborator's profile and to every collaborator's followers, so a fact reel
from psychedelic.station that names @close__quarters as a collaborator also reaches the band's followers
and sits on the band's grid. Instagram sends the collaborator an invite; because every account here is
managed by the same login, this accepts it straight away.

    python studio/collabs.py accept        # accept every pending invite between our own accounts

Which posts invite whom is decided by the scripts that make them (post_factreel.py) through invite().
"""
import datetime, glob, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
GRAPH = 'https://graph.facebook.com/v27.0'

# Our Instagram accounts by username, with the id the API knows them by (accounts.yaml channel_id).
OWN = {
    'close__quarters': '17841467020770402',
    'dylancantor23': '17841400966563600',
    'psychedelic.station': '17841411961308319',
    'nostalgia.hub.vhs': '17841425528393897',
}
# Who each account brings in on its collab posts, and how many collab posts it makes a day. Kept to one a
# day so the band's own grid stays the band's.
PLAN = {
    'psychedelic_station_ig': dict(with_=['close__quarters'], per_day=1),
    'nostalgia_ig': dict(with_=['close__quarters'], per_day=1),
}


def invite(account, made_today):
    """The collaborators for the next post `account` makes, given how many collab posts it made today."""
    p = PLAN.get(account)
    return list(p['with_']) if p and made_today < p['per_day'] else []


def accept():
    import requests
    token = os.environ.get('IG_TOKEN')
    if not token: print('no IG_TOKEN; nothing to accept'); return 0
    pending = []
    for f in sorted(glob.glob(os.path.join(REPO, 'outbox', '*.json'))):
        item = json.load(open(f))
        if item.get('status') == 'published' and item.get('media_id') and item.get('collaborators') and not item.get('collab_done'):
            when = str(item.get('published_at') or item.get('scheduled_for') or '')
            if when and when[:10] < (datetime.date.today() - datetime.timedelta(days=3)).isoformat(): continue   # gave up on it
            pending.append((f, item))
    if not pending: print('no collab invites to accept'); return 0
    changed = 0
    for f, item in pending:
        done = dict(item.get('collab_done') or {})
        for name in item['collaborators']:
            uid = OWN.get(str(name).lstrip('@'))
            if not uid or name in done: continue
            r = requests.post('%s/%s/collaboration_invites' % (GRAPH, uid),
                              data=dict(media_id=item['media_id'], accept='true', access_token=token), timeout=30)
            ok = r.ok and (r.json() or {}).get('success', True) is not False
            print(('accepted' if ok else 'could not accept'), name, item['id'], '' if ok else r.text[:300])
            if ok: done[name] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if done:
            item['collab_done'] = done; json.dump(item, open(f, 'w'), indent=2, sort_keys=True); changed += 1
    return changed


if __name__ == '__main__':
    if sys.argv[1:] == ['accept']: print('updated', accept())
    else: print(__doc__)
