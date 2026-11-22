"""scripts/updater-manifest.py: the latest.json that the installed app reads, and the signatures
it refuses before they reach a user."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reframe_testing.scripts import load_script

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://github.com/owner/reframe/releases/download/v1.1.0rc1"
NSIS = "Reframe_1.1.0-rc.1_x64-setup.exe"

# `tauri signer generate` and `tauri signer sign -f KEY --app-version 1.1.0-rc.1 NSIS`
# (tauri-cli 2.12.4) with a throwaway key; the private key is not kept.
REAL_PUBKEY = (
    "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEQ3MzEyRjgzMkZDQzk2NzAKUldSd2xzd3Zn"
    "eTh4MTNkcnZ3S2Uzalpjc1ZFSDdVakNiV0FvZDFvRWRtYkVobXRYZ3daWHp3TS8K"
)
REAL_SIGNATURE = (
    "dW50cnVzdGVkIGNvbW1lbnQ6IHNpZ25hdHVyZSBmcm9tIHRhdXJpIHNlY3JldCBrZXkKUlVSd2xzd3ZneTh4MTQ2"
    "OW9Jd0hhU0t0NlpzNE5TMEdTUzRNbnJNL3RISFNOVWpqcm9GbUlNdU9MblVHa294bk5oNDBQYjQ4WGY4QVJMMzd3"
    "M1pnRWg3MFE3MlVzNUI2OEFjPQp0cnVzdGVkIGNvbW1lbnQ6IHRpbWVzdGFtcDoxNzk0Njc0NzkwCWZpbGU6UmVm"
    "cmFtZV8xLjEuMC1yYy4xX3g2NC1zZXR1cC5leGUJdmVyc2lvbjoxLjEuMC1yYy4xCmxVc3RCa0VPTXVYNDVRZWpT"
    "bVlSNThhamFubU1tdGNDRG1SK2o0ZWJFMllkY0ljNUhwVHZubE5BU0gya3NmSFNqWkUwZnJLdHdad08yZDZrRkc5"
    "ZURnPT0K"
)
REAL_KEY_ID = bytes.fromhex("D7312F832FCC9670")[::-1]


um = load_script("updater-manifest.py")


def _signature(key_id: bytes = REAL_KEY_ID, comment: str = "") -> str:
    """A .sig in the signer's layout; the signature bytes themselves are not checked here."""
    raw = b"ED" + key_id + bytes(64)
    text = (
        "untrusted comment: signature from tauri secret key\n"
        f"{base64.b64encode(raw).decode()}\n"
        f"trusted comment: {comment}\n"
        f"{base64.b64encode(bytes(64)).decode()}\n"
    )
    return base64.b64encode(text.encode()).decode()


def _artefact(directory: Path, name: str = NSIS, sig: str | None = REAL_SIGNATURE) -> Path:
    path = directory / name
    path.write_bytes(b"installer")
    if sig is not None:
        (directory / f"{name}.sig").write_text(sig + "\n", encoding="ascii")
    return path


def _build(artefacts: list[Path], version: str = "1.1.0-rc.1") -> dict[str, object]:
    manifest: dict[str, object] = um.build_manifest(
        version, "Fixed things.", BASE_URL, artefacts, REAL_PUBKEY, datetime.now(UTC)
    )
    return manifest


def test_the_manifest_has_the_shape_the_updater_reads(tmp_path: Path) -> None:
    now = datetime(2026, 11, 14, 17, 30, 5, tzinfo=UTC)
    manifest = um.build_manifest(
        "1.1.0-rc.1", "Fixed things.", BASE_URL + "/", [_artefact(tmp_path)], REAL_PUBKEY, now
    )

    assert manifest == {
        "version": "1.1.0-rc.1",
        "notes": "Fixed things.",
        "pub_date": "2026-11-14T17:30:05Z",
        "platforms": {
            "windows-x86_64-nsis": {
                "signature": REAL_SIGNATURE,
                "url": f"{BASE_URL}/{NSIS}",
            }
        },
    }


@pytest.mark.parametrize(
    ("name", "platform"),
    [
        ("Reframe_1.0.0_amd64.AppImage", "linux-x86_64-appimage"),
        ("Reframe_1.0.0_amd64.deb", "linux-x86_64-deb"),
    ],
)
def test_each_updatable_install_gets_its_own_target(name: str, platform: str) -> None:
    assert um.platform_of(name) == platform


