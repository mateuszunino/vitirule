#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
weather_collector.py
====================
Ingere dados horários observados (últimas 72 h) e previstos (próximas 168 h)
para os vasos em São José/SC (-27.5969, -48.6367) e grava na tabela
`weather_hourly` do PostgreSQL/Supabase.

Fontes, em ordem de prioridade
------------------------------
1. EPAGRI/CIRAM (`source_priority` 1). A Epagri não publica API aberta para
   dados horários. O acesso documentado é o portal com cadastro, que entrega
   um CSV dos últimos 24 meses por estação. Este coletor aceita dois caminhos:
   a) `EPAGRI_CSV_DIR`: pasta onde você salva o CSV baixado do portal. O
      arquivo mais recente é lido a cada execução.
   b) `EPAGRI_API_URL`: endpoint JSON, caso o Ciram libere um acesso
      programático para o projeto. O mapeamento de campos é configurável.
   Sem nenhum dos dois, a fonte é pulada e registrada no log.
2. INMET, estação automática A806 (`source_priority` 2), pela API
   apitempo.inmet.gov.br. Horários em UTC. Com `INMET_TOKEN` usa a rota
   autenticada.
3. Open-Meteo (`source_priority` 3): análise de modelo para as horas passadas
   e previsão para as futuras. É a única fonte de previsão horária com API
   aberta nesta lista. Não existe WRF no Open-Meteo. O padrão `best_match`
   escolhe o modelo de maior resolução para o ponto, com GFS e ECMWF IFS na
   sequência.

Uma linha de fonte melhor substitui a de fonte pior para a mesma hora, nunca
o contrário. Assim o CSV da Epagri importado depois corrige o que entrou pelo
INMET ou pelo Open-Meteo. Previsão é sempre sobrescrita pela rodada mais nova.

Convenções
----------
* `ts` é `timestamptz` em UTC e marca o FIM da hora. Temperatura e umidade são
  o valor naquele instante. Chuva é o acumulado dos 60 minutos anteriores.
* `leaf_wet` = UR >= 85 % ou chuva > 0 na hora.
* Fuso de exibição: America/Sao_Paulo, pela view `weather_hourly_local`.

Variáveis de ambiente
---------------------
DATABASE_URL        postgresql://postgres.<ref>:<senha>@<host>:5432/postgres?sslmode=require
STATION_ID          padrão sj_vasos
EPAGRI_CSV_DIR, EPAGRI_API_URL, EPAGRI_API_TOKEN, EPAGRI_STATION_CODE,
EPAGRI_FIELD_MAP (JSON), EPAGRI_TZ (padrão America/Sao_Paulo)
INMET_STATION (padrão A806), INMET_TOKEN
OPEN_METEO_MODELS   padrão best_match,gfs_seamless,ecmwf_ifs025

Uso
---
    python weather_collector.py --init-db        # cria tabelas e view
    python weather_collector.py                  # coleta e grava
    python weather_collector.py --dry-run        # coleta e imprime, sem banco
    # cron, de hora em hora no minuto 10:
    10 * * * * cd /opt/tomato_dss && .venv/bin/python weather_collector.py >> logs/weather.log 2>&1

Status no log: ok, ok_with_fallback (alguma fonte falhou e outra cobriu), partial
(menos de 80 % das 72 h observadas) e failed.
Códigos de saída: 0 sucesso, 1 sem dados observados ou sem previsão, 3 erro de banco.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("weather_collector")

UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
PRIORITY = {"epagri_ciram": 1, "inmet": 2, "open_meteo": 3}

