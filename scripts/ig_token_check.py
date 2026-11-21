#!/usr/bin/env python3
"""Say how long each Instagram token has left, and raise the alarm a week before it runs out.

    IG_TOKEN=... [DISCORD_WEBHOOK=...] python scripts/ig_token_check.py [--warn-days 7]

A token lasts about 60 days and nothing warns when it lapses: posts simply stop. This asks Instagram when
each token in use expires (one request per token, never printing it). With under --warn-days left, or a
token already refused, it posts one line to the Discord webhook if there is one and exits 1 so the run
shows red. Anything it cannot find out is reported and ignored: this must never be the reason a job fails.
"""
import argparse, datetime, os, sys
import requests, yaml

ap = argparse.ArgumentParser(); ap.add_argument('--warn-days', type=float, default=7); a = ap.parse_args()
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
accounts = [x for x in yaml.safe_load(open(os.path.join(root, 'accounts.yaml')))['accounts'] if x.get('provider') == 'instagram']
slots = {}
for x in accounts: slots.setdefault(x['api_key_secret'], []).append(x['name'])
now = datetime.datetime.now(datetime.timezone.utc); alarms = []
for slot, names in sorted(slots.items()):
    token = os.environ.get(slot, '')
    who = ', '.join(names)
    if not token: print('%s is not set (%s)' % (slot, who)); continue
    try:
        r = requests.get('https://graph.facebook.com/debug_token', params={'input_token': token}, headers={'Authorization': 'Bearer ' + token}, timeout=30)
        data = (r.json() or {}).get('data') or {}
    except Exception as exc:
        print('::warning::could not check %s: %s' % (slot, type(exc).__name__)); continue
    if r.status_code == 401 or data.get('is_valid') is False:
        alarms.append('The Instagram token in %s is no longer accepted. Nothing can post to %s until it is replaced.' % (slot, who)); continue
    exp = data.get('expires_at')
    if not exp:
        print('%s: no expiry reported (%s)' % (slot, who)); continue
    left = (datetime.datetime.fromtimestamp(int(exp), datetime.timezone.utc) - now).total_seconds() / 86400
    print('%s: %.1f days left (%s)' % (slot, left, who))
    if left < a.warn_days:
        alarms.append('The Instagram token in %s runs out in %.1f days. Replace it with an extended one before then, or posting to %s stops.' % (slot, max(left, 0), who))
for msg in alarms:
    print('::error::' + msg)
    try:
        sys.path.insert(0, root)
        from src.notify import extract_webhook_url
        hook = extract_webhook_url(os.environ.get('DISCORD_WEBHOOK', ''))
        if hook: requests.post(hook, json={'content': '⚠️ ' + msg}, timeout=20)
    except Exception: pass
sys.exit(1 if alarms else 0)
