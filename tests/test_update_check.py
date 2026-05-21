from __future__ import annotations

from datetime import UTC, datetime

from local_translation_workbench import update_check


def _release_payload(tag_name: str) -> dict[str, object]:
    version = tag_name.removeprefix("v")
    return {
        "tag_name": tag_name,
        "html_url": f"https://github.com/gyyxs88/local_translation_workbench-releases/releases/tag/{tag_name}",
        "assets": [
            {
                "name": f"local_translation_workbench-{version}.zip",
                "browser_download_url": f"https://example.test/local_translation_workbench-{version}.zip",
            },
            {
                "name": f"local_translation_workbench-{version}.zip.sha256",
                "browser_download_url": f"https://example.test/local_translation_workbench-{version}.zip.sha256",
            },
        ],
    }


def test_check_for_update_reports_newer_release():
    result = update_check.check_for_update(
        current_version="0.1.3",
        fetch_json=lambda url, timeout_seconds: _release_payload("v0.1.4"),
        now=lambda: datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "ok"
    assert result["current_version"] == "0.1.3"
    assert result["latest_version"] == "0.1.4"
    assert result["update_available"] is True
    assert result["release_url"].endswith("/v0.1.4")
    assert result["download_url"].endswith("local_translation_workbench-0.1.4.zip")
    assert result["sha256_url"].endswith("local_translation_workbench-0.1.4.zip.sha256")
    assert result["checked_at"] == "2026-05-21T12:00:00+00:00"


def test_check_for_update_reports_current_release():
    result = update_check.check_for_update(
        current_version="0.1.3",
        fetch_json=lambda url, timeout_seconds: _release_payload("v0.1.3"),
    )

    assert result["status"] == "ok"
    assert result["latest_version"] == "0.1.3"
    assert result["update_available"] is False


def test_check_for_update_compares_multi_digit_patch_versions():
    result = update_check.check_for_update(
        current_version="0.1.9",
        fetch_json=lambda url, timeout_seconds: _release_payload("v0.1.10"),
    )

    assert result["latest_version"] == "0.1.10"
    assert result["update_available"] is True


def test_check_for_update_is_non_blocking_when_release_lookup_fails():
    def raise_offline(url: str, timeout_seconds: float) -> dict[str, object]:
        raise OSError("offline")

    result = update_check.check_for_update(
        current_version="0.1.3",
        fetch_json=raise_offline,
        now=lambda: datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
    )

    assert result["status"] == "unavailable"
    assert result["current_version"] == "0.1.3"
    assert result["latest_version"] is None
    assert result["update_available"] is False
    assert result["error"]["type"] == "OSError"
    assert "offline" in result["error"]["message"]
