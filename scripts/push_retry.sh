#!/usr/bin/env bash
# Push the current branch, rebasing on every rejection, and FAIL if it never lands.
#
# The parallel matrix jobs (render, metrics, analytics, queue) all commit to main at
# once. The old inline loop (`for i in 1 2 3 4; do git push && break; git pull
# --rebase; done`) rebased after the 4th rejection and then stopped without pushing,
# and the step still exited 0: on 2026-11-28 four campaigns' renders (ascii_art,
# cq_producer, rocket_league, tiny_code) were made and uploaded but their queue.json
# never reached main, so topup found nothing and those accounts had no posts booked.
#
# usage: scripts/push_retry.sh [attempts]   (default 12)
set -u
attempts="${1:-12}"
for i in $(seq 1 "$attempts"); do
  if git push; then
    exit 0
  fi
  echo "push rejected, rebasing (attempt $i of $attempts)"
  # spread the retries so the jobs stop colliding on the same second
  sleep $(( (RANDOM % 8) + i ))
  if ! git pull --rebase; then
    git rebase --abort 2>/dev/null
    echo "::error::rebase failed; commit not pushed"
    exit 1
  fi
done
echo "::error::push still rejected after $attempts attempts; commit not pushed"
exit 1
