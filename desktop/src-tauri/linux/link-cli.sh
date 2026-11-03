#!/bin/sh
# Puts the frozen CLI on PATH as /usr/bin/reframe. A reframe that another package or pip put
# there is left alone. The package's file list cannot hold the link: the bundler copies the
# file a link points to.
cli=/usr/lib/Reframe/sidecar/reframe
link=/usr/bin/reframe
if [ ! -e "$link" ] && [ ! -L "$link" ] || [ "$(readlink "$link")" = "$cli" ]; then
    ln -sfn "$cli" "$link"
else
    echo "Reframe: $link is not this package's; the reframe CLI stays at $cli" >&2
fi
