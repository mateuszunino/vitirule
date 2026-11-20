#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
db.py
=====
Único ponto de acesso ao banco PostgreSQL/Supabase via `psycopg2` (sem ORM).

Regras seguidas (SKILL.md seção 6 e BRIEFING.md seção 8):
* Toda data/hora exige fuso e é gravada em UTC (`timestamptz`).
* Nenhuma instrução `DELETE` em tabelas de dados do ensaio.
* Cargas repetíveis com `INSERT ... ON CONFLICT`.
* Dados simulados são sempre marcados com `simulated = true` e isolados por
  padrão (`simulated = false`) nas consultas de dados reais.
* As tabelas climáticas vêm diretamente de `weather_collector.DDL`.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json, RealDictCursor, execute_values

import epidemiology_assimilation as ea
import weather_collector as wc

load_dotenv()

log = logging.getLogger("db")

UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
POT_ID_RE = re.compile(r"^V(0[1-9]|1\d|20)$")
LEAF_ID_RE = re.compile(r"^V(0[1-9]|1\d|20)-F[1-3]$")
VALID_DISEASES = frozenset(ea.PATHOGENS.keys())

APP_DDL = """
create table if not exists pots (
    pot_id    text primary key check (pot_id ~ '^V(0[1-9]|1[0-9]|20)$'),
    treatment text not null check (treatment in ('testemunha', 'dss'))
);

create table if not exists leaves (
    leaf_id text primary key check (leaf_id ~ '^V(0[1-9]|1[0-9]|20)-F[1-3]$'),
    pot_id  text not null references pots,
    disease text check (disease in ('pinta_preta', 'requeima')),
    notes   text
);

create table if not exists video_assessments (
    assessment_id   bigint generated always as identity primary key,
    leaf_id         text not null references leaves,
    captured_at     timestamptz not null,
    video_sha256    text not null unique,
    video_path      text not null,
    severity_pct    double precision check (severity_pct between 0 and 100),
    severity_sd_pct double precision,
    necrosis_pct    double precision,
    chlorosis_pct   double precision,
    leaf_area_cm2   double precision,
    lesion_area_mm2 double precision,
    quality_ok      boolean not null,
    accepted        boolean not null,
    flags           text[] not null default '{}',
    result          jsonb not null,
    simulated       boolean not null default false,
    created_at      timestamptz not null default now()
);
alter table video_assessments add column if not exists simulated boolean not null default false;
create index if not exists video_assessments_leaf_ts on video_assessments (leaf_id, captured_at);

create table if not exists epi_fits (
    fit_id             bigint generated always as identity primary key,
    pot_id             text not null references pots,
    disease            text not null check (disease in ('pinta_preta', 'requeima')),
    fitted_at          timestamptz not null,
    model              text not null check (model in ('logistic', 'gompertz')),
    n_obs              integer not null,
    r                  double precision not null,
    r_lo95             double precision,
    r_hi95             double precision,
    aacpd_observed     double precision,
    aacpd_total_median double precision,
    state              jsonb not null,
    result             jsonb not null,
    simulated          boolean not null default false
);
alter table epi_fits add column if not exists simulated boolean not null default false;
create index if not exists epi_fits_pot on epi_fits (pot_id, disease, fitted_at desc);

create table if not exists spray_events (
    spray_id   bigint generated always as identity primary key,
    pot_id     text not null references pots,
    applied_at timestamptz not null,
    product    text not null,
    dose       text,
    notes      text,
    simulated  boolean not null default false
);
alter table spray_events add column if not exists simulated boolean not null default false;
create index if not exists spray_events_pot_ts on spray_events (pot_id, applied_at desc);

create table if not exists dsv_daily (
    station_id  text not null,
    day         date not null,
    kind        text not null check (kind in ('observed', 'forecast')),
    tomcast_dsv smallint not null check (tomcast_dsv between 0 and 4),
    wallin_sv   smallint not null check (wallin_sv between 0 and 4),
    wet_hours   smallint not null,
    primary key (station_id, day, kind)
);

create table if not exists decisions (
    decision_id bigint generated always as identity primary key,
    pot_id      text not null references pots,
    disease     text not null,
    decided_at  timestamptz not null,
    action      text not null check (action in ('spray', 'monitor', 'none')),
    reasons     text[] not null,
    result      jsonb not null,
    simulated   boolean not null default false
);
alter table decisions add column if not exists simulated boolean not null default false;
create index if not exists decisions_pot_ts on decisions (pot_id, disease, decided_at desc);
"""


