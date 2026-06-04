from __future__ import annotations

import math
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
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

    async_add_entities(
        [
            BirdWeatherRecentDetectionsSensor(coordinator, station_id),
            BirdWeatherLastDetectionSensor(coordinator, station_id),
            BirdWeatherDailyCountSensor(coordinator, station_id),
            BirdWeatherDailyTopSpeciesSensor(coordinator, station_id),
            BirdWeatherNotableSpeciesSensor(coordinator, station_id),
            BirdWeatherNewSpeciesSensor(coordinator, station_id),
            BirdWeatherYearlyTopSpeciesSensor(coordinator, station_id),
            BirdWeatherRarestSpeciesSensor(coordinator, station_id),
            BirdWeatherLifetimeSpeciesSensor(coordinator, station_id),
            BirdWeatherSpeciesDiversitySensor(coordinator, station_id),
            BirdWeatherActivitySensor(coordinator, station_id),
            BirdWeatherNewSpeciesWindowSensor(coordinator, station_id),
            BirdWeatherHistoryDepthSensor(coordinator, station_id),
            BirdWeatherWatchedSpeciesSensor(coordinator, station_id),
        ]
    )


class _BirdWeatherSensor(CoordinatorEntity[BirdWeatherCoordinator], SensorEntity):
    """Base class for BirdWeather sensors."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"detections"})

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
            configuration_url=f"https://app.birdweather.com/stations/{self._station_id}",
        )


class BirdWeatherRecentDetectionsSensor(_BirdWeatherSensor):
    """Number of species detected in the past hour."""

    _attr_translation_key = "recent_detections"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_recent_detections"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("recent_detections", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("recent_detections", [])}


class BirdWeatherLastDetectionSensor(_BirdWeatherSensor):
    """Name of the most recently detected species."""

    _attr_translation_key = "last_detection"
    _attr_icon = "mdi:bird"

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_last_detection"

    def _latest(self) -> dict | None:
        return self.coordinator.data.get("last_detection")

    @property
    def native_value(self) -> str | None:
        d = self._latest()
        return d.get("species") if d else None

    @property
    def entity_picture(self) -> str | None:
        d = self._latest()
        return d.get("image_url") if d else None

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("recent_events", [])}


class BirdWeatherDailyCountSensor(_BirdWeatherSensor):
    """Total individual detections over the trailing 24 hours.

    Sourced from BirdWeather's native `counts(period: 1 day)` — a true total,
    not capped or limited by detection-feed pagination.
    """

    _attr_translation_key = "daily_count"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "detections"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_daily_count"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("today_total")


class BirdWeatherDailyTopSpeciesSensor(_BirdWeatherSensor):
    """Top species by detection count over the trailing 24 hours."""

    _attr_translation_key = "daily_top_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_daily_top_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("daily_top_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("daily_top_species", [])}


class BirdWeatherNotableSpeciesSensor(_BirdWeatherSensor):
    """Most unusual species detected recently (rarity vs the station baseline)."""

    _attr_translation_key = "notable_species"
    _attr_icon = "mdi:bird-off"

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_notable_species"

    def _top(self) -> dict | None:
        return self.coordinator.data.get("notable_detection")

    @property
    def native_value(self) -> str | None:
        d = self._top()
        return d.get("species") if d else None

    @property
    def entity_picture(self) -> str | None:
        d = self._top()
        return d.get("image_url") if d else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self._top()
        attrs: dict = {"detections": self.coordinator.data.get("notable_detections", [])}
        if d:
            attrs["rarity_score"] = d.get("rarity_score")
            attrs["yearly_rank"] = d.get("yearly_rank")
        return attrs


class BirdWeatherNewSpeciesSensor(_BirdWeatherSensor):
    """Species never previously detected at this station (sticky lifetime log)."""

    _attr_translation_key = "new_species"
    _attr_icon = "mdi:new-box"

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_new_species"

    def _latest(self) -> dict | None:
        return self.coordinator.data.get("new_detection")

    @property
    def native_value(self) -> str | None:
        d = self._latest()
        return d.get("species") if d else None

    @property
    def entity_picture(self) -> str | None:
        d = self._latest()
        return d.get("image_url") if d else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self._latest()
        attrs: dict = {
            "detections": self.coordinator.data.get("new_detections", []),
            "lifetime_species_count": self.coordinator.data.get("lifetime_species_count", 0),
        }
        if d:
            attrs["first_seen"] = d.get("first_seen") or d.get("last_seen")
        return attrs


class BirdWeatherYearlyTopSpeciesSensor(_BirdWeatherSensor):
    """Top species by detection count over the station's baseline period."""

    _attr_translation_key = "yearly_top_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_yearly_top_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("yearly_top_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("yearly_top_species", [])}


