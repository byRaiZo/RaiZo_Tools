import hashlib
import json

from core import updater


def test_release_asset_selection_requires_exact_versioned_name():
    wanted = {
        "name": "RaiZo_Tools-v1.2.3-win64.zip",
        "browser_download_url": "https://example.invalid/release.zip",
    }
    checksum = {
        "name": "RaiZo_Tools-v1.2.3-win64.zip.sha256",
        "browser_download_url": "https://example.invalid/release.zip.sha256",
    }
    wrong = {"name": "other.zip", "browser_download_url": "https://example.invalid/other.zip"}

    assert updater._pick_assets([wrong, checksum, wanted], "1.2.3") == (wanted, checksum)
    assert updater._pick_assets([wrong], "1.2.3") == (None, None)


def test_checksum_parser_rejects_wrong_filename_and_invalid_digest():
    digest = hashlib.sha256(b"release").hexdigest()
    name = "RaiZo_Tools-v1.2.3-win64.zip"

    assert updater._checksum_sha256(f"{digest}  {name}\n", name) == digest
    assert updater._checksum_sha256(f"{digest}  wrong.zip\n", name) == ""
    assert updater._digest_sha256("sha512:" + digest) == ""
    assert updater._digest_sha256("sha256:not-a-hash") == ""


def test_release_without_digest_or_sidecar_is_not_downloadable():
    release = updater.Release("1.2.3", "Release", "", "", asset_url="https://example.invalid/x.zip")

    assert release.downloadable is False


def test_download_is_blocked_when_sha256_is_missing(monkeypatch, tmp_path):
    release = updater.Release(
        "1.2.3",
        "Release",
        "",
        "",
        asset_name="RaiZo_Tools-v1.2.3-win64.zip",
        asset_url="https://example.invalid/release.zip",
    )
    failures = []
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path)
    worker = updater.DownloadWorker(release)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == ["обновление заблокировано: отсутствует корректная SHA-256"]
    assert not list(tmp_path.iterdir())


def test_download_removes_archive_when_sha256_mismatches(monkeypatch, tmp_path):
    class Response:
        headers = {"Content-Length": "7"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size=-1):
            if hasattr(self, "sent"):
                return b""
            self.sent = True
            return b"payload"

    release = updater.Release(
        "1.2.3",
        "Release",
        "",
        "",
        asset_name="RaiZo_Tools-v1.2.3-win64.zip",
        asset_url="https://example.invalid/release.zip",
        digest="sha256:" + "0" * 64,
    )
    failures = []
    monkeypatch.setattr(updater, "UPDATE_DIR", tmp_path)
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    worker = updater.DownloadWorker(release)
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == ["контрольная сумма не совпала"]
    assert not (tmp_path / release.asset_name).exists()
    assert not (tmp_path / (release.asset_name + ".part")).exists()


def test_pending_release_cannot_escape_update_directory(monkeypatch, tmp_path):
    update_dir = tmp_path / "update"
    update_dir.mkdir()
    outside = tmp_path / "outside.zip"
    outside.write_bytes(b"keep")
    pending_file = update_dir / "pending.json"
    pending_file.write_text(
        json.dumps(
            {
                "version": "1.2.3",
                "name": "Release",
                "changelog": "",
                "page": "",
                "asset_name": "../outside.zip",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(updater, "UPDATE_DIR", update_dir)
    monkeypatch.setattr(updater, "_PENDING", pending_file)

    assert updater.pending() is None
    updater.clear_pending()

    assert outside.read_bytes() == b"keep"
