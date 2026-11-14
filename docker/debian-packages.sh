#!/bin/sh
# Writes OUT: each Debian package installed in this image with its version, its source package
# and version, and that source's page on snapshot.debian.org (Debian keeps every source version
# there, so the image's distro packages are not re-hosted).
set -eu

out="$1"
arch="$(dpkg --print-architecture)"
{
    printf 'Debian packages in this image (%s), as dpkg lists them.\n' "$arch"
    printf 'Each line: package, version, source package, source version, the source on snapshot.debian.org.\n\n'
    dpkg-query -W -f '${db:Status-Abbrev}\t${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n' \
        | awk -F '\t' '$1 ~ /^ii/ {
            v = $5
            gsub(/:/, "%3A", v)
            gsub(/\+/, "%2B", v)
            printf "%s %s %s %s https://snapshot.debian.org/package/%s/%s/\n", $2, $3, $4, $5, $4, v
        }' \
        | LC_ALL=C sort
} >"$out.part"
mv "$out.part" "$out"
