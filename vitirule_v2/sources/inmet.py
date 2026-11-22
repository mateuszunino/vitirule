"""
Leitor e seletor objetivo de estacoes automaticas horarias do INMET em Santa
Catarina + filtro oficial de municipios produtores pela PAM/IBGE (SIDRA 5457),
conforme o Adendo Brasil congelado na tag `v2-freeze-br` em `docs/v2/preregistro.md`.

Notas importantes:
- Nao inclui leitor da Epagri/Ciram nesta etapa (entra somente quando os arquivos
  oficiais chegarem e o formato real for conhecido).
- Todos os timestamps do INMET sao lidos e normalizados explicitamente em UTC.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from ..rules.common import HourlyRecord

UTC = timezone.utc

INMET_HIST_ZIP_URL = "https://portal.inmet.gov.br/uploads/dadoshistoricos/{year}.zip"
IBGE_SIDRA_PAM_SC_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/5457/periodos/{year}"
    "/variaveis/216?localidades=N6[N3[42]]&classificacao=782[40260,40126,40274]"
)
# Mapeamento explicito de nomes de estacoes do INMET em SC que trazem
# abreviacao ou designacao diferente do nome oficial do municipio no IBGE.
INMET_STATION_TO_MUNICIPALITY_ALIASES: dict[str, str] = {
    "SAO MIGUEL DO OESTE": "SAO MIGUEL DO OESTE",
    "MAJOR VIEIRA": "MAJOR VIEIRA",
    "RIO DO CAMPO": "RIO DO CAMPO",
    "ITUPORANGA": "ITUPORANGA",
    "NOVO HORIZONTE": "NOVO HORIZONTE",
    "XANXERE": "XANXERE",
    "DIONISIO CERQUEIRA": "DIONISIO CERQUEIRA",
    "JOACABA": "JOACABA",
    "CACADOR": "CACADOR",
    "CURITIBANOS": "CURITIBANOS",
    "CAMPOS NOVOS": "CAMPOS NOVOS",
    "SAO JOAQUIM": "SAO JOAQUIM",
    "LAGES": "LAGES",
    "URUSSANGA": "URUSSANGA",
    "ARARANGUA": "ARARANGUA",
    "FLORIANOPOLIS": "FLORIANOPOLIS",
    "FLORIANOPOLIS-SAO JOSE": "SAO JOSE",
    "ITAJAI": "ITAJAI",
    "INDAIAL": "INDAIAL",
    "RIO NEGRINHO": "RIO NEGRINHO",
    "CHAPECO": "CHAPECO",
    "RANCHO QUEIMADO": "RANCHO QUEIMADO",
    "ITAPOA": "ITAPOA",
    "BOM JARDIM DA SERRA": "BOM JARDIM DA SERRA",
    "BOM JARDIM DA SERRA - MORRO DA IGREJA": "BOM JARDIM DA SERRA",
    "MORRO DA IGREJA": "BOM JARDIM DA SERRA",
    "SAO JOSE": "SAO JOSE",
    "TUBARAO": "TUBARAO",
    "CRICIUMA": "CRICIUMA",
    "JOINVILLE": "JOINVILLE",
    "BLUMENAU": "BLUMENAU",
    "LAGUNA - FAROL DE SANTA MARTA": "LAGUNA",
    "LAGUNA": "LAGUNA",
}


def normalize_br_name(name: str) -> str:
    """Remove acentos, espacos duplicados e converte para maiusculas ASCII."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s*-\s*SC\s*$", "", s.strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s


def _parse_br_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v) or v <= -999.0:
        return None
    return v


@dataclass(frozen=True)
class InmetStationInfo:
    station_id: str
    station_name: str
    municipality_key: str
    uf: str
    lat: float
    lon: float
    elevation_m: float | None
    csv_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["csv_paths"] = [str(p) for p in self.csv_paths]
        return d


def parse_inmet_csv_header(path: str | Path) -> dict[str, Any]:
    """Lê as 8 primeiras linhas de metadados de um CSV oficial do INMET."""
    p = Path(path)
    meta: dict[str, str] = {}
    with p.open("r", encoding="latin-1", errors="replace") as fh:
        for _ in range(8):
            line = fh.readline()
            if not line:
                break
            parts = line.rstrip("\r\n").split(";")
            if len(parts) >= 2:
                k = normalize_br_name(parts[0].rstrip(":"))
                meta[k] = parts[1].strip()
    station_name = meta.get("ESTACAO", p.stem)
    norm_name = normalize_br_name(station_name)
    muni_key = INMET_STATION_TO_MUNICIPALITY_ALIASES.get(norm_name, norm_name)
    return {
        "station_id": meta.get("CODIGO (WMO)", "").strip().upper(),
        "station_name": station_name,
        "municipality_key": muni_key,
        "uf": meta.get("UF", "SC").strip().upper(),
        "lat": _parse_br_float(meta.get("LATITUDE")),
        "lon": _parse_br_float(meta.get("LONGITUDE")),
        "elevation_m": _parse_br_float(meta.get("ALTITUDE")),
    }


