"""Raporttien yhteinen aineisto: rivit, suodattimet ja tiedostonimet (aina yksi auto)."""
from __future__ import annotations

from dataclasses import dataclass

from . import timeutil
from .database import CORRECTION_FIELDS, TRIP_TYPE_LABELS, VehicleDB
from .integrity import odometer_issues, odometer_reconciliation, summarize
from .vehicle_registry import Settings, VehicleConfig

APP_VERSION = "0.1.0"

MONTH_NAMES = [
    "",
    "Tammikuu",
    "Helmikuu",
    "Maaliskuu",
    "Huhtikuu",
    "Toukokuu",
    "Kesäkuu",
    "Heinäkuu",
    "Elokuu",
    "Syyskuu",
    "Lokakuu",
    "Marraskuu",
    "Joulukuu",
]

# suodatin -> (ajotyypit, tiedostonimen pääte, otsikko)
FILTERS = {
    "all": (("business", "private", "commute"), "", ""),
    "business": (("business",), "_tyoajot", "Osaraportti: vain työajot"),
    "private": (("private",), "_yksityisajot", "Osaraportti: vain yksityisajot"),
    "commute": (("commute",), "_tyomatkat", "Osaraportti: vain työmatkat"),
}


@dataclass
class ReportFilter:
    key: str = "all"
    include_commute: bool = True  # koskee vain "private"-suodatinta

    @property
    def types(self) -> tuple[str, ...]:
        types = FILTERS[self.key][0]
        if self.key == "private" and self.include_commute:
            types = ("private", "commute")
        return types

    @property
    def suffix(self) -> str:
        return FILTERS[self.key][1]

    @property
    def title(self) -> str:
        t = FILTERS[self.key][2]
        if self.key == "private" and self.include_commute:
            t += " (sisältää työmatkat)"
        return t

    @property
    def is_partial(self) -> bool:
        return self.key != "all"

    @classmethod
    def parse(cls, key: str | None, include_commute: bool | None, settings: Settings) -> "ReportFilter":
        key = key if key in FILTERS else "all"
        inc = settings.commute_counts_as_private if include_commute is None else include_commute
        return cls(key, inc)


@dataclass
class ReportContext:
    db: VehicleDB
    vehicle: VehicleConfig
    settings: Settings

    @property
    def vehicle_id(self) -> str:
        return self.vehicle.id

    def info_for(self, when_iso: str | None) -> dict:
        info = self.db.vehicle_info_at(when_iso)
        return info or {
            "plate": self.vehicle.plate,
            "vin": self.vehicle.vin,
            "make": self.vehicle.make,
            "model": self.vehicle.model,
            "powertrain": self.vehicle.powertrain,
            "driver": self.vehicle.driver,
        }

    # ------------------------------------------------------------ tiedostonimet
    def file_prefix(self, plate: str | None = None) -> str:
        from .vehicle_registry import safe_name

        plate = safe_name(plate if plate is not None else self.vehicle.plate)
        return f"Ajopaivakirja_{self.vehicle.id}_{plate}" if plate else f"Ajopaivakirja_{self.vehicle.id}"

    def month_pdf_name(self, year: int, month: int, flt: ReportFilter | None = None) -> str:
        return f"{self.file_prefix()}_{year}_{month:02d}{flt.suffix if flt else ''}.pdf"

    def year_pdf_name(self, year: int, flt: ReportFilter | None = None) -> str:
        return f"{self.file_prefix()}_{year}_vuosiraportti{flt.suffix if flt else ''}.pdf"

    def xlsx_name(self, year: int, flt: ReportFilter | None = None) -> str:
        return f"{self.file_prefix()}_{year}{flt.suffix if flt else ''}.xlsx"

    def csv_name(self, year: int, flt: ReportFilter | None = None) -> str:
        return f"{self.file_prefix()}_{year}{flt.suffix if flt else ''}.csv"

    # ----------------------------------------------------------------- data
    def trips(self, start_iso: str, end_iso: str, flt: ReportFilter | None = None) -> list[dict]:
        types = flt.types if flt else None
        return self.db.list_trips(start_iso, end_iso, trip_types=types)

    def rows(self, trips: list[dict]) -> list[dict]:
        locked_at_cache: dict[tuple[int, int], str | None] = {}
        out = []
        for t in trips:
            y, m = timeutil.local_year_month(t["start_time"])
            if (y, m) not in locked_at_cache:
                p = self.db.period(y, m)
                locked_at_cache[(y, m)] = p.get("locked_at") if p.get("status") == "locked" else None
            out.append(trip_row(self.db, t, locked_at_cache[(y, m)]))
        return out

    def month_summary(self, year: int, month: int) -> dict:
        start, end = timeutil.month_bounds(year, month)
        trips = self.db.list_trips(start, end)
        s = summarize(trips)
        s.update(odometer_reconciliation(trips))
        s["issues"] = odometer_issues(self.db, self.settings.odometer_gap_tolerance_km, start, end)
        boundary = self.db.get_state(f"odometer_boundary:{year}-{month:02d}")
        s["ha_odometer_at_start"] = float(boundary) if boundary else None
        return s

    def year_summary(self, year: int) -> dict:
        start, end = timeutil.year_bounds(year)
        trips = self.db.list_trips(start, end)
        s = summarize(trips)
        s.update(odometer_reconciliation(trips))
        s["issues"] = odometer_issues(self.db, self.settings.odometer_gap_tolerance_km, start, end)
        s["months"] = []
        for m in range(1, 13):
            ms, me = timeutil.month_bounds(year, m)
            mt = [t for t in trips if ms <= t["start_time"] < me]
            sm = summarize(mt)
            sm["month"] = m
            sm["name"] = MONTH_NAMES[m]
            sm["locked"] = self.db.is_locked(year, m)
            s["months"].append(sm)
        return s

    def drivers(self, trips: list[dict]) -> list[str]:
        names = []
        for t in trips:
            d = self.info_for(t["start_time"]).get("driver") or ""
            if d and d not in names:
                names.append(d)
        return names


