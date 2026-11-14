"""Writes the Tauri updater's ``latest.json`` for a release from the signed updater artefacts.

Each ARTEFACT needs ``ARTEFACT.sig`` next to it, as ``tauri signer sign --app-version`` writes it.
A signature that the installed app would refuse stops the run: one bound to another version, made
for another file, or made with a key other than the public key in ``tauri.conf.json``.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAURI_CONFIG = REPO_ROOT / "desktop" / "src-tauri" / "tauri.conf.json"

# The bundler's file name endings, and the updater target the app looks up for that install:
# `{os}-{arch}-{installer}` (tauri-plugin-updater). Only the installs that the app updates.
PLATFORMS = (
    ("_x64-setup.exe", "windows-x86_64-nsis"),
    ("_amd64.AppImage", "linux-x86_64-appimage"),
    ("_amd64.deb", "linux-x86_64-deb"),
)

SEMVER = re.compile(
    r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(-((0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(\.(0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(\+([0-9a-zA-Z-]+(\.[0-9a-zA-Z-]+)*))?"
)

# minisign: a 2-byte algorithm, the 8-byte key id, then the key or the signature.
PUBLIC_KEY_SIZE = 2 + 8 + 32
SIGNATURE_SIZE = 2 + 8 + 64


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class Signature:
    key_id: bytes
    trusted: dict[str, str]


def key_id_text(key_id: bytes) -> str:
    """The key id as minisign prints it (a little-endian number)."""
    return key_id[::-1].hex().upper()


def _b64_text(value: str, what: str) -> str:
    try:
        return base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ManifestError(f"{what} is not base64-encoded minisign text") from exc


def _b64_bytes(value: str, size: int, what: str) -> bytes:
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except binascii.Error as exc:
        raise ManifestError(f"{what}: the key line is not base64") from exc
    if len(raw) != size:
        raise ManifestError(f"{what}: {len(raw)} bytes, a minisign line has {size}")
    return raw


def public_key_id(pubkey: str) -> bytes:
    """The key id of a Tauri ``pubkey`` value (base64 of a minisign public key file)."""
    lines = _b64_text(pubkey, "the updater's public key").splitlines()
    if len(lines) < 2 or not lines[0].startswith("untrusted comment:"):
        raise ManifestError("the updater's public key is not a minisign public key")
    return _b64_bytes(lines[1], PUBLIC_KEY_SIZE, "the updater's public key")[2:10]


def read_signature(text: str, what: str) -> Signature:
    """Parses a Tauri ``.sig`` file (base64 of a minisign signature file)."""
    lines = _b64_text(text, what).splitlines()
    if (
        len(lines) < 4
        or not lines[0].startswith("untrusted comment:")
        or not lines[2].startswith("trusted comment: ")
    ):
        raise ManifestError(f"{what} is not a minisign signature")
    raw = _b64_bytes(lines[1], SIGNATURE_SIZE, what)
    comment = lines[2].removeprefix("trusted comment: ")
    trusted = {
        key: value for key, _, value in (field.partition(":") for field in comment.split("\t"))
    }
    return Signature(key_id=raw[2:10], trusted=trusted)


def platform_of(name: str) -> str:
    for ending, platform in PLATFORMS:
        if name.endswith(ending):
            return platform
    endings = ", ".join(ending for ending, _ in PLATFORMS)
    raise ManifestError(f"{name}: not an updater artefact (a name ending in {endings})")


def platform_entry(
    artefact: Path, version: str, key_id: bytes, base_url: str
) -> tuple[str, dict[str, str]]:
    platform = platform_of(artefact.name)
    if not artefact.is_file():
        raise ManifestError(f"{artefact}: no such file")
    sig_path = artefact.with_name(artefact.name + ".sig")
    if not sig_path.is_file():
        raise ManifestError(f"{sig_path}: no such file (sign {artefact.name} first)")
    sig_text = sig_path.read_text(encoding="ascii").strip()
    signature = read_signature(sig_text, sig_path.name)
    signed_version = signature.trusted.get("version")
    if signed_version is None:
        raise ManifestError(
            f"{sig_path.name} is not bound to a version: sign with --app-version {version}"
        )
    if signed_version != version:
        raise ManifestError(
            f"{sig_path.name} is signed for version {signed_version}, not {version}"
        )
    signed_file = signature.trusted.get("file")
    if signed_file != artefact.name:
        raise ManifestError(
            f"{sig_path.name} is the signature of {signed_file}, not {artefact.name}"
        )
    if signature.key_id != key_id:
        raise ManifestError(
            f"{sig_path.name} is signed with key {key_id_text(signature.key_id)}, but the app"
            f" trusts key {key_id_text(key_id)} (plugins.updater.pubkey)"
        )
    url = f"{base_url.rstrip('/')}/{quote(artefact.name)}"
    return platform, {"signature": sig_text, "url": url}


def build_manifest(
    version: str,
    notes: str,
    base_url: str,
    artefacts: list[Path],
    pubkey: str,
    now: datetime,
) -> dict[str, object]:
    if not SEMVER.fullmatch(version):
        raise ManifestError(
            f"{version!r} is not a SemVer version (stamp-version.py --print-semver)"
        )
    if not base_url.startswith("https://"):
        raise ManifestError(f"{base_url}: the updater downloads only over https")
    key_id = public_key_id(pubkey)
    platforms: dict[str, dict[str, str]] = {}
    for artefact in artefacts:
        platform, entry = platform_entry(artefact, version, key_id, base_url)
        if platform in platforms:
            raise ManifestError(f"{artefact.name}: a second artefact for {platform}")
        platforms[platform] = entry
    return {
        "version": version,
        "notes": notes,
        "pub_date": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "platforms": dict(sorted(platforms.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--version", required=True, help="the SemVer version the artefacts carry")
    parser.add_argument("--notes", required=True, type=Path, help="a file with the release notes")
    parser.add_argument("--base-url", required=True, help="where the release's assets are")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tauri-config", type=Path, default=DEFAULT_TAURI_CONFIG)
    parser.add_argument("artefacts", nargs="+", type=Path, metavar="ARTEFACT")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.tauri_config.read_text(encoding="utf-8"))
        manifest = build_manifest(
            args.version,
            args.notes.read_text(encoding="utf-8").strip(),
            args.base_url,
            args.artefacts,
            config["plugins"]["updater"]["pubkey"],
            datetime.now(UTC),
        )
    except ManifestError as exc:
        print(f"updater-manifest: {exc}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