def _find_col(headers: Sequence[str], *needles: str) -> int | None:
    norm_headers = [normalize_br_name(h) for h in headers]
    for idx, h in enumerate(norm_headers):
        if all(n in h for n in needles):
            return idx
    return None


def parse_inmet_csv_records(path: str | Path) -> list[HourlyRecord]:
    """
    Lê as linhas horárias de um CSV oficial do INMET em UTC (`HourlyRecord`).

    - Converte radiação global de `Kj/m²` para `W/m²` dividindo por `3.6`.
    - Mantém `wet=None` (estação automática sem sensor de molhamento foliar).
    - Trata strings vazias e sentinelas `<= -999` como `None`.
    """
    p = Path(path)
    records: list[HourlyRecord] = []
    with p.open("r", encoding="latin-1", errors="replace", newline="") as fh:
        for _ in range(8):
            fh.readline()
        reader = csv.reader(fh, delimiter=";")
        headers = next(reader, None)
        if not headers:
            return []

        i_date = _find_col(headers, "DATA")
        i_hour = _find_col(headers, "HORA")
        i_precip = _find_col(headers, "PRECIPITACAO", "HORARIO")
        i_temp = _find_col(headers, "TEMPERATURA DO AR", "BULBO SECO")
        i_rh = _find_col(headers, "UMIDADE RELATIVA", "HORARIA")
        i_wind = _find_col(headers, "VENTO", "VELOCIDADE")
        i_rad = _find_col(headers, "RADIACAO")

        if i_date is None or i_hour is None:
            raise ValueError(f"Colunas DATA/HORA ausentes em {p.name}: {headers}")

        for row in reader:
            if not row or len(row) <= max(i_date, i_hour):
                continue
            raw_d = row[i_date].strip()
            raw_h = row[i_hour].strip()
            if not raw_d or not raw_h:
                continue

            # Data pode vir em YYYY/MM/DD ou YYYY-MM-DD
            d_clean = raw_d.replace("-", "/")
            m_h = re.match(r"^(\d{2}):?(\d{2})", raw_h)
            if not m_h:
                continue
            hh, mm = int(m_h.group(1)), int(m_h.group(2))
            try:
                dt = datetime.strptime(d_clean, "%Y/%m/%d").replace(hour=hh, minute=mm, tzinfo=UTC)
            except ValueError:
                continue

            def _get(idx: int | None) -> float | None:
                if idx is None or idx >= len(row):
                    return None
                return _parse_br_float(row[idx])

            rad_kj = _get(i_rad)
            rad_wm2 = (max(0.0, rad_kj) / 3.6) if rad_kj is not None else None
            precip = _get(i_precip)
            temp = _get(i_temp)
            rh = _get(i_rh)
            wind = _get(i_wind)

            records.append(
                HourlyRecord(
                    ts=dt,
                    temp_c=temp,
                    rh_pct=rh,
                    precip_mm=precip,
                    wet=None,
                    wind_ms=wind,
                    rad_wm2=rad_wm2,
                )
            )
    return records


def load_inmet_station_records(paths: Sequence[str | Path]) -> list[HourlyRecord]:
    """Carrega e ordena em UTC os registros de múltiplos anos de uma estação INMET."""
    by_ts: dict[datetime, HourlyRecord] = {}
    for p in sorted(paths, key=lambda x: str(x)):
        for rec in parse_inmet_csv_records(p):
            by_ts[rec.ts] = rec
    return [by_ts[k] for k in sorted(by_ts)]


