from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION_ID, DOMAIN
from .coordinator import BirdWeatherConfigEntry, BirdWeatherCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BirdWeatherConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    station_id = entry.data[CONF_STATION_ID]
    async_add_entities([BirdWeatherExtendedSilenceSensor(coordinator, station_id)])


class BirdWeatherExtendedSilenceSensor(
    CoordinatorEntity[BirdWeatherCoordinator], BinarySensorEntity
):
    """Problem sensor: on when the station has logged no detections in the
    trailing 24-hour window (an "extended silence").

    Derived from the 24-hour `detections_24h` list (empty → nothing heard in 24h).
    When the poll itself fails the coordinator goes unavailable, so this sensor
    is unavailable too — "we don't know" rather than a false problem.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "extended_silence"
    # Device-health signal (is the station reporting?), not a bird observation —
    # so it belongs in the device's Diagnostic section. Still fully usable in
    # automations/alerts; entity_id and history are unchanged.
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._attr_unique_id = f"{station_id}_extended_silence"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self.coordinator.device_name,
            manufacturer="BirdWeather",
            model="BirdWeather Station",
            configuration_url=f"https://app.birdweather.com/stations/{self._station_id}",
        )

    @property
    def is_on(self) -> bool:
        return not (self.coordinator.data.get("detections_24h") or [])