# --------------------------------------------------------------------------
# Validação de identificadores e timestamps
# --------------------------------------------------------------------------
def validate_pot_id(pot_id: str) -> str:
    if not isinstance(pot_id, str) or not POT_ID_RE.match(pot_id):
        raise ValueError(f"pot_id inválido: {pot_id!r}. Esperado V01 a V20.")
    return pot_id


def validate_leaf_id(leaf_id: str) -> str:
    if not isinstance(leaf_id, str) or not LEAF_ID_RE.match(leaf_id):
        raise ValueError(f"leaf_id inválido: {leaf_id!r}. Esperado V01-F1 a V20-F3.")
    return leaf_id


def validate_disease(disease: str) -> str:
    if disease not in VALID_DISEASES:
        raise ValueError(f"doença desconhecida: {disease!r}. Use {sorted(VALID_DISEASES)}.")
    return disease


def ensure_utc(value: Any, label: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"{label} inválido: {value!r}")
    if dt.tzinfo is None:
        raise ValueError(f"{label} sem fuso horário: {value!r}. Use ISO 8601 com offset.")
    return dt.astimezone(UTC)


# --------------------------------------------------------------------------
# Conexão e inicialização
# --------------------------------------------------------------------------
def get_connection(database_url: Optional[str] = None):
    """Abre conexão com PostgreSQL/Supabase usando `DATABASE_URL`."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não definida no ambiente ou .env")
    return psycopg2.connect(url, connect_timeout=10, application_name="tomato_dss")


def check_health(conn) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("select 1")
            row = cur.fetchone()
            return bool(row and row[0] == 1)
    except Exception:
        return False


def init_db(conn) -> None:
    """Cria tabelas climáticas (weather_collector.DDL), tabelas do DSS e unidades V01-V20."""
    with conn, conn.cursor() as cur:
        cur.execute(wc.DDL)
        cur.execute(APP_DDL)
    seed_trial_units(conn)


def seed_trial_units(conn) -> None:
    """Popula os 20 vasos (`V01`-`V20`) e as 60 folhas (`V01-F1`-`V20-F3`) de forma idempotente."""
    pots = [(f"V{i:02d}", "testemunha" if i <= 10 else "dss") for i in range(1, 21)]
    leaves = [(f"V{i:02d}-F{f}", f"V{i:02d}") for i in range(1, 21) for f in range(1, 4)]
    with conn, conn.cursor() as cur:
        execute_values(
            cur,
            "insert into pots (pot_id, treatment) values %s on conflict (pot_id) do nothing",
            pots,
        )
        execute_values(
            cur,
            "insert into leaves (leaf_id, pot_id) values %s on conflict (leaf_id) do nothing",
            leaves,
        )


# --------------------------------------------------------------------------
# Vasos e folhas
# --------------------------------------------------------------------------
def get_pot(conn, pot_id: str) -> Optional[dict]:
    validate_pot_id(pot_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("select pot_id, treatment from pots where pot_id = %s", (pot_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_leaf(conn, leaf_id: str) -> Optional[dict]:
    validate_leaf_id(leaf_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("select leaf_id, pot_id, disease, notes from leaves where leaf_id = %s", (leaf_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def set_leaf_disease(conn, leaf_id: str, disease: str, notes: Optional[str] = None) -> None:
    validate_leaf_id(leaf_id)
    validate_disease(disease)
    with conn, conn.cursor() as cur:
        cur.execute(
            "update leaves set disease = %s, notes = coalesce(%s, notes) where leaf_id = %s",
            (disease, notes, leaf_id),
        )


# --------------------------------------------------------------------------
# Avaliações de vídeo (`video_assessments`)
# --------------------------------------------------------------------------
def get_assessment_by_sha256(conn, video_sha256: str) -> Optional[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select assessment_id, leaf_id, captured_at, video_sha256, video_path,
                   severity_pct, severity_sd_pct, necrosis_pct, chlorosis_pct,
                   leaf_area_cm2, lesion_area_mm2, quality_ok, accepted, flags,
                   result, simulated, created_at
            from video_assessments
            where video_sha256 = %s
            """,
            (video_sha256,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def insert_video_assessment(
    conn,
    vision_result: dict,
    video_path: str,
    simulated: bool = False,
) -> tuple[int, bool]:
    """
    Grava avaliação em `video_assessments` com idempotência por `video_sha256`.
    Retorna `(assessment_id, created)` onde `created=False` indica que o SHA256
    já existia no banco.
    """
    leaf_id = validate_leaf_id(vision_result["leaf_id"])
    captured_utc = ensure_utc(vision_result["captured_at"], "captured_at")
    sha256 = vision_result["video"]["sha256"]
    quality = vision_result.get("quality") or {}
    quality_ok = bool(quality.get("ok", False))
    flags = list(quality.get("flags") or [])

    with conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into video_assessments (
                leaf_id, captured_at, video_sha256, video_path,
                severity_pct, severity_sd_pct, necrosis_pct, chlorosis_pct,
                leaf_area_cm2, lesion_area_mm2, quality_ok, accepted, flags,
                result, simulated
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (video_sha256) do nothing
            returning assessment_id
            """,
            (
                leaf_id,
                captured_utc,
                sha256,
                str(video_path),
                vision_result.get("severity_pct"),
                vision_result.get("severity_sd_pct"),
                vision_result.get("necrosis_pct"),
                vision_result.get("chlorosis_pct"),
                vision_result.get("leaf_area_cm2"),
                vision_result.get("lesion_area_mm2"),
                quality_ok,
                quality_ok,   # `accepted` começa igual a `quality_ok` (SKILL.md seção 6)
                flags,
                Json(vision_result),
                bool(simulated),
            ),
        )
        row = cur.fetchone()
        if row is not None:
            return int(row[0]), True
        cur.execute("select assessment_id from video_assessments where video_sha256 = %s", (sha256,))
        existing = cur.fetchone()
        return int(existing[0]), False


def get_accepted_assessments_for_pot(
    conn,
    pot_id: str,
    disease: Optional[str] = None,
    simulated: bool = False,
) -> list[dict]:
    """
    Retorna apenas avaliações com `accepted = true` (SKILL.md seção 10) de um vaso,
    no formato esperado por `epidemiology_assimilation.aggregate_leaves_to_pot`.
    """
    validate_pot_id(pot_id)
    if disease is not None:
        validate_disease(disease)
    sql = """
        select va.assessment_id, va.leaf_id, va.captured_at,
               va.severity_pct, va.severity_sd_pct
        from video_assessments va
        join leaves l on l.leaf_id = va.leaf_id
        where l.pot_id = %s
          and va.accepted = true
          and va.simulated = %s
          and va.severity_pct is not null
    """
    params: list[Any] = [pot_id, bool(simulated)]
    if disease is not None:
        sql += " and (l.disease is null or l.disease = %s)"
        params.append(disease)
    sql += " order by va.captured_at asc, va.leaf_id asc"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        ts = ensure_utc(r["captured_at"], "captured_at")
        out.append({
            "assessment_id": int(r["assessment_id"]),
            "leaf_id": r["leaf_id"],
            "ts": ts.isoformat(),
            "severity_pct": float(r["severity_pct"]),
            "severity_sd_pct": None if r["severity_sd_pct"] is None else float(r["severity_sd_pct"]),
        })
    return out


# --------------------------------------------------------------------------
# Clima (`weather_hourly` e `dsv_daily`)
# --------------------------------------------------------------------------
def get_weather_hourly(
    conn,
    station_id: str = "sj_vasos",
    kind: str = "observed",
    start: Optional[Any] = None,
    end: Optional[Any] = None,
) -> list[dict]:
    if kind not in ("observed", "forecast"):
        raise ValueError(f"kind inválido: {kind!r}")
    sql = """
        select ts, temp_c, rh_pct, precip_mm, dewpoint_c, wind_ms, rad_wm2,
               leaf_wet, source, is_measured
        from weather_hourly
        where station_id = %s and kind = %s
    """
    params: list[Any] = [station_id, kind]
    if start is not None:
        sql += " and ts >= %s"
        params.append(ensure_utc(start, "start"))
    if end is not None:
        sql += " and ts <= %s"
        params.append(ensure_utc(end, "end"))
    sql += " order by ts asc"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    result: list[dict] = []
    for r in rows:
        ts = ensure_utc(r["ts"], "weather_hourly.ts")
        result.append({
            "ts": ts.isoformat(),
            "temp_c": r["temp_c"],
            "rh_pct": r["rh_pct"],
            "precip_mm": r["precip_mm"],
            "dewpoint_c": r["dewpoint_c"],
            "wind_ms": r["wind_ms"],
            "rad_wm2": r["rad_wm2"],
            "leaf_wet": r["leaf_wet"],
            "source": r["source"],
            "is_measured": r["is_measured"],
        })
    return result


def get_weather_summary(
    conn,
    station_id: str = "sj_vasos",
    now: Optional[Any] = None,
) -> dict:
    """Resumo de cobertura (últimas 72 h observadas e próximas 168 h previstas) e última observação."""
    now_utc = ensure_utc(now, "now") if now is not None else datetime.now(UTC)
    now_hour = now_utc.replace(minute=0, second=0, microsecond=0)
    obs_start = now_hour - timedelta(hours=72)
    fc_end = now_hour + timedelta(hours=168)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select count(*) filter (where temp_c is not null and rh_pct is not null) as usable_rows,
                   count(*) as total_rows
            from weather_hourly
            where station_id = %s and kind = 'observed' and ts > %s and ts <= %s
            """,
            (station_id, obs_start, now_hour),
        )
        obs_stats = cur.fetchone() or {"usable_rows": 0, "total_rows": 0}

        cur.execute(
            """
            select count(*) filter (where temp_c is not null and rh_pct is not null) as usable_rows,
                   count(*) as total_rows
            from weather_hourly
            where station_id = %s and kind = 'forecast' and ts > %s and ts <= %s
            """,
            (station_id, now_hour, fc_end),
        )
        fc_stats = cur.fetchone() or {"usable_rows": 0, "total_rows": 0}

        cur.execute(
            """
            select ts, source, temp_c, rh_pct, precip_mm, leaf_wet, is_measured
            from weather_hourly
            where station_id = %s and kind = 'observed'
            order by ts desc
            limit 1
            """,
            (station_id,),
        )
        last_obs = cur.fetchone()

    last_payload = None
    if last_obs:
        ts_utc = ensure_utc(last_obs["ts"], "last_obs.ts")
        last_payload = {
            "ts": ts_utc.astimezone(LOCAL_TZ).isoformat(),
            "source": last_obs["source"],
            "temp_c": last_obs["temp_c"],
            "rh_pct": last_obs["rh_pct"],
            "precip_mm": last_obs["precip_mm"],
            "leaf_wet": last_obs["leaf_wet"],
            "is_measured": last_obs["is_measured"],
        }

    return {
        "station_id": station_id,
        "checked_at": now_utc.astimezone(LOCAL_TZ).isoformat(),
        "observed_72h_rows": int(obs_stats["usable_rows"]),
        "observed_72h_coverage": round(int(obs_stats["usable_rows"]) / 72.0, 4),
        "forecast_168h_rows": int(fc_stats["usable_rows"]),
        "forecast_168h_coverage": round(int(fc_stats["usable_rows"]) / 168.0, 4),
        "last_observed": last_payload,
    }


def upsert_dsv_daily(conn, rows: Sequence[dict]) -> int:
    if not rows:
        return 0
    tuples = [
        (
            r["station_id"],
            r["day"] if isinstance(r["day"], date) else date.fromisoformat(str(r["day"])),
            r["kind"],
            int(r["tomcast_dsv"]),
            int(r["wallin_sv"]),
            int(r["wet_hours"]),
        )
        for r in rows
    ]
    sql = """
        insert into dsv_daily (station_id, day, kind, tomcast_dsv, wallin_sv, wet_hours)
        values %s
        on conflict (station_id, day, kind) do update set
            tomcast_dsv = excluded.tomcast_dsv,
            wallin_sv = excluded.wallin_sv,
            wet_hours = excluded.wet_hours
    """
    with conn, conn.cursor() as cur:
        execute_values(cur, sql, tuples, page_size=500)
    return len(tuples)


def get_dsv_daily(
    conn,
    station_id: str = "sj_vasos",
    kind: str = "observed",
    start_day: Optional[date] = None,
    end_day: Optional[date] = None,
) -> list[dict]:
    sql = """
        select station_id, day, kind, tomcast_dsv, wallin_sv, wet_hours
        from dsv_daily
        where station_id = %s and kind = %s
    """
    params: list[Any] = [station_id, kind]
    if start_day is not None:
        sql += " and day >= %s"
        params.append(start_day)
    if end_day is not None:
        sql += " and day <= %s"
        params.append(end_day)
    sql += " order by day asc"

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Ajustes epidemiológicos (`epi_fits`)
# --------------------------------------------------------------------------
def insert_epi_fit(conn, fit_result: dict, simulated: bool = False) -> int:
    pot_id = validate_pot_id(fit_result["unit_id"])
    disease = validate_disease(fit_result["disease"])
    fitted_utc = ensure_utc(fit_result["fitted_at"], "fitted_at")
    params = fit_result["params"]
    r_ci = params.get("r_ci95") or [None, None]
    aacpd_info = fit_result.get("aacpd") or {}

    with conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into epi_fits (
                pot_id, disease, fitted_at, model, n_obs, r, r_lo95, r_hi95,
                aacpd_observed, aacpd_total_median, state, result, simulated
            )
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning fit_id
            """,
            (
                pot_id,
                disease,
                fitted_utc,
                fit_result["model"],
                int(fit_result["n_obs"]),
                float(params["r"]),
                None if r_ci[0] is None else float(r_ci[0]),
                None if r_ci[1] is None else float(r_ci[1]),
                aacpd_info.get("observed"),
                aacpd_info.get("total_median"),
                Json(fit_result["state"]),
                Json(fit_result),
                bool(simulated),
            ),
        )
        return int(cur.fetchone()[0])


def get_latest_epi_fit(
    conn,
    pot_id: str,
    disease: str,
    simulated: bool = False,
) -> Optional[dict]:
    validate_pot_id(pot_id)
    validate_disease(disease)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select fit_id, pot_id, disease, fitted_at, model, n_obs, r, r_lo95, r_hi95,
                   aacpd_observed, aacpd_total_median, state, result, simulated
            from epi_fits
            where pot_id = %s and disease = %s and simulated = %s
            order by fitted_at desc, fit_id desc
            limit 1
            """,
            (pot_id, disease, bool(simulated)),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------
# Aplicações (`spray_events`)
# --------------------------------------------------------------------------
def insert_spray_event(
    conn,
    pot_id: str,
    applied_at: Any,
    product: str,
    dose: Optional[str] = None,
    notes: Optional[str] = None,
    simulated: bool = False,
) -> int:
    validate_pot_id(pot_id)
    if not product or not str(product).strip():
        raise ValueError("product é obrigatório")
    applied_utc = ensure_utc(applied_at, "applied_at")
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into spray_events (pot_id, applied_at, product, dose, notes, simulated)
            values (%s, %s, %s, %s, %s, %s)
            returning spray_id
            """,
            (pot_id, applied_utc, str(product).strip(), dose, notes, bool(simulated)),
        )
        return int(cur.fetchone()[0])


def get_spray_events(conn, pot_id: str, simulated: bool = False) -> list[dict]:
    validate_pot_id(pot_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select spray_id, pot_id, applied_at, product, dose, notes, simulated
            from spray_events
            where pot_id = %s and simulated = %s
            order by applied_at asc, spray_id asc
            """,
            (pot_id, bool(simulated)),
        )
        rows = cur.fetchall()
    out: list[dict] = []
    for r in rows:
        item = dict(r)
        item["applied_at"] = ensure_utc(item["applied_at"], "applied_at").isoformat()
        out.append(item)
    return out


