"""Startup loader for the BirdWeather cards (see www/birdweather-card-loader.js).

add_extra_js_url alone isn't enough: HA serves index.html before stage-2
integrations set up, bakes the extra-module list into it at render time, and
never loads modules added afterwards. A page loaded during startup — which is
when a reconnecting browser or Companion app reloads — gets no card JS, and
every BirdWeather card stays a "Custom element doesn't exist" error.

The fix is to have something in the page from the first render that is served
from the first request:
  * The loader file is copied to config/www, served at /local — mounted by the
    frontend integration before the web server starts, unlike our own static
    path, which only exists once our async_setup has run.
  * It's registered as a Lovelace resource, which is persisted in .storage and
    so is listed for the page even during startup.
The loader then retries the real card imports until our static path is up.

It also covers a second failure that looks the same in the browser: where HA
installs its scoped custom element registry polyfill (older WebKit), a card
module that ran before the polyfill defined its element on the native
registry, which the polyfill can't see. The loader only counts a card as
loaded once the current registry has it, and otherwise re-runs the module
under a fresh URL. See the header of www/birdweather-card-loader.js.

Resources only exist in storage mode; YAML-mode dashboards still get the cards
via add_extra_js_url but must list the loader themselves to cover startup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

LOADER_FILE = "birdweather-card-loader.js"
LOADER_URL = f"/local/{LOADER_FILE}"


async def async_install_card_loader(hass: HomeAssistant, version: str) -> None:
    """Copy the loader into config/www and register it as a Lovelace resource.

    Best-effort: on failure the cards still load via add_extra_js_url on any
    page rendered after setup, so log and carry on rather than fail setup.
    """
    try:
        await hass.async_add_executor_job(_copy_loader, hass)
        # ?v= busts the browser cache on upgrade (/local is served with long
        # cache headers) and hands the loader the version for the card URLs.
        await _async_register_resource(hass, f"{LOADER_URL}?v={version}")
    except Exception:
        _LOGGER.warning(
            "Couldn't install the BirdWeather card loader; cards may show "
            "\"Custom element doesn't exist\" after a restart until the page "
            "is refreshed",
            exc_info=True,
        )


async def async_remove_card_loader(hass: HomeAssistant) -> None:
    """Undo async_install_card_loader (the last BirdWeather entry was removed)."""
    resources = await _async_storage_resources(hass)
    if resources is not None:
        for item in _our_items(resources):
            await resources.async_delete_item(item["id"])
    await hass.async_add_executor_job(_loader_path(hass).unlink, True)


def _loader_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("www", LOADER_FILE))


def _copy_loader(hass: HomeAssistant) -> None:
    data = (Path(__file__).parent / "www" / LOADER_FILE).read_bytes()
    dest = _loader_path(hass)
    try:
        if dest.read_bytes() == data:
            return  # unchanged — don't rewrite on every start
    except OSError:
        pass
    # Creating config/www on a fresh install only takes effect after the next
    # restart (/local is mounted only if the dir exists at frontend setup); until
    # then the resource 404s harmlessly and add_extra_js_url covers normal loads.
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


async def _async_storage_resources(
    hass: HomeAssistant,
) -> ResourceStorageCollection | None:
    """The loaded resource collection, or None when it isn't ours to edit.

    In YAML mode the collection is a read-only ResourceYAMLCollection.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    resources = lovelace.resources if lovelace is not None else None
    if not isinstance(resources, ResourceStorageCollection):
        return None
    # The collection loads lazily (on first websocket list); mirror what HA's
    # own handlers do so async_items() reflects what's on disk.
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True
    return resources


def _our_items(resources: ResourceStorageCollection) -> list[dict]:
    # Match on path only: the ?v= query changes with every release.
    return [
        item
        for item in resources.async_items()
        if urlsplit(item.get("url", "")).path == LOADER_URL
    ]


async def _async_register_resource(hass: HomeAssistant, url: str) -> None:
    """Ensure exactly one module resource points at `url`."""
    resources = await _async_storage_resources(hass)
    if resources is None:
        _LOGGER.debug(
            "Lovelace isn't in storage mode; not registering %s as a resource",
            LOADER_URL,
        )
        return
    ours = _our_items(resources)
    if not ours:
        await resources.async_create_item({"res_type": "module", "url": url})
        return
    first, *extras = ours
    if first.get("url") != url or first.get("type") != "module":
        await resources.async_update_item(
            first["id"], {"res_type": "module", "url": url}
        )
    for item in extras:
        await resources.async_delete_item(item["id"])
