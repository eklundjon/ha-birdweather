from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfPressure,
    UnitOfSoundPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_STATION_ID, DOMAIN
from .coordinator import BirdWeatherConfigEntry, BirdWeatherCoordinator

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class BirdWeatherSensorDescription(SensorEntityDescription):
    """Describes a PUC onboard hardware sensor: which sensor sub-suite it reads
    (`environment` / `light` / `system`), how to pull its value from that
    suite's latest reading, and optionally extra attributes to expose."""

    suite: str
    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


def _sd_free_pct(s: dict[str, Any]) -> float | None:
    """Percent of SD card free, from the BigInt available/capacity (strings)."""
    try:
        avail = int(s.get("sdAvailable"))
        cap = int(s.get("sdCapacity"))
    except (TypeError, ValueError):
        return None
    return round(avail / cap * 100, 1) if cap > 0 else None


def _sd_attrs(s: dict[str, Any]) -> dict[str, Any]:
    """Free / total SD capacity in GB, as context for the free-percent state."""
    try:
        avail = int(s.get("sdAvailable"))
        cap = int(s.get("sdCapacity"))
    except (TypeError, ValueError):
        return {}
    gb = 1_000_000_000
    return {"free_gb": round(avail / gb, 1), "capacity_gb": round(cap / gb, 1)}


# PUC onboard hardware sensors. Created conditionally — only for sub-suites the
# station actually reports (a BirdNET-Pi has none). See client _SENSORS_QUERY for
# why eco2 is excluded. Spectral light is reduced to the broadband `clear`
# channel (a luminance proxy; not lux, so no illuminance device class).
HARDWARE_SENSORS: tuple[BirdWeatherSensorDescription, ...] = (
    BirdWeatherSensorDescription(
        key="temperature",
        translation_key="env_temperature",
        suite="environment",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.get("temperature"),
    ),
    BirdWeatherSensorDescription(
        key="humidity",
        translation_key="env_humidity",
        suite="environment",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.get("humidity"),
    ),
    BirdWeatherSensorDescription(
        key="barometric_pressure",
        translation_key="env_pressure",
        suite="environment",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda s: s.get("barometricPressure"),
    ),
    BirdWeatherSensorDescription(
        key="sound_pressure",
        translation_key="env_sound_pressure",
        suite="environment",
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.get("soundPressureLevel"),
    ),
    BirdWeatherSensorDescription(
        # BME688 bVOCeq (breath-VOC-equivalent) from Bosch's BSEC library — an
        # estimate in ppm, anchored to ~0.5 ppm in clean air; maps cleanly to the
        # parts-ratio VOC device class. (Some stations read a constant 0.125 ppm
        # floor when the gas sensor isn't calibrated — a valid low reading.)
        key="voc",
        translation_key="env_voc",
        suite="environment",
        device_class=SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS_PARTS,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda s: s.get("voc"),
    ),
    BirdWeatherSensorDescription(
        # BSEC IAQ index (0–500), not US-EPA AQI — HA's aqi device class is a
        # generic air-quality index, so it fits.
        key="aqi",
        translation_key="env_aqi",
        suite="environment",
        device_class=SensorDeviceClass.AQI,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda s: s.get("aqi"),
    ),
    BirdWeatherSensorDescription(
        key="light_level",
        translation_key="env_light",
        suite="light",
        icon="mdi:white-balance-sunny",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.get("clear"),
    ),
    BirdWeatherSensorDescription(
        key="battery_voltage",
        translation_key="sys_battery_voltage",
        suite="system",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("batteryVoltage"),
    ),
    BirdWeatherSensorDescription(
        key="power_source",
        translation_key="sys_power_source",
        suite="system",
        icon="mdi:power-plug",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("powerSource"),
    ),
    BirdWeatherSensorDescription(
        key="wifi_rssi",
        translation_key="sys_wifi_rssi",
        suite="system",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("wifiRssi"),
    ),
    BirdWeatherSensorDescription(
        key="sd_free",
        translation_key="sys_sd_free",
        suite="system",
        icon="mdi:micro-sd",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_sd_free_pct,
        attrs_fn=_sd_attrs,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BirdWeatherConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    station_id = entry.data[CONF_STATION_ID]

    entities: list[SensorEntity] = [
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

    # PUC hardware sensors: create only the sub-suites the station actually
    # reports (a BirdNET-Pi reports none). Gated on the first refresh's data, so
    # a station that only gains a PUC later picks the entities up on reload.
    suites = coordinator.data.get("sensors") or {}
    entities.extend(
        BirdWeatherHardwareSensor(coordinator, station_id, desc)
        for desc in HARDWARE_SENSORS
        if suites.get(desc.suite)
    )

    async_add_entities(entities)


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


class BirdWeatherHardwareSensor(_BirdWeatherSensor):
    """A PUC onboard hardware reading (environment / light / system), driven by
    a BirdWeatherSensorDescription. Reports None when its sub-suite is absent
    from a poll (stale hardware) rather than going unavailable, and exposes the
    reading's own timestamp as `last_reading` (sensor time is independent of
    detection time)."""

    entity_description: BirdWeatherSensorDescription

    def __init__(
        self,
        coordinator: BirdWeatherCoordinator,
        station_id: str,
        description: BirdWeatherSensorDescription,
    ) -> None:
        super().__init__(coordinator, station_id)
        self.entity_description = description
        self._attr_unique_id = f"{station_id}_{description.key}"

    def _suite(self) -> dict | None:
        return (self.coordinator.data.get("sensors") or {}).get(
            self.entity_description.suite
        )

    @property
    def native_value(self) -> Any:
        suite = self._suite()
        return self.entity_description.value_fn(suite) if suite else None

    @property
    def extra_state_attributes(self) -> dict:
        suite = self._suite() or {}
        attrs: dict = {}
        if ts := suite.get("timestamp"):
            attrs["last_reading"] = ts
        if self.entity_description.attrs_fn:
            attrs.update(self.entity_description.attrs_fn(suite))
        return attrs