def get_last_spray_event(conn, pot_id: str, simulated: bool = False) -> Optional[dict]:
    events = get_spray_events(conn, pot_id, simulated=simulated)
    return events[-1] if events else None


# --------------------------------------------------------------------------
# Decisões (`decisions`)
# --------------------------------------------------------------------------
def insert_decision(conn, decision_result: dict, simulated: bool = False) -> int:
    pot_id = validate_pot_id(decision_result["pot_id"])
    disease = validate_disease(decision_result["disease"])
    decided_utc = ensure_utc(decision_result["decided_at"], "decided_at")
    action = decision_result["action"]
    if action not in ("spray", "monitor", "none"):
        raise ValueError(f"action inválida: {action!r}")
    reasons = list(decision_result.get("reasons") or [])

    with conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into decisions (pot_id, disease, decided_at, action, reasons, result, simulated)
            values (%s, %s, %s, %s, %s, %s, %s)
            returning decision_id
            """,
            (pot_id, disease, decided_utc, action, reasons, Json(decision_result), bool(simulated)),
        )
        return int(cur.fetchone()[0])


def get_latest_decision(
    conn,
    pot_id: str,
    disease: str,
    simulated: bool = False,
) -> Optional[dict]:
    validate_pot_id(pot_id)
    validate_disease(disease)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            select decision_id, pot_id, disease, decided_at, action, reasons, result, simulated
            from decisions
            where pot_id = %s and disease = %s and simulated = %s
            order by decided_at desc, decision_id desc
            limit 1
            """,
            (pot_id, disease, bool(simulated)),
        )
        row = cur.fetchone()
        return dict(row) if row else None