class BirdWeatherRarestSpeciesSensor(_BirdWeatherSensor):
    """Rarest species over the rolling 7-day window (highest rarity score)."""

    _attr_translation_key = "rarest_species"
    _attr_icon = "mdi:chart-bar"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_rarest_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("rarest_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("rarest_species", [])}


class BirdWeatherLifetimeSpeciesSensor(_BirdWeatherSensor):
    """Count of distinct species ever detected at this station."""

    _attr_translation_key = "lifetime_species"
    _attr_icon = "mdi:binoculars"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_lifetime_species"

    @property
    def native_value(self) -> int:
        return self.coordinator.data.get("lifetime_species_count", 0)


class BirdWeatherSpeciesDiversitySensor(_BirdWeatherSensor):
    """Shannon diversity index (H′) over the trailing 24 hours.

    Combines richness (how many species) and evenness (how balanced their
    counts) into one number: higher = a more varied, balanced soundscape;
    a single dominant species pushes it toward 0. Richness and Pielou's
    evenness are exposed as attributes.
    """

    _attr_translation_key = "species_diversity"
    _attr_icon = "mdi:chart-bell-curve"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_species_diversity"

    def _counts(self) -> list[int]:
        return [
            int(s.get("count") or 0)
            for s in self.coordinator.data.get("today_top") or []
            if (s.get("count") or 0) > 0
        ]

    @property
    def native_value(self) -> float | None:
        counts = self._counts()
        total = sum(counts)
        if not total:
            return None
        h = -sum((c / total) * math.log(c / total) for c in counts)
        return round(h if h > 0 else 0.0, 4)

    @property
    def extra_state_attributes(self) -> dict:
        counts = self._counts()
        richness = len(counts)
        attrs: dict = {"richness": richness}
        value = self.native_value
        if value is not None and richness > 1:
            # Pielou's evenness J′ = H′ / ln(S): 0 = one species dominates,
            # 1 = perfectly even.
            attrs["evenness"] = round(value / math.log(richness), 4)
        return attrs


class BirdWeatherActivitySensor(_BirdWeatherSensor):
    """Bird activity relative to a typical day.

    The trailing-24h detection total divided by the station's average daily
    total over its baseline window — 1.0 ≈ a normal day, 2.0 ≈ twice as busy,
    0.5 ≈ half. `unknown` until a baseline exists.
    """

    _attr_translation_key = "activity_level"
    _attr_icon = "mdi:speedometer"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_activity_level"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        today = data.get("today_total")
        typical = data.get("typical_daily_count")
        if today is None or not typical:
            return None
        return round(today / typical, 2)

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data
        return {
            "detections_today": data.get("today_total"),
            "typical_daily_count": data.get("typical_daily_count"),
        }


class BirdWeatherNewSpeciesWindowSensor(_BirdWeatherSensor):
    """Number of species first heard at this station within the recent window.

    A momentum signal — how many genuinely new species have shown up lately
    (e.g. spring arrivals) — derived by diffing the station's recent vs.
    historical top-species sets.
    """

    _attr_translation_key = "new_species_window"
    _attr_icon = "mdi:new-box"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_new_species_window"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.get("new_species_window")


class BirdWeatherHistoryDepthSensor(_BirdWeatherSensor):
    """How far back this station's detection history reaches (diagnostic).

    The station's earliest recorded detection, straight from the BirdWeather
    API — useful context for the activity/lifetime figures.
    """

    _attr_translation_key = "history_start"
    _attr_icon = "mdi:clock-start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_history_start"

    @property
    def native_value(self) -> datetime | None:
        earliest = self.coordinator.data.get("history_earliest")
        if not earliest:
            return None
        try:
            # BirdWeather returns a tz-aware ISO timestamp (e.g. with -05:00).
            return datetime.fromisoformat(earliest)
        except ValueError:
            return None


class BirdWeatherWatchedSpeciesSensor(_BirdWeatherSensor):
    """Your watch-list species that this station has detected ("Birds of
    interest"), most-recently-heard first. State = how many are on record;
    `detections` is the list for the bird-list card. Configure the watch-list
    in the integration's options. Species you watch but the station hasn't
    recorded don't appear here — the watched-species device trigger covers
    their arrival.
    """

    _attr_translation_key = "watched_species"
    _attr_icon = "mdi:star"
    _attr_native_unit_of_measurement = "species"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: BirdWeatherCoordinator, station_id: str) -> None:
        super().__init__(coordinator, station_id)
        self._attr_unique_id = f"{station_id}_watched_species"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("watched_species", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"detections": self.coordinator.data.get("watched_species", [])}