DDL = """
create table if not exists weather_hourly (
    station_id      text        not null,
    ts              timestamptz not null,
    kind            text        not null check (kind in ('observed', 'forecast')),
    source          text        not null,
    source_priority smallint    not null,
    temp_c          double precision,
    rh_pct          double precision,
    precip_mm       double precision,
    dewpoint_c      double precision,
    wind_ms         double precision,
    rad_wm2         double precision,
    leaf_wet        boolean,
    is_measured     boolean     not null,
    issued_at       timestamptz not null,
    ingested_at     timestamptz not null default now(),
    primary key (station_id, ts, kind)
);
create index if not exists weather_hourly_kind_ts on weather_hourly (station_id, kind, ts desc);

create table if not exists weather_forecast_archive (
    station_id text        not null,
    issued_day date        not null,
    ts         timestamptz not null,
    source     text        not null,
    temp_c     double precision,
    rh_pct     double precision,
    precip_mm  double precision,
    leaf_wet   boolean,
    primary key (station_id, issued_day, ts)
);

create table if not exists weather_ingest_log (
    id                bigint generated always as identity primary key,
    run_at            timestamptz not null default now(),
    station_id        text not null,
    status            text not null,
    observed_rows     integer not null,
    forecast_rows     integer not null,
    observed_coverage real,
    sources           jsonb,
    errors            jsonb
);

create or replace view weather_hourly_local as
select w.*, (w.ts at time zone 'America/Sao_Paulo') as ts_local
from weather_hourly w;
"""

UPSERT = """
insert into weather_hourly
    (station_id, ts, kind, source, source_priority, temp_c, rh_pct, precip_mm,
     dewpoint_c, wind_ms, rad_wm2, leaf_wet, is_measured, issued_at)
values %s
on conflict (station_id, ts, kind) do update set
    source = excluded.source, source_priority = excluded.source_priority,
    temp_c = excluded.temp_c, rh_pct = excluded.rh_pct, precip_mm = excluded.precip_mm,
    dewpoint_c = excluded.dewpoint_c, wind_ms = excluded.wind_ms, rad_wm2 = excluded.rad_wm2,
    leaf_wet = excluded.leaf_wet, is_measured = excluded.is_measured,
    issued_at = excluded.issued_at, ingested_at = now()
where weather_hourly.kind = 'forecast'
   or excluded.source_priority <= weather_hourly.source_priority
"""

ARCHIVE = """
insert into weather_forecast_archive
    (station_id, issued_day, ts, source, temp_c, rh_pct, precip_mm, leaf_wet)
values %s
on conflict (station_id, issued_day, ts) do nothing
"""


# --------------------------------------------------------------------------
# Configuração e registro
# --------------------------------------------------------------------------
@dataclass
class Settings:
    database_url: Optional[str] = None
    station_id: str = "sj_vasos"
    latitude: float = -27.5969
    longitude: float = -48.6367
    observed_hours: int = 72
    forecast_hours: int = 168
    min_coverage: float = 0.80
    rh_wet_threshold: float = 85.0
    epagri_csv_dir: Optional[str] = None
    epagri_api_url: Optional[str] = None
    epagri_forecast_url: Optional[str] = None
    epagri_api_token: Optional[str] = None
    epagri_station_code: Optional[str] = None
    epagri_tz: str = "America/Sao_Paulo"
    epagri_field_map: dict = field(default_factory=lambda: {
        "ts": "DataHorario", "temp_c": "TempArInst(C)", "rh_pct": "UmidRelMedia(%)",
        "precip_mm": "Precipitacao(mm)", "wind_ms": "Vel.MediaVento(m/s)"})
    inmet_station: str = "A806"
    inmet_token: Optional[str] = None
    inmet_base_url: str = "https://apitempo.inmet.gov.br"
    open_meteo_url: str = "https://api.open-meteo.com/v1/forecast"
    open_meteo_models: tuple = ("best_match", "gfs_seamless", "ecmwf_ifs025")
    http_attempts: int = 5
    http_backoff_base: float = 1.5
    http_backoff_cap: float = 60.0
    http_timeout: tuple = (5.0, 30.0)
    db_attempts: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        s = cls(database_url=env("DATABASE_URL"))
        s.station_id = env("STATION_ID", s.station_id)
        s.latitude = float(env("STATION_LAT", s.latitude))
        s.longitude = float(env("STATION_LON", s.longitude))
        s.epagri_csv_dir = env("EPAGRI_CSV_DIR")
        s.epagri_api_url = env("EPAGRI_API_URL")
        s.epagri_forecast_url = env("EPAGRI_FORECAST_URL")
        s.epagri_api_token = env("EPAGRI_API_TOKEN")
        s.epagri_station_code = env("EPAGRI_STATION_CODE")
        s.epagri_tz = env("EPAGRI_TZ", s.epagri_tz)
        if env("EPAGRI_FIELD_MAP"):
            s.epagri_field_map = json.loads(env("EPAGRI_FIELD_MAP"))
        s.inmet_station = env("INMET_STATION", s.inmet_station)
        s.inmet_token = env("INMET_TOKEN")
        if env("OPEN_METEO_MODELS"):
            s.open_meteo_models = tuple(m.strip() for m in env("OPEN_METEO_MODELS").split(",") if m.strip())
        return s


