#!/bin/sh
# The bundler's rpm owns the files but not the folders under /usr/lib/Reframe, so rpm leaves the
# empty folders behind. Removes them after an erase (rpm passes 0), not after an upgrade.
app=/usr/lib/Reframe
if [ "$1" = 0 ] && [ -d "$app" ]; then
    find "$app" -depth -type d -empty -delete
fi