# --------------------------------------------------------------------------
# Exportação para o R (SKILL.md seção 9)
# --------------------------------------------------------------------------
AACPD_CSV_COLUMNS = (
    "pot_id",
    "treatment",
    "disease",
    "aacpd",
    "n_avaliacoes",
    "primeira_data",
    "ultima_data",
)


def export_aacpd_csv(
    conn,
    output_path: str | Path,
    disease: str,
    simulated: bool = False,
) -> Path:
    """
    Exporta a AACPD observada por vaso no formato exato da seção 9 do SKILL.md:
    `pot_id, treatment, disease, aacpd, n_avaliacoes, primeira_data, ultima_data`.
    Usa apenas avaliações aceitas (`accepted = true`) agregadas por vaso e dia.
    """
    validate_disease(disease)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("select pot_id, treatment from pots order by pot_id asc")
        pots = [dict(r) for r in cur.fetchall()]

    rows_out: list[dict] = []
    for pot in pots:
        assessments = get_accepted_assessments_for_pot(
            conn, pot["pot_id"], disease=disease, simulated=simulated
        )
        if not assessments:
            continue
        pot_obs = ea.aggregate_leaves_to_pot(assessments)
        times = [o["ts"] for o in pot_obs]
        sevs = [o["severity_pct"] for o in pot_obs]
        area = ea.aacpd(times, sevs) if len(pot_obs) > 1 else 0.0
        first_day = ensure_utc(times[0]).astimezone(LOCAL_TZ).date().isoformat()
        last_day = ensure_utc(times[-1]).astimezone(LOCAL_TZ).date().isoformat()
        rows_out.append({
            "pot_id": pot["pot_id"],
            "treatment": pot["treatment"],
            "disease": disease,
            "aacpd": round(area, 8),
            "n_avaliacoes": len(pot_obs),
            "primeira_data": first_day,
            "ultima_data": last_day,
        })

    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=AACPD_CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)
    return out


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Inicialização e exportação do banco do DSS.")
    parser.add_argument("--init-db", action="store_true", help="cria tabelas e popula V01-V20")
    parser.add_argument("--export-aacpd", help="caminho de saída CSV da AACPD por vaso")
    parser.add_argument("--disease", choices=sorted(VALID_DISEASES), default="pinta_preta")
    parser.add_argument("--simulated", action="store_true", help="exporta dados marcados como simulados")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not args.init_db and not args.export_aacpd:
        parser.error("informe --init-db ou --export-aacpd")

    conn = get_connection()
    try:
        if args.init_db:
            init_db(conn)
            print("banco inicializado com sucesso (tabelas + V01-V20)")
        if args.export_aacpd:
            path = export_aacpd_csv(conn, args.export_aacpd, args.disease, simulated=args.simulated)
            print(f"AACPD exportada em {path}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