@pytest.mark.parametrize(
    "name", ["Reframe_1.0.0_x64_en-US.msi", "Reframe-1.0.0-1.x86_64.rpm", "Reframe_1.0.0.zip"]
)
def test_an_install_the_app_never_updates_gets_no_entry(name: str) -> None:
    with pytest.raises(um.ManifestError, match="not an updater artefact"):
        um.platform_of(name)


def test_a_signature_for_another_version_is_refused(tmp_path: Path) -> None:
    sig = _signature(comment=f"timestamp:1\tfile:{NSIS}\tversion:1.0.0")

    with pytest.raises(
        um.ManifestError, match=re.escape("signed for version 1.0.0, not 1.1.0-rc.1")
    ):
        _build([_artefact(tmp_path, sig=sig)])


def test_a_signature_without_a_version_is_refused(tmp_path: Path) -> None:
    sig = _signature(comment=f"timestamp:1\tfile:{NSIS}")

    with pytest.raises(um.ManifestError, match=re.escape("--app-version 1.1.0-rc.1")):
        _build([_artefact(tmp_path, sig=sig)])


def test_the_signature_of_another_file_is_refused(tmp_path: Path) -> None:
    sig = _signature(
        comment="timestamp:1\tfile:Reframe_1.1.0-rc.1_x64_en-US.msi\tversion:1.1.0-rc.1"
    )

    with pytest.raises(
        um.ManifestError, match=re.escape("signature of Reframe_1.1.0-rc.1_x64_en-US.msi")
    ):
        _build([_artefact(tmp_path, sig=sig)])


def test_a_key_the_app_does_not_trust_is_refused(tmp_path: Path) -> None:
    config = json.loads((REPO_ROOT / "desktop/src-tauri/tauri.conf.json").read_text("utf-8"))
    committed = config["plugins"]["updater"]["pubkey"]

    with pytest.raises(um.ManifestError) as error:
        um.build_manifest(
            "1.1.0-rc.1", "", BASE_URL, [_artefact(tmp_path)], committed, datetime.now(UTC)
        )

    trusted = um.key_id_text(um.public_key_id(committed))
    assert f"signed with key D7312F832FCC9670, but the app trusts key {trusted}" in str(error.value)


def test_a_missing_signature_is_refused(tmp_path: Path) -> None:
    with pytest.raises(um.ManifestError, match=r"\.sig: no such file"):
        _build([_artefact(tmp_path, sig=None)])


def test_a_decoded_signature_file_is_refused(tmp_path: Path) -> None:
    decoded = base64.b64decode(REAL_SIGNATURE).decode()

    with pytest.raises(um.ManifestError, match="not base64-encoded"):
        _build([_artefact(tmp_path, sig=decoded)])


def test_two_artefacts_for_one_target_are_refused(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()

    with pytest.raises(um.ManifestError, match="a second artefact for windows-x86_64-nsis"):
        _build([_artefact(first), _artefact(second)])


def test_a_pep_440_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(um.ManifestError, match="not a SemVer version"):
        _build([_artefact(tmp_path)], version="1.1.0rc1")


def test_a_download_url_without_https_is_refused(tmp_path: Path) -> None:
    with pytest.raises(um.ManifestError, match="only over https"):
        um.build_manifest(
            "1.1.0-rc.1",
            "",
            "http://example.org/download",
            [_artefact(tmp_path)],
            REAL_PUBKEY,
            datetime.now(UTC),
        )


def test_the_command_writes_latest_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "tauri.conf.json"
    config.write_text(json.dumps({"plugins": {"updater": {"pubkey": REAL_PUBKEY}}}), "utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("### Fixed\n\n- F-17: things\n\n", encoding="utf-8")
    out = tmp_path / "latest.json"
    argv = ["--version", "1.1.0-rc.1", "--notes", str(notes), "--base-url", BASE_URL]
    argv += ["--out", str(out), "--tauri-config", str(config), str(_artefact(tmp_path))]

    assert um.main(argv) == 0

    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["notes"] == "### Fixed\n\n- F-17: things"
    assert list(manifest["platforms"]) == ["windows-x86_64-nsis"]
    assert capsys.readouterr().out.strip() == str(out)


def test_a_refused_signature_writes_no_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("", encoding="utf-8")
    out = tmp_path / "latest.json"
    argv = ["--version", "1.1.0-rc.1", "--notes", str(notes), "--base-url", BASE_URL]
    argv += ["--out", str(out), str(_artefact(tmp_path))]

    assert um.main(argv) == 1

    assert not out.exists()
    assert "the app trusts key" in capsys.readouterr().err
