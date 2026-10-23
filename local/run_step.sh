#!/usr/bin/env bash
# One container command, with an owned process group and a remote deadline.
set -u
if [ "${1:-}" = --stop ]; then
  token=$2
  case "$token" in *[!a-zA-Z0-9-]*|'') exit 3;; esac
  lease="/tmp/hgs-check-$token"
  [ -f "$lease/pid" ] || exit 2
  read -r owner < "$lease/pid"
  if kill -0 "$owner" 2>/dev/null; then
    grep -zFq -- "$token" "/proc/$owner/cmdline" || exit 2
    kill -TERM "$owner" || exit 2
    for _ in {1..100}; do
      [ ! -e "$lease/pid" ] && exit 0
      sleep 0.1
    done
    exit 2
  fi
  exit 2
fi
token=$1
seconds=$2
shift 2
case "$token" in *[!a-zA-Z0-9-]*|'') exit 3;; esac
lease="/tmp/hgs-check-$token"
mkdir -m 700 "$lease" || exit 2
child=
stop_requested=0
cleanup() {
  trap '' INT TERM
  if [ -n "$child" ]; then
    kill -TERM -- "-$child" 2>/dev/null || true
    # Wait for the entire group, including descendants after the leader exits.
    for _ in {1..20}; do
      kill -0 -- "-$child" 2>/dev/null || break
      sleep 0.1
    done
    kill -KILL -- "-$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
  fi
  rm -f "$lease/pid"
  rmdir "$lease" 2>/dev/null || true
}
trap cleanup EXIT
trap 'stop_requested=1' INT TERM
printf '%s\n' "$$" > "$lease/pid"
[ "$stop_requested" = 0 ] || exit 143
setsid timeout --kill-after=3s "${seconds}s" "$@" &
child=$!
[ "$stop_requested" = 0 ] || exit 143
wait "$child"
exit $?
