#!/usr/bin/env bash
# Install system packages on a GitHub runner without ever hanging the job.
#
#     bash scripts/apt_install.sh ffmpeg libsndfile1
#
# apt on the hosted runners sometimes stalls for an hour (a dead mirror, or the man-page index being
# rebuilt), and a stalled install step held a nightly studio run and three render jobs on 2026-11-24.
# Each try gets a few minutes; a stalled try is killed and started again, three times in all.
set -u
[ "$#" -gt 0 ] || { echo "usage: apt_install.sh PACKAGE..."; exit 2; }
OPTS="-o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 -o DPkg::Lock::Timeout=60"
sudo rm -f /var/lib/man-db/auto-update            # no man-page index rebuild after every install
for try in 1 2 3; do
  if sudo timeout -k 10 150 apt-get $OPTS update -qq \
     && sudo DEBIAN_FRONTEND=noninteractive timeout -k 10 360 apt-get $OPTS install -y -qq "$@"; then
    exit 0
  fi
  echo "::warning::apt try $try failed or timed out; trying again"
  sudo pkill -9 -x apt-get 2>/dev/null; sudo pkill -9 -x dpkg 2>/dev/null
  sudo dpkg --configure -a >/dev/null 2>&1
  sleep 5
done
echo "::error::could not install: $*"
exit 1
