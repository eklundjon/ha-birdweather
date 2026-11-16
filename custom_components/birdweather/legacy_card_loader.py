"""Cleanup for the /local card loader that 0.6.0 and 0.7.0 installed.

Those versions copied birdweather-card-loader.js into config/www and registered
/local/birdweather-card-loader.js as a Lovelace resource, so the cards would also
load on pages opened while HA was still starting. An integration shouldn't
write into the user's www folder: the copy outlives an uninstall, and
everything under /local is served without authentication. The cards now
handle HA's scoped registry polyfill themselves (see _defineElement in the
card modules), and this removes what the older versions left behind.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant

from .card_resources import async_storage_resources

_LOGGER = logging.getLogger(__name__)

LOADER_FILE = "birdweather-card-loader.js"
LOADER_URL = f"/local/{LOADER_FILE}"


async def async_remove_legacy_card_loader(hass: HomeAssistant) -> None:
    """Delete the old loader's Lovelace resource and its copy in config/www.

    Idempotent, so it runs on every setup. Best-effort: a leftover only costs
    a 404 in the browser console, so log and carry on rather than fail setup.
    """
    try:
        resources = await async_storage_resources(hass)
        if resources is not None:
            for item in _our_items(resources):
                await resources.async_delete_item(item["id"])
        await hass.async_add_executor_job(_loader_path(hass).unlink, True)
    except Exception:
        _LOGGER.warning("Couldn't remove the old BirdWeather card loader", exc_info=True)


def _loader_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", LOADER_FILE))


def _our_items(resources: ResourceStorageCollection) -> list[dict]:
    # Match on path only: the ?v= query changed with every release.
    return [
        item
        for item in resources.async_items()
        if urlsplit(item.get("url", "")).path == LOADER_URL
    ]
