#!/bin/sh
# Runs a command as PUID:PGID with the groups of the GPU device nodes. Installed as
# reframe-entrypoint and linked as reframe and reframe-server, so a `docker exec` of either
# command also runs as that user and writes files the server can read.
set -eu

name=$(basename "$0")
case "$name" in
reframe | reframe-server) set -- "/opt/reframe/venv/bin/$name" "$@" ;;
esac
if [ "$#" -eq 0 ]; then
    echo "usage: reframe-entrypoint COMMAND [ARG...]" >&2
    exit 2
fi

PUID=${PUID:-1000}
PGID=${PGID:-1000}
# PUID=0 is for rootless Docker and Podman, where the container's root is the host user.
if [ "$(id -u)" != 0 ] || [ "$PUID" = 0 ]; then
    exec "$@"
fi
for value in "$PUID" "$PGID"; do
    case "$value" in
    '' | *[!0-9]*)
        echo "reframe-entrypoint: PUID and PGID must be numbers, not '$value'" >&2
        exit 2
        ;;
    esac
done

for dir in /config /data; do
    mkdir -p "$dir"
    # Only a folder that another user owns is walked, so a restart does not walk the cache.
    if [ "$(stat -c %u:%g "$dir")" != "$PUID:$PGID" ]; then
        chown -R "$PUID:$PGID" "$dir"
    fi
done

# The render group's id differs between hosts, so it is read from the device nodes.
groups=$PGID
for device in /dev/dri/*; do
    [ -c "$device" ] || continue
    gid=$(stat -c %g "$device")
    if [ "$gid" != 0 ]; then
        case ",$groups," in
        *",$gid,"*) ;;
        *) groups="$groups,$gid" ;;
        esac
    fi
done

if [ "${HOME:-/root}" = /root ]; then
    export HOME=/data
fi
exec setpriv --reuid="$PUID" --regid="$PGID" --groups="$groups" --no-new-privs -- "$@"
