#!/bin/sh
# Removes /usr/bin/reframe when it is this package's link and the package is removed, not
# upgraded: dpkg passes "remove", rpm passes 0 (on an upgrade rpm runs this after the new
# package's link-cli.sh).
cli=/usr/lib/Reframe/sidecar/reframe
link=/usr/bin/reframe
case "$1" in
    remove | 0)
        if [ "$(readlink "$link")" = "$cli" ]; then
            rm -f "$link"
        fi
        ;;
esac
