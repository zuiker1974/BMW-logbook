"""Selainkäyttöliittymä (FastAPI + Jinja2), näkyy HA:n sivupalkissa Ingressin kautta.

Kaikki näkymät ovat auton polun alla (/v/<auto>/...). "Kaikki autot" -näkymää ei ole.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import timeutil
from .csv_report import build_csv
from .database import EDITABLE_FIELDS, TRIP_TYPE_LABELS, LogbookError
from .integrity import purpose_issues, summarize
from .pdf_report import build_month_pdf, build_year_pdf
from .report_data import APP_VERSION, MONTH_NAMES, ReportFilter, fmt_km, trip_row
from .service import LockBlocked, VehicleService
from .xlsx_report import ImportRejected, build_xlsx

HERE = Path(__file__).parent
INGRESS_IP = "172.30.32.2"

FIELD_LABELS = {
    "start_time": "Alkuaika",
    "end_time": "Loppuaika",
    "start_address": "Lähtöpaikka",
    "end_address": "Määränpää",
    "start_odometer": "Mittari alussa",
    "end_odometer": "Mittari lopussa",
    "start_lat": "Lähtö lat",
    "start_lon": "Lähtö lon",
    "end_lat": "Määränpää lat",
    "end_lon": "Määränpää lon",
    "trip_type": "Ajotyyppi",
    "purpose": "Tarkoitus",
    "comment": "Kommentti",
    "trip": "Ajo lisätty",
    "merged_into_id": "Yhdistetty matkaan",
    "merge": "Yhdistetty matkoista",
    "unmerge": "Yhdistäminen purettu",
    "gap_ack": "Mittariaukko kuitattu",
    "period_lock": "Jakson lukitus",
}
SOURCE_LABELS = {
    "ui": "selain",
    "excel_drive": "Excel (Drive)",
    "excel_upload": "Excel (selain)",
    "merge": "yhdistäminen",
    "unmerge": "purku",
    "manual_add": "käsin lisäys",
    "gap_fill": "aukon täyttö",
    "period": "jakso",
    "vehicle_info": "asetussivu",
}


def create_app(app_state, restrict: bool | None = None) -> FastAPI:
    api = FastAPI(title="BMW-ajopäiväkirja", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    env = templates.env
    env.filters["date"] = timeutil.fmt_date
    env.filters["time"] = timeutil.fmt_time
    env.filters["dt"] = timeutil.fmt_datetime
    env.filters["km"] = fmt_km
    env.globals.update(
        TYPE_LABELS=TRIP_TYPE_LABELS,
        MONTH_NAMES=MONTH_NAMES,
        FIELD_LABELS=FIELD_LABELS,
        SOURCE_LABELS=SOURCE_LABELS,
        APP_VERSION=APP_VERSION,
    )
    api.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    if restrict is None:
        restrict = bool(os.environ.get("SUPERVISOR_TOKEN"))

    @api.middleware("http")
    async def ingress_only(request: Request, call_next):
        if restrict:
            host = request.client.host if request.client else ""
            if host not in (INGRESS_IP, "127.0.0.1"):
                return Response("Käytä ajopäiväkirjaa Home Assistantin kautta.", status_code=403)
        return await call_next(request)

    # ------------------------------------------------------------------ apu
    def base(request: Request) -> str:
        return request.headers.get("X-Ingress-Path", "").rstrip("/")

    def svc_or_404(vid: str) -> VehicleService:
        svc = app_state.services.get(vid)
        if svc is None:
            raise HTTPException(404, f"Autoa '{vid}' ei ole käytössä.")
        return svc

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        ctx.setdefault("msg", request.query_params.get("msg"))
        ctx.setdefault("err", request.query_params.get("err"))
        ctx["base"] = base(request)
        ctx["app"] = app_state
        ctx["vehicles"] = app_state.all_vehicles()
        return templates.TemplateResponse(request, name, ctx)

    def redirect(request: Request, path: str, msg: str | None = None, err: str | None = None, **params) -> RedirectResponse:
        q = {k: v for k, v in params.items() if v not in (None, "")}
        if msg:
            q["msg"] = msg
        if err:
            q["err"] = err
        url = base(request) + path + (("?" + urlencode(q)) if q else "")
        return RedirectResponse(url, status_code=303)

    def attachment(data: bytes, filename: str, media: str) -> Response:
        return Response(
            data,
            media_type=media,
            headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
        )

    def default_period() -> tuple[int, int]:
        now = timeutil.now_utc().astimezone(timeutil.local_tz())
        return now.year, now.month

    # ------------------------------------------------------------ etusivu
    @api.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        cards = []
        for v in app_state.all_vehicles():
            svc = app_state.services.get(v.id)
            last = svc.db.last_trip() if svc else None
            cards.append(
                {
                    "v": v,
                    "svc": svc,
                    "status": app_state.vehicle_status(v.id) if svc else ("Ei käytössä" if not v.enabled else "Ei konfiguroitu"),
                    "errors": app_state.vehicle_errors.get(v.id, []),
                    "last": last,
                }
            )
        return render(request, "index.html", cards=cards)

    # -------------------------------------------------------- matkalista
    @api.get("/v/{vid}", response_class=HTMLResponse)
    async def trip_list(request: Request, vid: str, year: int | None = None, month: int | None = None, type: str = ""):
        svc = svc_or_404(vid)
        dy, dm = default_period()
        year = year or dy
        month = dm if month is None and year == dy else (month if month is not None else 0)
        if month:
            start, end = timeutil.month_bounds(year, month)
        else:
            start, end = timeutil.year_bounds(year)
        types = [type] if type in TRIP_TYPE_LABELS else None
        trips = svc.db.list_trips(start, end, trip_types=types)
        all_in_period = svc.db.list_trips(start, end)
        rows = [trip_row(svc.db, t) for t in trips]
        locked = {}
        for t in trips:
            ym = timeutil.local_year_month(t["start_time"])
            if ym not in locked:
                locked[ym] = svc.db.is_locked(*ym)
        for r, t in zip(rows, trips):
            r["locked"] = locked[timeutil.local_year_month(t["start_time"])]
            r["is_parent"] = bool(t["is_merged_parent"])
        issues = svc.issues(start, end)
        gaps_by_next = {i.next_trip_id: i for i in issues if i.kind in ("gap", "overlap")}
        other_issues = [i for i in issues if i.kind not in ("gap", "overlap")] + purpose_issues(all_in_period)
        years = sorted({timeutil.local_year_month(t["start_time"])[0] for t in svc.db.list_trips()} | {dy})
        return render(
            request,
            "trips.html",
            svc=svc,
            v=svc.vehicle,
            rows=rows,
            year=year,
            month=month,
            type=type,
            years=years,
            summary=summarize(all_in_period),
            gaps_by_next=gaps_by_next,
            other_issues=other_issues,
            status=app_state.vehicle_status(vid),
            stream_ok=app_state.stream_ok,
        )

    @api.post("/v/{vid}/trips/{tid}/field")
    async def update_field(request: Request, vid: str, tid: int):
        svc = svc_or_404(vid)
        if request.headers.get("content-type", "").startswith("application/json"):
            body = await request.json()
        else:
            body = dict(await request.form())
        field = str(body.get("field", ""))
        if field not in ("trip_type", "purpose", "comment"):
            return JSONResponse({"ok": False, "error": "Tätä kenttää ei voi muokata pikamuokkauksella."}, status_code=400)
        try:
            trip = svc.db.update_field(tid, field, body.get("value"), source="ui")
        except LogbookError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        svc.mark_dirty_trip(tid)
        return {"ok": True, "trip": {k: trip[k] for k in ("id", "trip_type", "purpose", "comment")}}

    @api.post("/v/{vid}/trips/merge")
    async def merge(request: Request, vid: str):
        svc = svc_or_404(vid)
        form = await request.form()
        ids = [int(x) for x in form.getlist("ids") if str(x).isdigit()]
        back = dict(year=form.get("year"), month=form.get("month"))
        try:
            new_id = svc.db.merge(ids)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}", err=str(exc), **back)
        svc.mark_dirty_trip(new_id)
        return redirect(request, f"/v/{vid}", msg=f"{len(ids)} matkaa yhdistetty.", **back)

    @api.post("/v/{vid}/trips/{tid}/unmerge")
    async def unmerge(request: Request, vid: str, tid: int):
        svc = svc_or_404(vid)
        trip = svc.db.get_trip(tid)
        try:
            kids = svc.db.unmerge(tid)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}", err=str(exc))
        if trip:
            svc.mark_dirty_time(trip["start_time"])
        y, m = timeutil.local_year_month(trip["start_time"]) if trip else default_period()
        return redirect(request, f"/v/{vid}", msg=f"Yhdistäminen purettu ({len(kids)} matkaa).", year=y, month=m)

    @api.get("/v/{vid}/trips/{tid}", response_class=HTMLResponse)
    async def trip_detail(request: Request, vid: str, tid: int):
        svc = svc_or_404(vid)
        trip = svc.db.get_trip(tid)
        if trip is None:
            raise HTTPException(404, "Matkaa ei löydy tämän auton ajopäiväkirjasta.")
        return render(
            request,
            "trip.html",
            svc=svc,
            v=svc.vehicle,
            trip=trip,
            row=trip_row(svc.db, trip),
            history=svc.db.history(tid),
            children=svc.db.children(tid),
            stops=svc.db.charging_stops(tid),
            locked=svc.db.trip_is_locked(trip),
            year_month=timeutil.local_year_month(trip["start_time"]),
        )

    @api.post("/v/{vid}/trips/{tid}/correct")
    async def correct(request: Request, vid: str, tid: int, field: str = Form(...), value: str = Form(""), reason: str = Form("")):
        svc = svc_or_404(vid)
        if field not in EDITABLE_FIELDS:
            return redirect(request, f"/v/{vid}/trips/{tid}", err="Tuntematon kenttä.")
        if field in ("start_time", "end_time") and value:
            value = timeutil.local_naive_to_iso(value)
        try:
            svc.db.update_field(tid, field, value, source="ui", reason=reason)
        except (LogbookError, ValueError) as exc:
            return redirect(request, f"/v/{vid}/trips/{tid}", err=str(exc))
        svc.mark_dirty_trip(tid)
        return redirect(request, f"/v/{vid}/trips/{tid}", msg="Korjaus tallennettu ja kirjattu muutoslokiin.")

    # ------------------------------------------------------ käsin lisäys
    @api.get("/v/{vid}/new", response_class=HTMLResponse)
    async def new_trip_form(request: Request, vid: str, prev: int | None = None, next: int | None = None):
        svc = svc_or_404(vid)
        prefill = {}
        if prev and next:
            p, n = svc.db.get_trip(prev), svc.db.get_trip(next)
            if p and n:
                prefill = {
                    "start_time": timeutil.to_local(p["end_time"]).strftime("%Y-%m-%dT%H:%M"),
                    "end_time": timeutil.to_local(n["start_time"]).strftime("%Y-%m-%dT%H:%M"),
                    "start_address": p["end_address"],
                    "end_address": n["start_address"],
                    "start_odometer": p["end_odometer"],
                    "end_odometer": n["start_odometer"],
                }
        return render(request, "new_trip.html", svc=svc, v=svc.vehicle, prefill=prefill, prev=prev, next=next)

    @api.post("/v/{vid}/new")
    async def new_trip(
        request: Request,
        vid: str,
        start_time: str = Form(...),
        end_time: str = Form(...),
        start_address: str = Form(""),
        end_address: str = Form(""),
        start_odometer: str = Form(""),
        end_odometer: str = Form(""),
        trip_type: str = Form("private"),
        purpose: str = Form(""),
        comment: str = Form(""),
        reason: str = Form(""),
        prev: str = Form(""),
        next: str = Form(""),
    ):
        svc = svc_or_404(vid)
        try:
            so = float(start_odometer.replace(",", ".")) if start_odometer else None
            eo = float(end_odometer.replace(",", ".")) if end_odometer else None
            if so is None or eo is None:
                raise LogbookError("Anna mittarilukemat ajon alussa ja lopussa.")
            if eo < so:
                raise LogbookError("Loppulukema ei voi olla pienempi kuin alkulukema.")
            trip = {
                "start_time": timeutil.local_naive_to_iso(start_time),
                "end_time": timeutil.local_naive_to_iso(end_time),
                "start_address": start_address,
                "end_address": end_address,
                "start_odometer": so,
                "end_odometer": eo,
                "trip_type": trip_type,
                "purpose": purpose,
                "comment": comment,
            }
            if trip["end_time"] < trip["start_time"]:
                raise LogbookError("Loppuaika on ennen alkuaikaa.")
            if prev and next:
                tid = svc.db.insert_trip(trip, source="gap_fill", reason=reason or "Mittariaukosta luotu ajo")
                svc.mark_dirty_time(trip["start_time"])
            else:
                tid = svc.add_manual_trip(trip, reason=reason)
        except (LogbookError, ValueError) as exc:
            return redirect(request, f"/v/{vid}/new", err=str(exc), prev=prev, next=next)
        y, m = timeutil.local_year_month(trip["start_time"])
        return redirect(request, f"/v/{vid}", msg=f"Ajo lisätty (matka {tid}).", year=y, month=m)

    @api.post("/v/{vid}/gaps/ack")
    async def ack_gap(request: Request, vid: str, prev: int = Form(...), next: int = Form(...), reason: str = Form("")):
        svc = svc_or_404(vid)
        try:
            svc.db.ack_gap(prev, next, reason)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}", err=str(exc))
        svc.mark_dirty_trip(next)
        trip = svc.db.get_trip(next)
        y, m = timeutil.local_year_month(trip["start_time"])
        return redirect(request, f"/v/{vid}", msg="Aukko kuitattu ja kirjattu muutoslokiin.", year=y, month=m)

    # ------------------------------------------------------------ raportit
    @api.get("/v/{vid}/reports", response_class=HTMLResponse)
    async def reports(request: Request, vid: str, year: int | None = None):
        svc = svc_or_404(vid)
        dy, dm = default_period()
        year = year or dy
        months = []
        for m in range(1, 13):
            p = svc.db.period(year, m)
            ms, me = timeutil.month_bounds(year, m)
            trips = svc.db.list_trips(ms, me)
            months.append(
                {
                    "month": m,
                    "name": MONTH_NAMES[m],
                    "period": p,
                    "count": len(trips),
                    "km": summarize(trips)["total_km"],
                    "ended": timeutil.parse_iso(me) <= timeutil.now_utc(),
                    "issues": [i for i in svc.issues(ms, me) if i.blocking] + purpose_issues(trips),
                }
            )
        years = sorted({timeutil.local_year_month(t["start_time"])[0] for t in svc.db.list_trips()} | {dy})
        return render(
            request,
            "reports.html",
            svc=svc,
            v=svc.vehicle,
            year=year,
            default_month=dm if year == dy else 12,
            years=years,
            months=months,
            imports=svc.db.imports(10),
            conflicts=svc.db.open_conflicts(),
            commute_default=svc.settings.commute_counts_as_private,
        )

    @api.get("/v/{vid}/download")
    async def download(
        request: Request,
        vid: str,
        kind: str,
        year: int,
        month: int = 0,
        filter: str = "all",
        include_commute: str | None = None,
    ):
        svc = svc_or_404(vid)
        inc = None if include_commute is None else include_commute in ("1", "on", "true")
        flt = ReportFilter.parse(filter, inc, svc.settings)
        ctx = svc.ctx
        if kind == "month_pdf":
            if not 1 <= month <= 12:
                raise HTTPException(400, "Valitse kuukausi.")
            archived = svc.period_file(year, month) if not flt.is_partial else None
            if archived is not None:
                return FileResponse(archived, media_type="application/pdf", filename=archived.name)
            data = build_month_pdf(ctx, year, month, flt)
            return attachment(data, ctx.month_pdf_name(year, month, flt), "application/pdf")
        if kind == "year_pdf":
            return attachment(build_year_pdf(ctx, year, flt), ctx.year_pdf_name(year, flt), "application/pdf")
        if kind == "xlsx":
            return attachment(
                build_xlsx(ctx, year, flt),
                ctx.xlsx_name(year, flt),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if kind == "csv":
            return attachment(build_csv(ctx, year, flt), ctx.csv_name(year, flt), "text/csv; charset=utf-8")
        raise HTTPException(400, "Tuntematon raporttityyppi.")

    @api.post("/v/{vid}/import")
    async def upload(request: Request, vid: str, file: UploadFile = File(...)):
        svc = svc_or_404(vid)
        data = await file.read()
        try:
            res = svc.import_bytes(data, file.filename or "tuonti.xlsx", source="excel_upload")
        except ImportRejected as exc:
            return redirect(request, f"/v/{vid}/reports", err=f"Tuonti hylätty: {exc}")
        return redirect(request, f"/v/{vid}/reports", msg=f"Tuonti valmis: {res.status_text()}.")

    @api.post("/v/{vid}/conflicts/{cid}")
    async def resolve(request: Request, vid: str, cid: int, choice: str = Form(...)):
        svc = svc_or_404(vid)
        try:
            svc.db.resolve_conflict(cid, choice)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}/reports", err=str(exc))
        return redirect(request, f"/v/{vid}/reports", msg="Ristiriita ratkaistu.")

    @api.post("/v/{vid}/periods/lock")
    async def lock(request: Request, vid: str, year: int = Form(...), month: int = Form(...)):
        svc = svc_or_404(vid)
        try:
            p = svc.lock_period(year, month)
        except LockBlocked as exc:
            return redirect(request, f"/v/{vid}/reports", err=str(exc), year=year)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}/reports", err=str(exc), year=year)
        return redirect(
            request,
            f"/v/{vid}/reports",
            msg=f"{MONTH_NAMES[month]} {year} lukittu. SHA-256: {p['report_sha256']}",
            year=year,
        )

    @api.post("/v/{vid}/periods/unlock")
    async def unlock(request: Request, vid: str, year: int = Form(...), month: int = Form(...), reason: str = Form("")):
        svc = svc_or_404(vid)
        try:
            svc.unlock_period(year, month, reason)
        except LogbookError as exc:
            return redirect(request, f"/v/{vid}/reports", err=str(exc), year=year)
        return redirect(request, f"/v/{vid}/reports", msg="Lukitus avattu ja kirjattu muutoslokiin.", year=year)

    # ------------------------------------------------------------ asetukset
    @api.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        cars = []
        for v in app_state.all_vehicles():
            svc = app_state.services.get(v.id)
            cars.append(
                {
                    "v": v,
                    "svc": svc,
                    "errors": app_state.vehicle_errors.get(v.id, []),
                    "entities": svc.entity_status if svc else {},
                    "files": svc.exporter.recent_files() if svc else [],
                    "pending": [p.name for p in svc.exporter.pending_imports(0)] if svc else [],
                    "imports": svc.db.imports(5) if svc else [],
                    "snapshot": svc.trip_manager.snapshot() if svc and svc.trip_manager else {},
                    "info_history": svc.db.vehicle_info_history() if svc else [],
                }
            )
        return render(request, "settings.html", cars=cars, settings=app_state.settings)

    @api.get("/health")
    async def health():
        return {"ok": True, "ha_connected": app_state.ha_connected, "version": APP_VERSION, "time": datetime.now().isoformat()}

    return api
