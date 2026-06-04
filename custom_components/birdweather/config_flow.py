from __future__ import annotations

from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .client import BirdWeatherClient, BirdWeatherError
from .const import (
    CONF_ABSENCE_DAYS,
    CONF_NOTABLE_RARITY_WEIGHT,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_WATCHED_EXTRA,
    CONF_WATCHED_SPECIES,
    DEFAULT_ABSENCE_DAYS,
    DEFAULT_NOTABLE_RARITY_WEIGHT,
    DEFAULT_RADIUS_KM,
    DOMAIN,
)


def _station_label(s: dict[str, Any]) -> str:
    region = s.get("state") or s.get("country") or ""
    dist = s.get("distance_km")
    parts = [s.get("name") or f"Station {s['id']}"]
    if region:
        parts.append(region)
    if dist is not None:
        parts.append(f"{dist:.0f} km")
    return " · ".join(parts)


class BirdWeatherConfigFlow(ConfigFlow, domain=DOMAIN):
    """Onboarding: discover a nearby public BirdWeather station (or search)."""

    VERSION = 1

    def __init__(self) -> None:
        self._search: str = ""

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return BirdWeatherOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        client = BirdWeatherClient(async_get_clientsession(self.hass))

        if user_input is not None:
            station_id = (user_input.get(CONF_STATION_ID) or "").strip()
            search = (user_input.get("search") or "").strip()

            if station_id:
                # A station was chosen (dropdown) or pasted (custom value).
                try:
                    station = await client.get_station(station_id)
                except (aiohttp.ClientError, BirdWeatherError):
                    station = None
                    errors["base"] = "cannot_connect"
                if not errors and station is None:
                    errors["base"] = "invalid_station"
                if not errors:
                    await self.async_set_unique_id(station_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=station["name"],
                        data={
                            CONF_STATION_ID: station_id,
                            CONF_STATION_NAME: station["name"],
                        },
                    )
            elif search:
                # Re-run discovery as a name search and re-render the form.
                self._search = search
            else:
                errors["base"] = "no_selection"

        # Build the station list: free-text search if given, else nearby.
        stations: list[dict[str, Any]] = []
        try:
            if self._search:
                stations = await client.search_stations(query=self._search, first=25)
            else:
                lat = self.hass.config.latitude
                lon = self.hass.config.longitude
                if lat is not None and lon is not None:
                    stations = await client.nearby_stations(
                        lat, lon, radius_km=DEFAULT_RADIUS_KM, first=25
                    )
        except (aiohttp.ClientError, BirdWeatherError):
            if not errors:
                errors["base"] = "cannot_connect"

        options = [
            SelectOptionDict(value=str(s["id"]), label=_station_label(s))
            for s in stations
        ]

        schema = vol.Schema(
            {
                vol.Optional("search", default=self._search): TextSelector(),
                vol.Optional(CONF_STATION_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=True,
                        sort=False,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"count": str(len(options))},
        )


class BirdWeatherOptionsFlow(OptionsFlow):
    """Per-entry options: notability blend + unusual-visitor threshold."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.config_entry.options

        # Watch-list picker: union of species the station has detected with any
        # already-saved selections (so a saved name that's since dropped off the
        # seen list isn't silently lost from the dropdown).
        coordinator = getattr(self.config_entry, "runtime_data", None)
        known = coordinator.known_species if coordinator else []
        saved = opts.get(CONF_WATCHED_SPECIES) or []
        watch_options = [
            SelectOptionDict(value=n, label=n)
            for n in sorted(set(known) | set(saved))
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NOTABLE_RARITY_WEIGHT,
                        default=opts.get(
                            CONF_NOTABLE_RARITY_WEIGHT, DEFAULT_NOTABLE_RARITY_WEIGHT
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=100, step=5,
                            mode=NumberSelectorMode.SLIDER,
                            unit_of_measurement="%",
                        )
                    ),
                    vol.Required(
                        CONF_ABSENCE_DAYS,
                        default=opts.get(CONF_ABSENCE_DAYS, DEFAULT_ABSENCE_DAYS),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=365, step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="days",
                        )
                    ),
                    vol.Optional(
                        CONF_WATCHED_SPECIES, default=saved
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=watch_options,
                            multiple=True,
                            custom_value=False,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_WATCHED_EXTRA,
                        default=opts.get(CONF_WATCHED_EXTRA, ""),
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                }
            ),
        )