@dataclass
class HourlyRecord:
    ts: datetime                      # UTC, hora cheia, fim do intervalo
    kind: str                         # 'observed' | 'forecast'
    source: str
    temp_c: Optional[float] = None
    rh_pct: Optional[float] = None
    precip_mm: Optional[float] = None
    dewpoint_c: Optional[float] = None
    wind_ms: Optional[float] = None
    rad_wm2: Optional[float] = None
    is_measured: bool = True

    def leaf_wet(self, rh_threshold: float) -> Optional[bool]:
        if self.rh_pct is None and self.precip_mm is None:
            return None
        return bool((self.rh_pct is not None and self.rh_pct >= rh_threshold)
                    or (self.precip_mm is not None and self.precip_mm > 0))

    def usable(self) -> bool:
        return self.temp_c is not None and self.rh_pct is not None


class ProviderUnavailable(Exception):
    """A fonte não está configurada ou não respondeu depois das tentativas."""


class TransientHTTPError(Exception):
    """Falha que pode passar sozinha: rede, timeout, 408, 425, 429 ou 5xx."""


class PermanentHTTPError(Exception):
    """Resposta 4xx que não muda com nova tentativa."""


# --------------------------------------------------------------------------
# HTTP com retry exponencial
# --------------------------------------------------------------------------
def http_get(session: requests.Session, url: str, settings: Settings,
             params: Optional[dict] = None, headers: Optional[dict] = None,
             sleep: Callable[[float], None] = time.sleep,
             redact: Optional[str] = None) -> requests.Response:
    """
    GET com recuo exponencial e jitter. Repete em erro de rede, timeout, 408,
    425, 429 e 5xx, respeitando `Retry-After`. Os demais 4xx falham na hora,
    porque repetir não muda a resposta.
    """
    shown = url.replace(redact, "***") if redact else url     # token fora do log
    hide = lambda exc: str(exc).replace(redact, "***") if redact else str(exc)
    last: Optional[Exception] = None
    for attempt in range(1, settings.http_attempts + 1):
        retry_after = None
        try:
            resp = session.get(url, params=params, headers=headers, timeout=settings.http_timeout)
        except (requests.ConnectionError, requests.Timeout,
                requests.exceptions.ChunkedEncodingError) as exc:
            last = exc
        else:
            code = resp.status_code
            if code in (200, 204):
                return resp
            if code in (408, 425, 429) or code >= 500:
                last = TransientHTTPError(f"HTTP {code} em {shown}")
                retry_after = resp.headers.get("Retry-After")
            else:
                raise PermanentHTTPError(f"HTTP {code} em {shown}")
        if attempt == settings.http_attempts:
            break
        delay = min(settings.http_backoff_cap, settings.http_backoff_base * 2 ** (attempt - 1))
        delay = random.uniform(0.5 * delay, delay)
        if retry_after and retry_after.strip().isdigit():
            delay = min(settings.http_backoff_cap, max(delay, float(retry_after)))
        log.warning("tentativa %d/%d falhou (%s); nova tentativa em %.1f s",
                    attempt, settings.http_attempts, hide(last), delay)
        sleep(delay)
    raise TransientHTTPError(f"sem resposta após {settings.http_attempts} tentativas: {hide(last)}")


# --------------------------------------------------------------------------
# Normalização
# --------------------------------------------------------------------------
_MISSING = {"", "null", "none", "nan", "-", "9999.9", "-9999", "-9999.0", "9999"}


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if text.lower() in _MISSING:
            return None
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            return None
    if number != number or abs(number) >= 9999:       # NaN ou código de falha
        return None
    return number


def in_range(value: Optional[float], low: float, high: float) -> Optional[float]:
    return value if value is not None and low <= value <= high else None


