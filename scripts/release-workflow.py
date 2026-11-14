"""The decisions of the release workflow (``.github/workflows/release.yml``), one subcommand per
step: the checks before a release, the sources release, the notes, the signed ``SHA256SUMS`` and
the publication of a GitHub release.

GitHub is reached only through ``gh``; any ``gh`` failure stops the step, so an API error is never
read as "no release". A release is published only after every asset is up with the local bytes,
and a draft found under its tag is an interrupted run's: the workflow runs one release at a time.
A failure prints ``::error::`` and exits 1; step outputs go to ``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_DOC = REPO_ROOT / "docs" / "release.md"
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.asc"
MANIFEST = "manifest.json"

# ASCII digits only, no leading zeros: the spelling PEP 440 and SemVer share.
_FINAL_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
# WiX refuses a larger ProductVersion, so the MSI would fail after every other build had run.
_MSI_LIMITS = (255, 255, 65535)
_SUMS_LINE = re.compile(r"([0-9a-f]{64}) [ *](\S+)")
_PUBLIC_KEY = re.compile(
    r"^-----BEGIN PGP PUBLIC KEY BLOCK-----$.*?^-----END PGP PUBLIC KEY BLOCK-----$",
    re.DOTALL | re.MULTILINE,
)

REQUIRED_SECRETS = ("TAURI_SIGNING_PRIVATE_KEY", "RELEASE_GPG_PRIVATE_KEY")
CERTIFICATE = "WINDOWS_CERTIFICATE"
WITH_CERTIFICATE = ("WINDOWS_CERTIFICATE_PASSWORD",)
SECRETS = (*REQUIRED_SECRETS, CERTIFICATE, *WITH_CERTIFICATE)

SOURCES_NOTES = (
    "The source code of the third-party programs and libraries that Reframe's packages bundle: "
    f"one archive per entry of {MANIFEST}, and their {SUMS}. Each Reframe release names the "
    "sources release it was built with.\n"
)


class ReleaseError(Exception):
    """The release must stop; the message says why and what to do."""


def gh(*args: str) -> bytes:
    """``gh``'s output; any failure, a 404 too, raises."""
    result = subprocess.run(["gh", *args], capture_output=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        command = " ".join(args)
        raise ReleaseError(f"gh {command[:120]} failed: {detail}")
    return result.stdout


def gh_json(*args: str) -> Any:
    return json.loads(gh(*args))


def gh_list(path: str) -> list[Any]:
    """Every item of a paginated list endpoint."""
    pages = gh_json("api", "--paginate", "--slurp", path)
    return [item for page in pages for item in page]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Want:
    """What a release asset must be."""

    sha256: str
    size: int | None = None


def local_files(paths: Iterable[Path]) -> dict[str, Want]:
    """Each file by its asset name (the file name).

    :raises ReleaseError: two files have one name.
    """
    files: dict[str, Want] = {}
    for path in paths:
        if path.name in files:
            raise ReleaseError(f"two files are named {path.name}; a release has one asset per name")
        files[path.name] = Want(sha256_file(path), path.stat().st_size)
    return files


def asset_problems(assets: Sequence[Mapping[str, Any]], wanted: Mapping[str, Want]) -> list[str]:
    """Why ``assets`` are not exactly ``wanted``: a missing, unfinished, other or extra file."""
    found = {str(asset["name"]): asset for asset in assets}
    problems = []
    for name, want in sorted(wanted.items()):
        asset = found.get(name)
        if asset is None:
            problems.append(f"{name}: missing")
        elif asset["state"] != "uploaded":
            problems.append(f"{name}: not completely uploaded (state {asset['state']})")
        elif want.size is not None and asset["size"] != want.size:
            problems.append(f"{name}: {asset['size']} bytes, expected {want.size}")
        # The API documents the digest as "string or null".
        elif asset.get("digest") not in (None, f"sha256:{want.sha256}"):
            problems.append(f"{name}: {asset['digest']}, expected sha256:{want.sha256}")
    problems += [f"{name}: not a file of this release" for name in sorted(set(found) - set(wanted))]
    return problems


def parse_sums(text: str, what: str) -> dict[str, str]:
    """``sha256sum`` lines as {file name: SHA-256}.

    :raises ReleaseError: a line that is not one, or a name listed twice.
    """
    sums: dict[str, str] = {}
    for line in text.splitlines():
        match = _SUMS_LINE.fullmatch(line)
        if match is None or match.group(2) in sums:
            raise ReleaseError(f"{what}: not a SHA-256 line of a new file: {line!r}")
        sums[match.group(2)] = match.group(1)
    return sums


def archive_names(manifest: Path) -> list[str]:
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8"))["entries"]
        return [str(entry["archive"]) for entry in entries]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReleaseError(f"{manifest}: not a source manifest ({error})") from error


def releases_with_tag(repo: str, tag: str) -> list[dict[str, Any]]:
    # Only the list has drafts: the by-tag endpoint finds published releases.
    releases = gh_list(f"repos/{repo}/releases?per_page=100")
    return [release for release in releases if release["tag_name"] == tag]


def delete_drafts(repo: str, releases: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deletes each draft, with what was uploaded to it, and returns the published releases."""
    published = []
    for release in releases:
        if release["draft"]:
            print(
                f"::warning::Deleting the draft release {release['tag_name']} (id {release['id']},"
                f" {len(release['assets'])} files) that an interrupted run left"
            )
            gh("api", "-X", "DELETE", f"repos/{repo}/releases/{release['id']}")
        else:
            published.append(release)
    return published


def publish(
    repo: str,
    tag: str,
    paths: Sequence[Path],
    *,
    title: str,
    notes_file: Path,
    latest: bool,
    target: str | None = None,
    verify_tag: bool = False,
) -> str:
    """Makes the release ``tag`` with exactly ``paths`` as assets and returns its URL. It is a
    draft until every asset is up with the local bytes, so nobody sees a partial release.

    :raises ReleaseError: ``tag`` is published already, or the upload is incomplete (the draft
        stays, and the next run deletes it).
    """
    wanted = local_files(paths)
    if delete_drafts(repo, releases_with_tag(repo, tag)):
        raise ReleaseError(
            f"The release {tag} is published already: nothing was changed. A release that is "
            "published is never replaced (docs/release.md, 'When a run fails')."
        )
    create = ["release", "create", tag, "--repo", repo, "--draft", "--title", title]
    create += ["--notes-file", str(notes_file)]
    if target is not None:
        create += ["--target", target]
    if verify_tag:
        create.append("--verify-tag")
    gh(*create, *(str(path) for path in paths))

    drafts = [release for release in releases_with_tag(repo, tag) if release["draft"]]
    if len(drafts) != 1:
        raise ReleaseError(f"{len(drafts)} draft releases have the tag {tag} after the upload")
    problems = asset_problems(drafts[0]["assets"], wanted)
    if problems:
        raise ReleaseError(
            f"The upload to the draft release {tag} is not complete; run the job again (it "
            "deletes the draft first):\n" + "\n".join(f"  {problem}" for problem in problems)
        )
    release = gh_json(
        "api",
        "-X",
        "PATCH",
        f"repos/{repo}/releases/{drafts[0]['id']}",
        "-F",
        "draft=false",
        "-f",
        f"make_latest={str(latest).lower()}",
    )
    if release.get("draft") is not False:
        raise ReleaseError(f"GitHub did not publish the release {tag}")
    return str(release["html_url"])


def find_sources(repo: str, tag: str, manifest: Path, sums_out: Path) -> bool:
    """Whether the sources release ``tag`` is published with every file of ``manifest``; when it
    is, its ``SHA256SUMS`` is written to ``sums_out``. A draft of it is deleted.

    :raises ReleaseError: it is published but incomplete, or it is another manifest's.
    """
    published = delete_drafts(repo, releases_with_tag(repo, tag))
    if not published:
        return False
    assets = published[0]["assets"]
    sums_asset = next((a for a in assets if a["name"] == SUMS and a["state"] == "uploaded"), None)
    if sums_asset is None:
        raise _incomplete(tag, [f"{SUMS}: missing"])
    data = gh(
        "api",
        "-H",
        "Accept: application/octet-stream",
        f"repos/{repo}/releases/assets/{sums_asset['id']}",
    )
    sums = parse_sums(data.decode("utf-8"), f"{SUMS} of {tag}")
    archives = set(archive_names(manifest))
    problems = [f"{name}: not in its {SUMS}" for name in sorted(archives - set(sums))]
    problems += [
        f"{name}: in its {SUMS}, not in the manifest" for name in sorted(set(sums) - archives)
    ]
    wanted = {
        MANIFEST: Want(sha256_file(manifest), manifest.stat().st_size),
        SUMS: Want(hashlib.sha256(data).hexdigest(), len(data)),
    }
    wanted |= {name: Want(sha256) for name, sha256 in sums.items()}
    problems += asset_problems(assets, wanted)
    if problems:
        raise _incomplete(tag, problems)
    sums_out.parent.mkdir(parents=True, exist_ok=True)
    sums_out.write_bytes(data)
    return True


def _incomplete(tag: str, problems: list[str]) -> ReleaseError:
    return ReleaseError(
        f"The sources release {tag} is published but does not hold this manifest's files. If no "
        f"Reframe release names it, delete it (gh release delete {tag} --cleanup-tag) and run the"
        " release again:\n" + "\n".join(f"  {problem}" for problem in problems)
    )


def publish_sources(repo: str, tag: str, manifest: Path, files: Path, target: str) -> str:
    """Makes the sources release: the manifest, ``SHA256SUMS`` and each fetched archive."""
    if manifest.name != MANIFEST:
        raise ReleaseError(f"{manifest}: the manifest's asset must be named {MANIFEST}")
    archives = archive_names(manifest)
    sums = parse_sums((files / SUMS).read_text(encoding="utf-8"), str(files / SUMS))
    paths = [manifest, files / SUMS, *(files / name for name in archives)]
    wanted = local_files(paths)
    wrong = sorted(set(sums) ^ set(archives))
    wrong += [name for name in archives if name in sums and sums[name] != wanted[name].sha256]
    if wrong:
        raise ReleaseError(f"{files / SUMS} does not match the archives: {', '.join(wrong)}")
    with tempfile.TemporaryDirectory(prefix="release-notes-") as folder:
        notes = Path(folder) / "notes.md"
        notes.write_text(SOURCES_NOTES, encoding="utf-8")
        return publish(
            repo, tag, paths, title=f"Sources {tag}", notes_file=notes, latest=False, target=target
        )


def version_problems(tag: str, version: str) -> list[str]:
    problems = []
    if tag != f"v{version}":
        problems.append(f"The tag {tag} is not v{version}, the stamped version")
    match = _FINAL_VERSION.fullmatch(version)
    if match is None:
        problems.append(
            f"{version!r} is not X.Y.Z: pre-releases are not released (docs/release.md)"
        )
    elif any(
        int(number) > limit for number, limit in zip(match.groups(), _MSI_LIMITS, strict=True)
    ):
        problems.append(f"{version}: the MSI's version is at most 255.255.65535")
    return problems


def secret_problems(secrets: set[str], timestamp_url: str) -> list[str]:
    """The secrets and variables a release needs that are not set."""
    missing = [name for name in REQUIRED_SECRETS if name not in secrets]
    if CERTIFICATE in secrets:
        missing += [name for name in WITH_CERTIFICATE if name not in secrets]
    problems = [f"The secret {name} is not set (docs/release.md)" for name in missing]
    if CERTIFICATE in secrets and not timestamp_url:
        problems.append(
            f"The variable WINDOWS_TIMESTAMP_URL is not set, but {CERTIFICATE} is (docs/release.md)"
        )
    return problems


def is_highest(version: str, tags: Iterable[str]) -> bool:
    """Whether no ``vX.Y.Z`` tag names a higher version than ``version``."""
    own = _final_key(version)
    if own is None:
        return False
    keys = (_final_key(tag.removeprefix("v")) for tag in tags if tag.startswith("v"))
    return all(key <= own for key in keys if key is not None)


def _final_key(version: str) -> tuple[int, int, int] | None:
    match = _FINAL_VERSION.fullmatch(version)
    if match is None:
        return None
    major, minor, patch = (int(number) for number in match.groups())
    return major, minor, patch


def preflight(
    tag: str, version: str, repo: str, secrets: set[str], timestamp_url: str
) -> tuple[list[str], bool]:
    """The reasons not to release, and whether the release is the latest one."""
    problems = version_problems(tag, version) + secret_problems(secrets, timestamp_url)
    if gh_json("api", f"repos/{repo}")["private"]:
        problems.append(
            f"{repo} is private: the updater, the packages' sources link and the image need a "
            "public repository. Make it public first (docs/release.md)"
        )
    refs = gh_list(f"repos/{repo}/git/matching-refs/tags/v")
    tags = [str(ref["ref"]).removeprefix("refs/tags/") for ref in refs]
    return problems, is_highest(version, tags)


def release_notes(
    changes: str, *, signed: bool, check_url: str, sources_url: str, sources_sums: str
) -> str:
    lines = [changes.strip(), ""]
    if not signed:
        lines += [
            "**The Windows installers are not code-signed.** Windows SmartScreen warns before it"
            " starts them.",
            "",
        ]
    lines += [
        "### Checksums",
        "",
        f"`{SUMS}` holds the SHA-256 of every file of this release, and `{SIGNATURE}` its GPG"
        f" signature. How to check a download: {check_url}",
        "",
        "### Source code",
        "",
        "The source code of the third-party programs and libraries in these packages:"
        f" {sources_url}",
        "",
        "SHA-256 of each archive:",
        "",
        "```",
        sources_sums.rstrip("\n"),
        "```",
    ]
    return "\n".join(lines) + "\n"


def write_sums(paths: Sequence[Path], out_dir: Path) -> Path:
    files = local_files(paths)
    out_dir.mkdir(parents=True, exist_ok=True)
    sums = out_dir / SUMS
    sums.write_bytes("".join(f"{f.sha256}  {name}\n" for name, f in sorted(files.items())).encode())
    return sums


def documented_public_key(doc: Path) -> str:
    match = _PUBLIC_KEY.search(doc.read_text(encoding="utf-8"))
    if match is None:
        raise ReleaseError(
            f"{doc} has no PGP public key block: add the release key's public key "
            "(docs/release.md, 'The signing key of SHA256SUMS')"
        )
    return match.group(0) + "\n"


@contextlib.contextmanager
def _gnupg_home() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="gpg-", ignore_cleanup_errors=True) as folder:
        try:
            yield Path(folder)
        finally:
            subprocess.run(
                ["gpgconf", "--homedir", folder, "--kill", "all"], capture_output=True, check=False
            )


def _gpg(home: Path, what: str, *args: str, stdin: str = "") -> None:
    result = subprocess.run(
        ["gpg", "--homedir", str(home), "--batch", "--no-tty", "--yes", *args],
        input=stdin.encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ReleaseError(f"{what}: {detail}")


def sign(sums: Path, secret_key: str, passphrase: str, public_key: str) -> Path:
    """Writes ``sums``'s detached signature next to it and checks it with ``public_key``, the key
    that users are told to trust.

    :raises ReleaseError: the key cannot sign (a wrong passphrase), or it is not ``public_key``.
    """
    if not secret_key.strip():
        raise ReleaseError("The secret RELEASE_GPG_PRIVATE_KEY is not set (docs/release.md)")
    signature = sums.with_name(SIGNATURE)
    with _gnupg_home() as home:
        _gpg(home, "RELEASE_GPG_PRIVATE_KEY is not a GPG secret key", "--import", stdin=secret_key)
        _gpg(
            home,
            "The release key cannot sign (RELEASE_GPG_PASSPHRASE?)",
            *("--pinentry-mode", "loopback", "--passphrase-fd", "0"),
            *("--armor", "--detach-sign", "--output", str(signature), str(sums)),
            stdin=passphrase,
        )
    with _gnupg_home() as home:
        _gpg(
            home, "The public key in docs/release.md is not a GPG key", "--import", stdin=public_key
        )
        _gpg(
            home,
            f"{SIGNATURE} does not verify with the public key in docs/release.md: the secret "
            "RELEASE_GPG_PRIVATE_KEY holds another key",
            *("--verify", str(signature), str(sums)),
        )
    return signature


def _set_outputs(**values: str) -> None:
    text = "".join(f"{name}={value}\n" for name, value in values.items())
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as file:
            file.write(text)
    else:
        sys.stdout.write(text)


def _error(message: str) -> None:
    first, *rest = message.splitlines() or [""]
    print(f"::error::{first}")
    for line in rest:
        print(line)


def _preflight(args: argparse.Namespace) -> int:
    secrets = {name for name in SECRETS if os.environ.get(f"{name}_SET") == "true"}
    timestamp_url = os.environ.get("WINDOWS_TIMESTAMP_URL", "")
    problems, latest = preflight(args.tag, args.version, args.repo, secrets, timestamp_url)
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    _set_outputs(version=args.version, latest=str(latest).lower())
    print(f"Releasing {args.version}; the latest release: {str(latest).lower()}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("preflight", help="the tag, the version, secrets, visibility")
    check.add_argument("--tag", required=True)
    check.add_argument("--version", required=True, help="stamp-version.py --check's output")
    check.add_argument("--repo", required=True, help="OWNER/NAME")

    find = commands.add_parser("sources-find", help="is the sources release complete?")
    find.add_argument("--repo", required=True)
    find.add_argument("--tag", required=True)
    find.add_argument("--manifest", type=Path, required=True)
    find.add_argument("--sums-out", type=Path, required=True)

    sources = commands.add_parser("sources-publish", help="make the sources release")
    sources.add_argument("--repo", required=True)
    sources.add_argument("--tag", required=True)
    sources.add_argument("--manifest", type=Path, required=True)
    sources.add_argument("--files", type=Path, required=True, help="sources-fetch.py's --out")
    sources.add_argument("--target", required=True, help="the commit the tag is made on")

    notes = commands.add_parser("notes", help="write the release notes")
    notes.add_argument("--changes", type=Path, required=True, help="release-notes.py's output")
    notes.add_argument("--signed", required=True, help="'true' when the installers are signed")
    notes.add_argument("--check-url", required=True, help="how to check a download")
    notes.add_argument("--sources-url", required=True)
    notes.add_argument("--sources-sums", type=Path, required=True)
    notes.add_argument("--out", type=Path, required=True)

    sums = commands.add_parser(
        "sums",
        help="SHA256SUMS of FILEs and its signature (RELEASE_GPG_PRIVATE_KEY, "
        "RELEASE_GPG_PASSPHRASE)",
    )
    sums.add_argument("--out-dir", type=Path, required=True)
    sums.add_argument("--public-key-doc", type=Path, default=RELEASE_DOC)
    sums.add_argument("files", nargs="+", type=Path, metavar="FILE")

    release = commands.add_parser("publish", help="make the GitHub release of a version")
    release.add_argument("--repo", required=True)
    release.add_argument("--tag", required=True)
    release.add_argument("--title", required=True)
    release.add_argument("--notes-file", type=Path, required=True)
    release.add_argument("--latest", required=True, choices=["true", "false"])
    release.add_argument("--verify-tag", action="store_true", help="the tag must exist already")
    release.add_argument("files", nargs="+", type=Path, metavar="FILE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "preflight":
            return _preflight(args)
        if args.command == "sources-find":
            found = find_sources(args.repo, args.tag, args.manifest, args.sums_out)
            _set_outputs(found=str(found).lower())
            print(f"{args.tag}: {'published and complete' if found else 'not published'}")
        elif args.command == "sources-publish":
            print(publish_sources(args.repo, args.tag, args.manifest, args.files, args.target))
        elif args.command == "notes":
            text = release_notes(
                args.changes.read_text(encoding="utf-8"),
                signed=args.signed == "true",
                check_url=args.check_url,
                sources_url=args.sources_url,
                sources_sums=args.sources_sums.read_text(encoding="utf-8"),
            )
            args.out.write_bytes(text.encode("utf-8"))
            print(text, end="")
        elif args.command == "sums":
            public_key = documented_public_key(args.public_key_doc)
            path = write_sums(args.files, args.out_dir)
            signature = sign(
                path,
                os.environ.get("RELEASE_GPG_PRIVATE_KEY", ""),
                os.environ.get("RELEASE_GPG_PASSPHRASE", ""),
                public_key,
            )
            print(f"{path}, {signature}")
        else:
            print(
                publish(
                    args.repo,
                    args.tag,
                    args.files,
                    title=args.title,
                    notes_file=args.notes_file,
                    latest=args.latest == "true",
                    verify_tag=args.verify_tag,
                )
            )
    except (ReleaseError, OSError) as error:
        _error(str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
