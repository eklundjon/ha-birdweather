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
            serial_number=self._station_id,
            configuration_url=f"https://app.birdweather.com/stations/{self._station_id}",
        )