def round_to_hour(ts: datetime) -> datetime:
    """Arredonda para a hora cheia mais próxima, em UTC."""
    ts = ts.astimezone(UTC)
    base = ts.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(hours=1) if ts.minute >= 30 else base


def clean(record: HourlyRecord) -> HourlyRecord:
    """Aplica limites físicos. Valor fora da faixa vira nulo, não é corrigido."""
    record.ts = round_to_hour(record.ts)
    record.temp_c = in_range(record.temp_c, -15.0, 50.0)
    rh = record.rh_pct
    record.rh_pct = None if rh is None or not 0.0 <= rh <= 105.0 else min(rh, 100.0)
    record.precip_mm = in_range(record.precip_mm, 0.0, 200.0)
    record.dewpoint_c = in_range(record.dewpoint_c, -30.0, 40.0)
    record.wind_ms = in_range(record.wind_ms, 0.0, 75.0)
    record.rad_wm2 = in_range(record.rad_wm2, 0.0, 1500.0)
    return record


def coverage(records: Iterable[HourlyRecord], start: datetime, end: datetime) -> float:
    """Fração das horas em (start, end] com temperatura e umidade válidas."""
    total = int((end - start).total_seconds() // 3600)
    if total <= 0:
        return 0.0
    have = {r.ts for r in records if r.usable() and start < r.ts <= end}
    return len(have) / total


def diurnal_peak_hour(records: Sequence[HourlyRecord]) -> Optional[int]:
    """Hora local do pico médio de temperatura. Fora de 11-17 h indica fuso trocado."""
    sums: dict[int, list[float]] = {}
    for r in records:
        if r.temp_c is not None:
            sums.setdefault(r.ts.astimezone(LOCAL_TZ).hour, []).append(r.temp_c)
    if len(sums) < 20:
        return None
    return max(sums, key=lambda h: sum(sums[h]) / len(sums[h]))


# --------------------------------------------------------------------------
# Fontes
# --------------------------------------------------------------------------
class EpagriProvider:
    name = "epagri_ciram"

    def __init__(self, settings: Settings, session: requests.Session):
        self.s, self.session = settings, session

    def configured(self) -> bool:
        return bool(self.s.epagri_csv_dir or self.s.epagri_api_url)

    # -- CSV do portal dadosambientaispublicos -----------------------------
    def parse_csv(self, path: Path) -> list[HourlyRecord]:
        """
        Formato do portal: linha 1 com dados da estação, linha 2 com o
        cabeçalho, depois uma linha por hora, com vírgula sobrando no fim e
        9999.9 no lugar de dado ausente. Data em DD/MM/AAAA HH:MM:SS.
        O manual não diz se a hora é local ou UTC (confirmar com o Ciram).
        O padrão aqui é local, ajustável por EPAGRI_TZ.
        """
        tz = ZoneInfo(self.s.epagri_tz)
        fmap = self.s.epagri_field_map
        records: list[HourlyRecord] = []
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
            rows = list(csv.reader(fh))
        header_at = next((i for i, row in enumerate(rows) if fmap["ts"] in row), None)
        if header_at is None:
            raise ProviderUnavailable(f"cabeçalho '{fmap['ts']}' não encontrado em {path.name}")
        header = [h.strip() for h in rows[header_at]]
        col = {key: header.index(name) for key, name in fmap.items() if name in header}
        for row in rows[header_at + 1:]:
            if len(row) <= col["ts"] or not row[col["ts"]].strip():
                continue
            try:
                local = datetime.strptime(row[col["ts"]].strip(), "%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue
            get = lambda key: to_float(row[col[key]]) if key in col and col[key] < len(row) else None
            records.append(HourlyRecord(ts=local.replace(tzinfo=tz).astimezone(UTC), kind="observed",
                                        source=self.name, temp_c=get("temp_c"), rh_pct=get("rh_pct"),
                                        precip_mm=get("precip_mm"), wind_ms=get("wind_ms")))
        return records

    def _from_csv_dir(self) -> list[HourlyRecord]:
        folder = Path(self.s.epagri_csv_dir)
        files = sorted(folder.glob("*.csv"), key=lambda p: p.stat().st_mtime)
        if not files:
            raise ProviderUnavailable(f"nenhum CSV em {folder}")
        log.info("EPAGRI: lendo %s", files[-1].name)
        return self.parse_csv(files[-1])

    # -- endpoint JSON, se houver acesso -----------------------------------
    def _from_api(self, url: str, kind: str, start: datetime, end: datetime) -> list[HourlyRecord]:
        tz = ZoneInfo(self.s.epagri_tz)
        fmap = self.s.epagri_field_map
        headers = {"Accept": "application/json"}
        if self.s.epagri_api_token:
            headers["Authorization"] = f"Bearer {self.s.epagri_api_token}"
        url = url.format(station=self.s.epagri_station_code or "",
                         start=start.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S"),
                         end=end.astimezone(tz).strftime("%Y-%m-%dT%H:%M:%S"),
                         lat=self.s.latitude, lon=self.s.longitude)
        payload = http_get(self.session, url, self.s, headers=headers).json()
        rows = payload.get("data", payload.get("dados", [])) if isinstance(payload, dict) else payload
        records = []
        for row in rows:
            raw = row.get(fmap["ts"])
            if raw is None:
                continue
            text = str(raw).strip()
            try:
                stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                try:
                    stamp = datetime.strptime(text, "%d/%m/%Y %H:%M:%S")
                except ValueError:
                    continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=tz)
            records.append(HourlyRecord(
                ts=stamp.astimezone(UTC), kind=kind, source=self.name,
                temp_c=to_float(row.get(fmap.get("temp_c", ""))),
                rh_pct=to_float(row.get(fmap.get("rh_pct", ""))),
                precip_mm=to_float(row.get(fmap.get("precip_mm", ""))),
                wind_ms=to_float(row.get(fmap.get("wind_ms", ""))),
                is_measured=(kind == "observed")))
        return records

    def observed(self, start: datetime, end: datetime) -> list[HourlyRecord]:
        if not self.configured():
            raise ProviderUnavailable("EPAGRI sem EPAGRI_CSV_DIR nem EPAGRI_API_URL")
        try:
            if self.s.epagri_api_url:
                return self._from_api(self.s.epagri_api_url, "observed", start, end)
            return self._from_csv_dir()
        except (TransientHTTPError, PermanentHTTPError, ValueError, OSError, KeyError) as exc:
            raise ProviderUnavailable(f"EPAGRI: {exc}") from exc

    def forecast(self, start: datetime, end: datetime) -> list[HourlyRecord]:
        if not self.s.epagri_forecast_url:
            raise ProviderUnavailable("EPAGRI sem EPAGRI_FORECAST_URL")
        try:
            return self._from_api(self.s.epagri_forecast_url, "forecast", start, end)
        except (TransientHTTPError, PermanentHTTPError, ValueError, KeyError) as exc:
            raise ProviderUnavailable(f"EPAGRI previsão: {exc}") from exc


class InmetProvider:
    """
    Estação automática do INMET. Rotas usadas (confirmar no manual da API do
    INMET se mudarem):
      com token:  /token/estacao/{AAAA-MM-DD}/{AAAA-MM-DD}/{codigo}/{token}
      sem token:  /estacao/{AAAA-MM-DD}/{AAAA-MM-DD}/{codigo}
    A resposta é uma lista com DT_MEDICAO (data) e HR_MEDICAO ('HHMM') em UTC.
    """
    name = "inmet"

    def __init__(self, settings: Settings, session: requests.Session):
        self.s, self.session = settings, session

    def observed(self, start: datetime, end: datetime) -> list[HourlyRecord]:
        d0, d1 = start.astimezone(UTC).date().isoformat(), end.astimezone(UTC).date().isoformat()
        base = self.s.inmet_base_url.rstrip("/")
        if self.s.inmet_token:
            url = f"{base}/token/estacao/{d0}/{d1}/{self.s.inmet_station}/{self.s.inmet_token}"
        else:
            url = f"{base}/estacao/{d0}/{d1}/{self.s.inmet_station}"
        try:
            resp = http_get(self.session, url, self.s, redact=self.s.inmet_token)
            if resp.status_code == 204 or not resp.content.strip():
                raise ProviderUnavailable("INMET respondeu sem conteúdo (token ausente ou estação sem dados)")
            payload = resp.json()
        except (TransientHTTPError, PermanentHTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"INMET: {exc}") from None
        if not isinstance(payload, list):
            raise ProviderUnavailable(f"INMET: resposta inesperada ({str(payload)[:120]})")
        records = []
        for row in payload:
            day, hhmm = row.get("DT_MEDICAO"), str(row.get("HR_MEDICAO", "")).zfill(4)
            if not day or not hhmm.isdigit():
                continue
            try:
                stamp = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=UTC)
            except ValueError:
                continue
            rad_kj = to_float(row.get("RAD_GLO"))          # kJ/m² na hora
            records.append(HourlyRecord(
                ts=stamp, kind="observed", source=self.name,
                temp_c=to_float(row.get("TEM_INS")), rh_pct=to_float(row.get("UMD_INS")),
                precip_mm=to_float(row.get("CHUVA")), dewpoint_c=to_float(row.get("PTO_INS")),
                wind_ms=to_float(row.get("VEN_VEL")),
                rad_wm2=None if rad_kj is None else max(rad_kj, 0.0) / 3.6))
        return records


