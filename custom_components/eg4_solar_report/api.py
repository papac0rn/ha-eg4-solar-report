"""Minimal client for the EG4 Monitor Center (Luxpower WManage) web API.

This is unofficial access. EG4 publishes no API, so these endpoints may change without notice.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOGIN_PATH = "/WManage/api/login"
PLANT_LIST_PATH = "/WManage/web/config/plant/list/viewer"
INVERTER_LIST_PATH = "/WManage/api/inverterOverview/list"
# UNCONFIRMED (SPEC-022 prerequisite 2): the per-day data export the prototype reads (.xls)
EXPORT_PATH = "/WManage/web/analyze/data/export/{serial}/{day}"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)


class Eg4Error(Exception):
    """Monitor Center request failed."""


class Eg4AuthError(Eg4Error):
    """Login was rejected."""


class Eg4MonitorClient:
    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, username: str, password: str
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._logged_in = False

    async def async_login(self) -> None:
        data = await self._post_json(
            LOGIN_PATH,
            {"account": self._username, "password": self._password},
            login=True,
        )
        if not data.get("success"):
            self._logged_in = False
            raise Eg4AuthError(data.get("msg") or "Login rejected")
        self._logged_in = True

    async def async_get_plants(self) -> list[dict[str, Any]]:
        data = await self._post_json(PLANT_LIST_PATH, {"page": 1, "rows": 50})
        return [
            {"plant_id": str(row.get("plantId")), "name": row.get("name") or str(row.get("plantId"))}
            for row in data.get("rows", [])
        ]

    async def async_get_inverters(self, plant_id: str) -> list[dict[str, Any]]:
        data = await self._post_json(
            INVERTER_LIST_PATH, {"plantId": plant_id, "page": 1, "rows": 50}
        )
        return [
            {
                "serial": row.get("serialNum"),
                "model": row.get("deviceTypeText4APP") or row.get("deviceTypeText") or "",
            }
            for row in data.get("rows", [])
            if row.get("serialNum")
        ]

    async def async_download_export(self, serial: str, day: date) -> bytes:
        """Return one day's data export for one inverter."""
        if not self._logged_in:
            await self.async_login()
        path = EXPORT_PATH.format(serial=serial, day=day.isoformat())
        for attempt in (1, 2):
            try:
                async with self._session.get(
                    self._base_url + path, timeout=REQUEST_TIMEOUT
                ) as resp:
                    body = await resp.read()
                    content_type = resp.headers.get("Content-Type", "")
            except (aiohttp.ClientError, TimeoutError) as err:
                raise Eg4Error(f"Export download failed: {err}") from err
            # An expired session answers with the HTML login page instead of a file
            if resp.status == 200 and "html" not in content_type:
                return body
            if attempt == 1 and (resp.status in (401, 403) or "html" in content_type):
                await self.async_login()
                continue
            raise Eg4Error(f"Export download failed: HTTP {resp.status} ({content_type})")
        raise Eg4Error("Export download failed")

    async def _post_json(
        self, path: str, form: dict[str, Any], login: bool = False
    ) -> dict[str, Any]:
        if not login and not self._logged_in:
            await self.async_login()
        for attempt in (1, 2):
            try:
                async with self._session.post(
                    self._base_url + path, data=form, timeout=REQUEST_TIMEOUT
                ) as resp:
                    if resp.status in (401, 403) and not login and attempt == 1:
                        await self.async_login()
                        continue
                    if resp.status != 200:
                        raise Eg4Error(f"{path}: HTTP {resp.status}")
                    try:
                        return await resp.json(content_type=None)
                    except ValueError as err:
                        if not login and attempt == 1:
                            # Expired session: HTML login page instead of JSON
                            await self.async_login()
                            continue
                        raise Eg4Error(f"{path}: response was not JSON") from err
            except (aiohttp.ClientError, TimeoutError) as err:
                raise Eg4Error(f"{path}: {err}") from err
        raise Eg4Error(f"{path}: session could not be restored")
