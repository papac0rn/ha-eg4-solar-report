"""EG4 Monitor Center access through pylxpweb.

This is unofficial access. EG4 publishes no API, so it may break if EG4 changes their site.
pylxpweb is the same library the EG4 Web Monitor integration uses; the manifest requirement is kept
compatible with its pin so both can be installed together.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import aiohttp
from pylxpweb import LuxpowerClient
from pylxpweb.exceptions import LuxpowerAuthError, LuxpowerError

_LOGGER = logging.getLogger(__name__)

# Device type 9 is a GridBOSS/MID controller, which has no inverter export
DEVICE_TYPE_GRIDBOSS = 9
# The server returns at most 10 day-sheets from the start date
MAX_EXPORT_DAYS = 10
XLS_SIGNATURE = b"\xd0\xcf\x11\xe0"


class Eg4Error(Exception):
    """Monitor Center request failed."""


class Eg4AuthError(Eg4Error):
    """Login was rejected."""


class Eg4MonitorClient:
    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, username: str, password: str
    ) -> None:
        self._client = LuxpowerClient(username, password, base_url=base_url, session=session)

    async def async_login(self) -> None:
        try:
            await self._client.login()
        except LuxpowerAuthError as err:
            raise Eg4AuthError(str(err) or "Login rejected") from err
        except LuxpowerError as err:
            raise Eg4Error(str(err)) from err

    async def async_get_plants(self) -> list[dict[str, Any]]:
        try:
            resp = await self._client.plants.get_plants(rows=50)
        except LuxpowerAuthError as err:
            raise Eg4AuthError(str(err)) from err
        except LuxpowerError as err:
            raise Eg4Error(str(err)) from err
        return [{"plant_id": str(p.plantId), "name": p.name or str(p.plantId)} for p in resp.rows]

    async def async_get_inverters(self, plant_id: str) -> list[dict[str, Any]]:
        try:
            resp = await self._client.devices.get_devices(int(plant_id))
        except LuxpowerAuthError as err:
            raise Eg4AuthError(str(err)) from err
        except LuxpowerError as err:
            raise Eg4Error(str(err)) from err
        return [
            {"serial": d.serialNum, "model": d.deviceTypeText or ""}
            for d in resp.rows
            if d.serialNum and d.deviceType != DEVICE_TYPE_GRIDBOSS
        ]

    async def async_download_export(self, serial: str, start: date, end: date) -> bytes:
        """Return the .xls data export for one inverter, one sheet per day (at most 10 days)."""
        if (end - start).days + 1 > MAX_EXPORT_DAYS:
            raise Eg4Error(f"An export covers at most {MAX_EXPORT_DAYS} days")
        try:
            content = await self._client.export.export_data(
                serial, start.isoformat(), end.isoformat() if end != start else None
            )
        except LuxpowerAuthError as err:
            raise Eg4AuthError(str(err)) from err
        except LuxpowerError as err:
            raise Eg4Error(f"Export download failed: {err}") from err
        # An expired session or server error answers with an HTML page instead of the workbook
        if not content.startswith(XLS_SIGNATURE):
            raise Eg4Error("The Monitor Center did not return an .xls export")
        return content

    async def async_close(self) -> None:
        # The HA-managed session is closed by HA; this only drops the client's own state
        try:
            await self._client.close()
        except LuxpowerError:
            pass