class OpenMeteoProvider:
    name = "open_meteo"
    VARIABLES = ("temperature_2m", "relative_humidity_2m", "dew_point_2m",
                 "precipitation", "wind_speed_10m", "shortwave_radiation")

    def __init__(self, settings: Settings, session: requests.Session):
        self.s, self.session = settings, session

    def fetch(self, model: str, now: datetime) -> tuple[list[HourlyRecord], list[HourlyRecord]]:
        """Uma chamada devolve o passado recente e a previsão. Tempo pedido em UTC, em epoch."""
        params = {
            "latitude": self.s.latitude, "longitude": self.s.longitude,
            "hourly": ",".join(self.VARIABLES),
            "past_days": self.s.observed_hours // 24 + 1,
            "forecast_days": self.s.forecast_hours // 24 + 2,
            "timezone": "GMT", "timeformat": "unixtime", "wind_speed_unit": "ms",
            "models": model,
        }
        try:
            payload = http_get(self.session, self.s.open_meteo_url, self.s, params=params).json()
        except (TransientHTTPError, PermanentHTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"Open-Meteo [{model}]: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("error") or "hourly" not in payload:
            reason = payload.get("reason") if isinstance(payload, dict) else payload
            raise ProviderUnavailable(f"Open-Meteo [{model}]: {str(reason)[:160]}")
        hourly = payload["hourly"]
        column = lambda name: hourly.get(name) or [None] * len(hourly["time"])
        observed, forecast = [], []
        for i, epoch in enumerate(hourly["time"]):
            stamp = datetime.fromtimestamp(int(epoch), tz=UTC)
            kind = "observed" if stamp <= now else "forecast"
            record = HourlyRecord(
                ts=stamp, kind=kind, source=self.name, is_measured=False,
                temp_c=to_float(column("temperature_2m")[i]),
                rh_pct=to_float(column("relative_humidity_2m")[i]),
                dewpoint_c=to_float(column("dew_point_2m")[i]),
                precip_mm=to_float(column("precipitation")[i]),
                wind_ms=to_float(column("wind_speed_10m")[i]),
                rad_wm2=to_float(column("shortwave_radiation")[i]))
            (observed if kind == "observed" else forecast).append(record)
        return observed, forecast


# --------------------------------------------------------------------------
# Orquestração
# --------------------------------------------------------------------------
@dataclass
class CollectionResult:
    observed: list[HourlyRecord]
    forecast: list[HourlyRecord]
    observed_coverage: float
    forecast_coverage: float
    sources: dict
    errors: list[str]
    warnings: list[str]
    issued_at: datetime

    min_coverage: float = 0.80

    @property
    def status(self) -> str:
        if not self.observed or not self.forecast:
            return "failed"
        if self.observed_coverage < self.min_coverage:
            return "partial"
        return "ok" if not self.errors else "ok_with_fallback"


def collect(settings: Settings, now: Optional[datetime] = None,
            session: Optional[requests.Session] = None) -> CollectionResult:
    """
    Observado: EPAGRI, depois INMET para as horas que a EPAGRI não trouxe
    (o CSV do portal costuma estar algumas horas atrasado), e por fim o
    Open-Meteo preenche o que ainda sobrar vazio.
    Previsão: EPAGRI se houver endpoint, senão os modelos do Open-Meteo em
    sequência até um cobrir 90 % das 168 h.
    """
    now = (now or datetime.now(UTC)).astimezone(UTC)
    now_hour = now.replace(minute=0, second=0, microsecond=0)
    obs_start = now_hour - timedelta(hours=settings.observed_hours)
    fc_end = now_hour + timedelta(hours=settings.forecast_hours)
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", "tomato-dss-weather/1.0 (pesquisa; UFSC)")
    errors: list[str] = []
    warnings: list[str] = []
    sources: dict[str, Any] = {"observed": {}, "forecast": None}

    merged: dict[datetime, HourlyRecord] = {}

    def absorb(records: Iterable[HourlyRecord], label: str) -> None:
        cleaned = [clean(r) for r in records]
        peak = diurnal_peak_hour([r for r in cleaned if r.is_measured])
        if peak is not None and not 11 <= peak <= 17:
            warnings.append(f"{label}: pico de temperatura às {peak} h locais; conferir o fuso da fonte")
        added = 0
        for r in sorted(cleaned, key=lambda r: r.ts):
            if not (obs_start < r.ts <= now_hour) or not r.usable():
                continue
            current = merged.get(r.ts)
            if current is None or PRIORITY[r.source] < PRIORITY[current.source]:
                merged[r.ts] = r
                added += 1
        sources["observed"][label] = added

    for provider in (EpagriProvider(settings, session), InmetProvider(settings, session)):
        if coverage(merged.values(), obs_start, now_hour) >= 1.0:
            break       # só pula a próxima fonte medida se não sobrou hora vazia
        try:
            absorb(provider.observed(obs_start, now_hour), provider.name)
        except ProviderUnavailable as exc:
            errors.append(str(exc))
            log.warning("%s", exc)

    # Open-Meteo: sempre consultado, pois traz a previsão. O passado tapa buracos.
    forecast: list[HourlyRecord] = []
    epagri = EpagriProvider(settings, session)
    try:
        forecast = [clean(r) for r in epagri.forecast(now_hour, fc_end)]
        forecast = [r for r in forecast if now_hour < r.ts <= fc_end]
        if coverage(forecast, now_hour, fc_end) >= 0.90:
            sources["forecast"] = "epagri_ciram"
        else:
            forecast = []
    except ProviderUnavailable as exc:
        log.info("%s", exc)

    open_meteo = OpenMeteoProvider(settings, session)
    filled_past = False
    for model in settings.open_meteo_models:
        if sources["forecast"] and filled_past:
            break
        try:
            past, future = open_meteo.fetch(model, now_hour)
        except ProviderUnavailable as exc:
            errors.append(str(exc))
            log.warning("%s", exc)
            continue
        if not filled_past:
            absorb(past, "open_meteo")
            filled_past = True
        if not sources["forecast"]:
            candidate = [r for r in (clean(r) for r in future) if now_hour < r.ts <= fc_end]
            if coverage(candidate, now_hour, fc_end) >= 0.90:
                forecast, sources["forecast"] = candidate, f"open_meteo:{model}"
            else:
                errors.append(f"Open-Meteo [{model}]: previsão cobre menos de 90 % das {settings.forecast_hours} h")

    observed = sorted(merged.values(), key=lambda r: r.ts)
    return CollectionResult(
        observed=observed, forecast=sorted(forecast, key=lambda r: r.ts),
        observed_coverage=round(coverage(observed, obs_start, now_hour), 4),
        forecast_coverage=round(coverage(forecast, now_hour, fc_end), 4),
        sources=sources, errors=errors, warnings=warnings, issued_at=now,
        min_coverage=settings.min_coverage)


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
def connect(settings: Settings, sleep: Callable[[float], None] = time.sleep):
    import psycopg2
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL não definida")
    last: Optional[Exception] = None
    for attempt in range(1, settings.db_attempts + 1):
        try:
            return psycopg2.connect(settings.database_url, connect_timeout=10,
                                    application_name="tomato_dss_weather")
        except psycopg2.OperationalError as exc:
            last = exc
            if attempt < settings.db_attempts:
                delay = min(30.0, 2.0 ** attempt) * random.uniform(0.5, 1.0)
                log.warning("conexão com o banco falhou (%d/%d); nova tentativa em %.1f s",
                            attempt, settings.db_attempts, delay)
                sleep(delay)
    raise RuntimeError(f"banco indisponível: {last}")


def init_db(conn) -> None:
    with conn, conn.cursor() as cur:
        cur.execute(DDL)


def _row(record: HourlyRecord, settings: Settings, issued_at: datetime) -> tuple:
    return (settings.station_id, record.ts, record.kind, record.source, PRIORITY[record.source],
            record.temp_c, record.rh_pct, record.precip_mm, record.dewpoint_c, record.wind_ms,
            record.rad_wm2, record.leaf_wet(settings.rh_wet_threshold), record.is_measured, issued_at)


def store(conn, result: CollectionResult, settings: Settings) -> dict:
    """Grava tudo em uma transação: observado, previsão, arquivo diário da previsão e log."""
    from psycopg2.extras import Json, execute_values
    rows = [_row(r, settings, result.issued_at) for r in result.observed + result.forecast]
    issued_day = result.issued_at.astimezone(LOCAL_TZ).date()
    archive = [(settings.station_id, issued_day, r.ts, r.source, r.temp_c, r.rh_pct, r.precip_mm,
                r.leaf_wet(settings.rh_wet_threshold)) for r in result.forecast]
    with conn, conn.cursor() as cur:
        if rows:
            execute_values(cur, UPSERT, rows, page_size=500)
        if archive:
            execute_values(cur, ARCHIVE, archive, page_size=500)
        cur.execute(
            "insert into weather_ingest_log (station_id, status, observed_rows, forecast_rows,"
            " observed_coverage, sources, errors) values (%s, %s, %s, %s, %s, %s, %s)",
            (settings.station_id, result.status, len(result.observed), len(result.forecast),
             result.observed_coverage, Json(result.sources), Json(result.errors + result.warnings)))
    return {"upserted": len(rows), "archived": len(archive)}


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------
def summary(result: CollectionResult) -> dict:
    last = result.observed[-1] if result.observed else None
    return {
        "status": result.status,
        "issued_at": result.issued_at.astimezone(LOCAL_TZ).isoformat(),
        "observed_rows": len(result.observed), "observed_coverage": result.observed_coverage,
        "forecast_rows": len(result.forecast), "forecast_coverage": result.forecast_coverage,
        "sources": result.sources,
        "last_observed": None if last is None else {
            "ts_local": last.ts.astimezone(LOCAL_TZ).isoformat(), "source": last.source,
            "temp_c": last.temp_c, "rh_pct": last.rh_pct, "precip_mm": last.precip_mm},
        "errors": result.errors, "warnings": result.warnings,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Coletor meteorológico do DSS de tomateiro.")
    parser.add_argument("--init-db", action="store_true", help="cria tabelas e view e sai")
    parser.add_argument("--dry-run", action="store_true", help="não grava no banco")
    parser.add_argument("--now", help="instante de referência em ISO 8601 (testes)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()

    if args.init_db:
        try:
            conn = connect(settings)
            init_db(conn)
            conn.close()
        except Exception as exc:
            log.error("falha ao criar o esquema: %s", exc)
            return 3
        print("esquema criado")
        return 0

    now = datetime.fromisoformat(args.now) if args.now else None
    if now is not None and now.tzinfo is None:
        parser.error("--now precisa de fuso, ex.: 2026-12-01T09:00:00-03:00")
    result = collect(settings, now=now)
    report = summary(result)
    if not args.dry_run and result.status != "failed":
        try:
            conn = connect(settings)
            try:
                report["db"] = store(conn, result, settings)
            finally:
                conn.close()
        except Exception as exc:
            log.error("falha ao gravar no banco: %s", exc)
            report["db_error"] = str(exc)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 3
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if result.status != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
