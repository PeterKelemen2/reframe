#!/bin/sh
# Writes OUT: each Debian package installed in this image with its version, its source package
# and version, and that source's page on snapshot.debian.org (Debian keeps every source version
# there, so the image's distro packages are not re-hosted). With NOTICES, appends to that file
# each package's copyright file (the slim image keeps them), each text once.
# Usage: debian-packages.sh OUT [NOTICES]
set -eu

out="$1"
notices="${2:-}"
doc="${REFRAME_DOC_ROOT:-/usr/share/doc}"
arch="$(dpkg --print-architecture)"
installed() {
    dpkg-query -W -f '${db:Status-Abbrev}\t${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n' \
        | awk -F '\t' '$1 ~ /^ii/' | cut -f 2- | LC_ALL=C sort
}
{
    printf 'Debian packages in this image (%s), as dpkg lists them.\n' "$arch"
    printf 'Each line: package, version, source package, source version, the source on snapshot.debian.org.\n\n'
    installed | awk -F '\t' '{
            v = $4
            gsub(/:/, "%3A", v)
            gsub(/\+/, "%2B", v)
            printf "%s %s %s %s https://snapshot.debian.org/package/%s/%s/\n", $1, $2, $3, $4, $3, v
        }'
} >"$out.part"
mv "$out.part" "$out"

[ -n "$notices" ] || exit 0
rule="=============================================================================="
line="------------------------------------------------------------------------------"
seen=$(mktemp -d)
cp "$notices" "$notices.part"
{
    printf '\n%s\nDebian packages in this image: the copyright file of each\n%s\n' "$rule" "$rule"
    installed | cut -f 1 | while read -r package; do
        file="$doc/${package%%:*}/copyright"
        if [ ! -f "$file" ]; then
            echo "debian-packages.sh: $package has no $file" >&2
            exit 1
        fi
        printf '\n%s\n%s\n%s\n' "$line" "$package" "$line"
        sum=$(sha256sum "$file" | cut -d ' ' -f 1)
        if [ -e "$seen/$sum" ]; then
            printf 'The same text as %s above.\n' "$(cat "$seen/$sum")"
        else
            printf '%s\n' "$package" >"$seen/$sum"
            cat "$file"
        fi
    done
} >>"$notices.part"
rm -rf "$seen"
mv "$notices.part" "$notices"
