from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from . import __version__

PACKAGE_DISTRIBUTION_NAME = "local-translation-workbench"
PUBLIC_RELEASE_REPO = "gyyxs88/local_translation_workbench-releases"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{PUBLIC_RELEASE_REPO}/releases/latest"
DEFAULT_TIMEOUT_SECONDS = 2.0
DEFAULT_INTERVAL_HOURS = 24.0

JsonFetcher = Callable[[str, float], dict[str, Any]]
Clock = Callable[[], datetime]

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def installed_version() -> str:
    if __version__:
        return __version__
    try:
        return metadata.version(PACKAGE_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return __version__


def check_for_update(
    *,
    current_version: str | None = None,
    fetch_json: JsonFetcher | None = None,
    now: Clock | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    current = _normalize_version(current_version or installed_version())
    checked_at = _utc_now(now).isoformat()
    if _env_truthy("LTW_DISABLE_UPDATE_CHECK"):
        return _base_result("disabled", current, checked_at)

    fetch = fetch_json or _fetch_json
    timeout = timeout_seconds if timeout_seconds is not None else _env_float(
        "LTW_UPDATE_CHECK_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )
    try:
        release = fetch(LATEST_RELEASE_API_URL, timeout)
    except Exception as exc:  # noqa: BLE001 - 更新提醒不能阻断 doctor 或 CLI。
        result = _base_result("unavailable", current, checked_at)
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return result

    latest = _normalize_version(str(release.get("tag_name") or ""))
    result = _base_result("ok", current, checked_at)
    result.update(
        {
            "latest_version": latest or None,
            "update_available": _is_newer_version(latest, current),
            "release_url": release.get("html_url"),
            "download_url": _find_download_url(release, ".zip"),
            "sha256_url": _find_download_url(release, ".zip.sha256"),
        }
    )
    return result


def maybe_check_for_update(
    *,
    fetch_json: JsonFetcher | None = None,
    now: Clock | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    if _env_truthy("LTW_DISABLE_UPDATE_CHECK"):
        return _base_result("disabled", _normalize_version(installed_version()), _utc_now(now).isoformat())

    clock_now = _utc_now(now)
    cache_file = cache_path or _cache_path()
    interval_hours = _env_float("LTW_UPDATE_CHECK_INTERVAL_HOURS", DEFAULT_INTERVAL_HOURS)
    cached = _read_fresh_cache(cache_file, clock_now, interval_hours)
    if cached is not None:
        cached["cached"] = True
        return cached

    result = check_for_update(fetch_json=fetch_json, now=lambda: clock_now)
    _write_cache(cache_file, result)
    result["cached"] = False
    return result


def run() -> int:
    print(json.dumps(check_for_update(), ensure_ascii=False))
    return 0


def _base_result(status: str, current_version: str, checked_at: str) -> dict[str, Any]:
    return {
        "status": status,
        "current_version": current_version,
        "latest_version": None,
        "update_available": False,
        "release_url": None,
        "download_url": None,
        "sha256_url": None,
        "checked_at": checked_at,
    }


def _fetch_json(url: str, timeout_seconds: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"local-translation-workbench/{installed_version()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        payload = response.read().decode(charset)
    return json.loads(payload)


def _find_download_url(release: dict[str, Any], suffix: str) -> str | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None

    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        url = asset.get("browser_download_url")
        if suffix == ".zip" and name.endswith(".zip.sha256"):
            continue
        if name.endswith(suffix) and isinstance(url, str):
            return url
    return None


def _normalize_version(value: str) -> str:
    return value.strip().removeprefix("v")


def _is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _parse_version(latest)
    current_parts = _parse_version(current)
    if latest_parts is None or current_parts is None:
        return False
    return latest_parts > current_parts


def _parse_version(value: str) -> tuple[int, int, int] | None:
    match = _VERSION_RE.match(value.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _utc_now(now: Clock | None = None) -> datetime:
    value = now() if now else datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _env_truthy(name: str) -> bool:
    value = os.getenv(name)
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _cache_path() -> Path:
    configured = os.getenv("LTW_UPDATE_CHECK_CACHE_PATH")
    if configured:
        return Path(configured)

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "local_translation_workbench" / "update_check.json"

    return Path.home() / ".cache" / "local_translation_workbench" / "update_check.json"


def _read_fresh_cache(cache_file: Path, now: datetime, interval_hours: float) -> dict[str, Any] | None:
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    checked_at = payload.get("checked_at")
    if not isinstance(checked_at, str):
        return None

    try:
        checked_time = datetime.fromisoformat(checked_at)
    except ValueError:
        return None
    if checked_time.tzinfo is None:
        checked_time = checked_time.replace(tzinfo=timezone.utc)

    if now - checked_time.astimezone(timezone.utc) <= timedelta(hours=interval_hours):
        return payload if isinstance(payload, dict) else None
    return None


def _write_cache(cache_file: Path, result: dict[str, Any]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return
