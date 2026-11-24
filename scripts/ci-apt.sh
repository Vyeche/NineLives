#!/usr/bin/env bash
# ci-apt.sh — apt-get install for the Gauntlet's runners, with time limits and retries: a stalled
# package mirror once used up a lane's whole time budget (and failed a run that had nothing wrong).
#   bash scripts/ci-apt.sh [apt-get options] PACKAGE...
# Each try gets 90 s to update and 3 minutes to install; three tries (about 14 minutes at worst),
# then it fails. The lanes' timeout-minutes leave room for all three.
set -uo pipefail
APT=(sudo apt-get -qq -o Acquire::Retries=3 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20
     -o DPkg::Lock::Timeout=60)
for try in 1 2 3; do
  if timeout 90 "${APT[@]}" update && timeout 180 "${APT[@]}" install -y "$@"; then
    exit 0
  fi
  echo "ci-apt: try $try of 3 failed; trying again" >&2
  sleep 10
done
exit 1