def discover_inmet_sc_stations(root_dir: str | Path, years: Sequence[int] = (2022, 2023, 2024, 2025)) -> list[InmetStationInfo]:
    """Descobre e agrupa por código WMO todas as estações automáticas de SC extraídas."""
    root = Path(root_dir)
    grouped: dict[str, list[Path]] = {}
    meta_by_id: dict[str, dict[str, Any]] = {}
    for yr in years:
        yr_dir = root / str(yr)
        if not yr_dir.is_dir():
            continue
        for csv_path in sorted(yr_dir.glob("*.CSV")) + sorted(yr_dir.glob("*.csv")):
            hdr = parse_inmet_csv_header(csv_path)
            sid = hdr["station_id"]
            if not sid or hdr["uf"] != "SC":
                continue
            grouped.setdefault(sid, []).append(csv_path)
            if sid not in meta_by_id or (meta_by_id[sid]["elevation_m"] is None and hdr["elevation_m"] is not None):
                meta_by_id[sid] = hdr

    out: list[InmetStationInfo] = []
    for sid in sorted(grouped):
        m = meta_by_id[sid]
        if m["lat"] is None or m["lon"] is None:
            continue
        out.append(
            InmetStationInfo(
                station_id=sid,
                station_name=m["station_name"],
                municipality_key=m["municipality_key"],
                uf=m["uf"],
                lat=float(m["lat"]),
                lon=float(m["lon"]),
                elevation_m=m["elevation_m"],
                csv_paths=tuple(sorted(set(grouped[sid]))),
            )
        )
    return out


def fetch_ibge_pam_sc_producers(
    year: int = 2025,
    cache_path: str | Path | None = None,
    session: requests.Session | None = None,
) -> dict[str, dict[str, float]]:
    """
    Retorna `{MUNICIPIO_NORMALIZADO: {"maca_ha": float, "tomate_ha": float, "uva_ha": float}}`
    para todos os municípios de Santa Catarina com base na tabela SIDRA 5457 (var 216, Área colhida).
    """
    cp = Path(cache_path) if cache_path is not None else None
    if cp is not None and cp.is_file():
        payload = json.loads(cp.read_text(encoding="utf-8"))
    else:
        sess = session or requests.Session()
        url = IBGE_SIDRA_PAM_SC_URL.format(year=year)
        resp = sess.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if cp is not None:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    return parse_ibge_pam_sc_payload(payload, year=year)


def parse_ibge_pam_sc_payload(payload: Any, year: int = 2025) -> dict[str, dict[str, float]]:
    """Converte o JSON da API SIDRA 5457 em mapa por município normalizado."""
    crop_key_map = {
        "40260": "maca_ha",
        "40126": "tomate_ha",
        "40274": "uva_ha",
    }
    yr_str = str(year)
    out: dict[str, dict[str, float]] = {}
    for res in payload[0]["resultados"]:
        cat_dict = res["classificacoes"][0]["categoria"]
        cat_id = next(iter(cat_dict.keys()))
        field = crop_key_map.get(str(cat_id))
        if field is None:
            continue
        for s in res["series"]:
            muni_norm = normalize_br_name(s["localidade"]["nome"])
            raw_val = str(s["serie"].get(yr_str, "")).strip()
            val = 0.0
            if raw_val not in ("", "-", "..", "...", "X"):
                try:
                    val = float(raw_val.replace(",", "."))
                except ValueError:
                    val = 0.0
            entry = out.setdefault(muni_norm, {"maca_ha": 0.0, "tomate_ha": 0.0, "uva_ha": 0.0})
            entry[field] = val
    return out


def is_producing_municipality(pam_row: Mapping[str, float] | None) -> bool:
    """Regra congelada em `v2-freeze-br`: área colhida > 0 ha em maçã, uva ou tomate."""
    if not pam_row:
        return False
    return any(float(pam_row.get(k, 0.0)) > 0.0 for k in ("maca_ha", "tomate_ha", "uva_ha"))


def download_inmet_sc_zips(
    out_dir: str | Path,
    years: Sequence[int] = (2022, 2023, 2024, 2025),
    session: requests.Session | None = None,
) -> dict[int, int]:
    """Baixa os ZIPs anuais do INMET e extrai somente os CSVs de SC (`INMET_S_SC_*`)."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", "vitirule-v2-research/2.0 (non-commercial)")
    counts: dict[int, int] = {}
    for yr in years:
        yr_dir = root / str(yr)
        existing = list(yr_dir.glob("*.CSV")) + list(yr_dir.glob("*.csv")) if yr_dir.is_dir() else []
        if existing:
            counts[yr] = len(existing)
            continue
        url = INMET_HIST_ZIP_URL.format(year=yr)
        resp = sess.get(url, timeout=180)
        resp.raise_for_status()
        yr_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for info in zf.infolist():
                name = Path(info.filename).name
                if name.upper().startswith("INMET_S_SC_") and name.upper().endswith(".CSV"):
                    (yr_dir / name).write_bytes(zf.read(info))
                    n += 1
        counts[yr] = n
    return counts
