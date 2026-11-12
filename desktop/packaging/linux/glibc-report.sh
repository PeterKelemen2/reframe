#!/bin/sh
# Prints the newest GLIBC_ symbol version that each ELF file of an AppImage needs, newest last,
# then the newest overall: the oldest glibc the AppImage can run on.
# Usage: glibc-report.sh FILE.AppImage
set -eu

appimage=$(realpath "$1")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cd "$work"
"$appimage" --appimage-extract > /dev/null

needs() {
    objdump -T "$1" 2> /dev/null | grep -o 'GLIBC_[0-9][0-9.]*' | sort -uV | tail -n 1
}

{
    printf '%s %s\n' "$(needs "$appimage")" "$(basename "$appimage") (runtime)"
    find squashfs-root -type f | while IFS= read -r f; do
        if [ "$(head -c 4 "$f" | od -An -c | tr -d ' ')" = '177ELF' ]; then
            printf '%s %s\n' "$(needs "$f")" "${f#squashfs-root/}"
        fi
    done
} | sed 's/^ /none /' | sort -V > report.txt

cat report.txt
printf 'newest: %s\n' "$(grep -o '^GLIBC_[0-9.]*' report.txt | sort -uV | tail -n 1)"
