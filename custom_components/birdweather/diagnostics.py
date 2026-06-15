from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_STATION_ID, CONF_STATION_NAME
from .coordinator import BirdWeatherConfigEntry

# The station id / name identify the station; redact them from diagnostics
# shared in bug reports. entry.as_dict() exposes the id in several places, so
# redact them all: data[station_id], the unique_id (which IS the station id), and
# title / station_name (the station's name). async_redact_data matches these keys
# at any depth. (The id is semi-public — it appears in app.birdweather.com URLs —
# but a bug report needn't broadcast it.)
TO_REDACT = {CONF_STATION_ID, CONF_STATION_NAME, "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BirdWeatherConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    fetched = coordinator.baseline_fetched_date

    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "baseline_species_count": coordinator.baseline_species_count,
            "baseline_fetched_date": fetched.isoformat() if fetched else None,
            "lifetime_species_count": coordinator.lifetime_species_count,
        },
        "data": coordinator.data,
    }
