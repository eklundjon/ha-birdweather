from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BirdWeatherCoordinator


class BirdWeatherEntity(CoordinatorEntity[BirdWeatherCoordinator]):
    """Base for every BirdWeather entity (sensors + the binary sensor).

    Holds the single DeviceInfo so the platform files don't each repeat it.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator)
        self._station_id = station_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=self.coordinator.device_name,
            manufacturer="BirdWeather",
            model="BirdWeather Station",
            # No serial_number: a BirdWeather station ID isn't a serial number, and
            # HA's device page labels that field "Serial number" (core frontend
            # text we can't relabel). The ID stays reachable via configuration_url.
            configuration_url=f"https://app.birdweather.com/stations/{self._station_id}",
        )
