"""Asetusten luku add-onin asetussivulta (/data/options.json) ja autojen tarkistus."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

_LOG = logging.getLogger(__name__)

ROLES = (
    "location",
    "odometer",
    "motion",
    "soc",
    "charging_state",
    "charging_method",
    "hv_system_state",
    "fuel_level",
    "charger_energy",
)
# Kululaskennan roolit: näitä ei syötetä ajotunnistukselle
CONSUMPTION_ROLES = ("fuel_level", "charger_energy")
REQUIRED_ROLES = ("location", "odometer")

VEHICLE_ID_RE = re.compile(r"^[a-z0-9_]{2,16}$")
VIN_RE = re.compile(r"^$|^[A-HJ-NPR-Z0-9]{17}$")

DEFAULT_PAUSE_TIMEOUT = {"PHEV": 2700, "BEV": 5400}
# Arviokerroin (kWh seinästä / varaus-%) muualla kuin kotilaturilla ladattaessa
DEFAULT_KWH_PER_PCT = {"PHEV": 0.12, "BEV": 0.0}


@dataclass
class VehicleConfig:
    id: str
    plate: str = ""
    make: str = "BMW"
    model: str = ""
    powertrain: str = "PHEV"
    vin: str = ""
    driver: str = ""
    enabled: bool = True
    charging_pause_enabled: bool = True
    charging_pause_timeout_s: int = 2700
    charge_kwh_per_pct: float = 0.0
    entities: dict[str, str] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return f"{self.make} {self.model}".strip()

    @property
    def folder_name(self) -> str:
        """Auton kansio raporttikansiossa: <id>_<rekisteritunnus>."""
        plate = safe_name(self.plate)
        return f"{self.id}_{plate}" if plate else self.id

    @property
    def file_prefix(self) -> str:
        plate = safe_name(self.plate)
        return f"Ajopaivakirja_{self.id}_{plate}" if plate else f"Ajopaivakirja_{self.id}"

    def entity(self, role: str) -> str:
        return self.entities.get(role, "") or ""

    @property
    def has_fuel(self) -> bool:
        return self.powertrain == "PHEV"

    def entity_ids(self) -> list[str]:
        return [e for e in self.entities.values() if e]


@dataclass
class Settings:
    vehicles: list[VehicleConfig] = field(default_factory=list)
    vehicle_errors: dict[str, list[str]] = field(default_factory=dict)
    export_dir: str = "/share/ajopaivakirja"
    data_dir: str = "/data"
    month_folder_format: str = "%m"
    trip_start_distance_m: int = 100
    trip_end_timeout_s: int = 600
    ghost_motion_max_s: int = 90
    home_zones: list[str] = field(default_factory=lambda: ["zone.home"])
    stream_status_entity: str = "sensor.cardata_debug_device_stream_connection_status"
    backfill_max_hours: int = 24
    ha_mqtt_enabled: bool = True
    report_xlsx: bool = True
    report_csv: bool = False
    xlsx_import_poll_s: int = 60
    odometer_gap_tolerance_km: float = 1.0
    auto_lock_after_days: int = 15
    commute_counts_as_private: bool = True
    archive_filtered: list[str] = field(default_factory=lambda: ["business"])
    nominatim_user_agent: str = "bmw-logbook-fi/0.1"
    refuel_min_l: float = 3.0
    log_level: str = "info"

    def vehicle(self, vehicle_id: str) -> VehicleConfig | None:
        for v in self.vehicles:
            if v.id == vehicle_id:
                return v
        return None

    def active_vehicles(self) -> list[VehicleConfig]:
        return [v for v in self.vehicles if v.enabled and v.id not in self.vehicle_errors]


def safe_name(value: str) -> str:
    """Tiedostonimeen kelpaava muoto (rekisteritunnus ABC-123 säilyy ennallaan)."""
    return re.sub(r"[^A-Za-z0-9ÅÄÖåäö_-]", "", (value or "").strip().upper())


def _vehicle_from_dict(raw: dict) -> VehicleConfig:
    powertrain = str(raw.get("powertrain") or "PHEV").upper()
    entities = {role: str(raw.get(f"entity_{role}") or "").strip() for role in ROLES}
    timeout = raw.get("charging_pause_timeout_s")
    kwh_pct = raw.get("charge_kwh_per_pct")
    return VehicleConfig(
        id=str(raw.get("id", "")).strip(),
        plate=str(raw.get("plate") or "").strip().upper(),
        make=str(raw.get("make") or "BMW").strip(),
        model=str(raw.get("model") or "").strip(),
        powertrain=powertrain,
        vin=str(raw.get("vin") or "").strip().upper(),
        driver=str(raw.get("driver") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
        charging_pause_enabled=bool(raw.get("charging_pause_enabled", True)),
        charging_pause_timeout_s=int(timeout if timeout is not None else DEFAULT_PAUSE_TIMEOUT.get(powertrain, 2700)),
        charge_kwh_per_pct=float(kwh_pct if kwh_pct is not None else DEFAULT_KWH_PER_PCT.get(powertrain, 0.0)),
        entities=entities,
    )


def parse_settings(options: dict, data_dir: str = "/data") -> Settings:
    s = Settings(data_dir=data_dir)
    for key in (
        "export_dir",
        "month_folder_format",
        "trip_start_distance_m",
        "trip_end_timeout_s",
        "ghost_motion_max_s",
        "home_zones",
        "stream_status_entity",
        "backfill_max_hours",
        "ha_mqtt_enabled",
        "report_xlsx",
        "report_csv",
        "xlsx_import_poll_s",
        "odometer_gap_tolerance_km",
        "auto_lock_after_days",
        "commute_counts_as_private",
        "archive_filtered",
        "nominatim_user_agent",
        "refuel_min_l",
        "log_level",
    ):
        if key in options and options[key] is not None:
            setattr(s, key, options[key])
    s.odometer_gap_tolerance_km = float(s.odometer_gap_tolerance_km)
    s.refuel_min_l = float(s.refuel_min_l)

    seen: set[str] = set()
    for raw in options.get("vehicles") or []:
        v = _vehicle_from_dict(raw)
        errors: list[str] = []
        if not VEHICLE_ID_RE.match(v.id):
            errors.append(f"Virheellinen auton tunniste '{v.id}' (sallittu a-z, 0-9, _; 2-16 merkkiä).")
        if v.id in seen:
            errors.append(f"Auton tunniste '{v.id}' on käytössä useammin kuin kerran.")
        if not VIN_RE.match(v.vin):
            errors.append("VIN on virheellinen (17 merkkiä, ei I, O tai Q).")
        if v.powertrain not in ("PHEV", "BEV"):
            errors.append("Voimalinjan on oltava PHEV tai BEV.")
        if v.entity("fuel_level") and not v.has_fuel:
            errors.append("Polttoaine-entiteetti on asetettu sähköautolle (BEV).")
        if v.enabled:
            for role in REQUIRED_ROLES:
                if not v.entity(role):
                    errors.append(f"Pakollinen entiteetti '{role}' puuttuu.")
        key = v.id if v.id not in seen else f"{v.id}#{len(s.vehicles)}"
        seen.add(v.id)
        if errors:
            s.vehicle_errors[key] = errors
            for e in errors:
                _LOG.error("Auto %s: %s", v.id, e)
        if v.id and key == v.id:
            s.vehicles.append(v)
    return s


def load_settings(path: str | None = None) -> Settings:
    data_dir = os.environ.get("LOGBOOK_DATA_DIR", "/data")
    path = path or os.path.join(data_dir, "options.json")
    p = Path(path)
    options = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if not p.exists():
        _LOG.warning("Asetustiedostoa %s ei löydy, käytetään oletuksia", path)
    return parse_settings(options, data_dir=data_dir)