def charging_note(db: VehicleDB, trip: dict) -> str:
    notes = []
    for s in db.charging_stops(trip["id"]):
        mins = timeutil.minutes_between(s["start_time"], s["end_time"]) if s["start_time"] and s["end_time"] else None
        place = s["address"] or (f"{s['lat']:.4f}, {s['lon']:.4f}" if s["lat"] is not None else "")
        method = f" ({s['method']})" if s.get("method") else ""
        notes.append(f"Lataustauko {mins} min{method}, {place}".strip(", ") if mins is not None else f"Lataustauko{method}, {place}")
    return "; ".join(notes)


def place(addr: str | None, lat: float | None, lon: float | None) -> str:
    if addr:
        return addr
    if lat is not None and lon is not None:
        return f"{lat:.5f}, {lon:.5f}"
    return ""


def trip_row(db: VehicleDB, t: dict, locked_at: str | None = None) -> dict:
    markers = []
    if t["source"] in ("manual", "gap_fill"):
        markers.append("käsin lisätty")
    if t["corrected"]:
        markers.append("korjattu")
    if t["is_merged_parent"]:
        markers.append("yhdistetty")
    post_lock = False
    if locked_at:
        for ch in db.history(t["id"]):
            if ch["field"] == "comment" and ch["changed_at"] > locked_at:
                post_lock = True
    corrected_fields = sorted(
        {ch["field"] for ch in db.history(t["id"]) if ch["field"] in CORRECTION_FIELDS}
    ) if t["corrected"] else []
    return {
        "id": t["id"],
        "date": timeutil.fmt_date(t["start_time"]),
        "start": timeutil.fmt_time(t["start_time"]),
        "end": timeutil.fmt_time(t["end_time"]),
        "end_date": timeutil.fmt_date(t["end_time"]),
        "from": place(t["start_address"], t["start_lat"], t["start_lon"]),
        "to": place(t["end_address"], t["end_lat"], t["end_lon"]),
        "odo_start": t["start_odometer"],
        "odo_end": t["end_odometer"],
        "km": t["distance_km"],
        "type": t["trip_type"],
        "type_label": TRIP_TYPE_LABELS[t["trip_type"]],
        "purpose": t["purpose"] or "",
        "charging": charging_note(db, t),
        "comment": t["comment"] or "",
        "comment_source": t.get("comment_source"),
        "comment_post_lock": post_lock,
        "markers": markers,
        "corrected_fields": corrected_fields,
        "source": t["source"],
        "start_time": t["start_time"],
        "end_time": t["end_time"],
    }


def fmt_km(v) -> str:
    if v is None:
        return ""
    v = float(v)
    return f"{v:,.0f}".replace(",", " ") if v.is_integer() else f"{v:,.1f}".replace(",", " ").replace(".", ",")
