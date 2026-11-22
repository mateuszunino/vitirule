"""
Testes unitarios da Fase 4 (transferencia brasileira INMET SC):
- Leitor de CSV oficial do INMET em UTC (virgula decimal, radiacao Kj/m2 -> W/m2,
  sentinelas -9999/vazio e wet=None)
- Filtro objetivo de municipios produtores via IBGE PAM (SIDRA 5457)
- Controle de qualidade cego no Hemisferio Sul sem sensor de LWD (`require_lwd_sensor=False`)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from vitirule_v2.qc import evaluate_station_season_qc
from vitirule_v2.rules.common import HourlyRecord
from vitirule_v2.sources.inmet import (
    is_producing_municipality,
    normalize_br_name,
    parse_ibge_pam_sc_payload,
    parse_inmet_csv_header,
    parse_inmet_csv_records,
)

UTC = timezone.utc

SAMPLE_INMET_CSV = """\
REGIAO:;S
UF:;SC
ESTACAO:;SAO JOAQUIM
CODIGO (WMO):;A815
LATITUDE:;-28,27555555
LONGITUDE:;-49,93444444
ALTITUDE:;1415,0
DATA DE FUNDACAO:;26/09/06
Data;Hora UTC;PRECIPITACAO TOTAL, HORARIO (mm);PRESSAO ATMOSFERICA AO NIVEL DA ESTACAO, HORARIA (mB);PRESSAO ATMOSFERICA MAX.NA HORA ANT. (AUT) (mB);PRESSAO ATMOSFERICA MIN. NA HORA ANT. (AUT) (mB);RADIACAO GLOBAL (Kj/m²);TEMPERATURA DO AR - BULBO SECO, HORARIA (°C);TEMPERATURA DO PONTO DE ORVALHO (°C);TEMPERATURA MAXIMA NA HORA ANT. (AUT) (°C);TEMPERATURA MINIMA NA HORA ANT. (AUT) (°C);TEMPERATURA ORVALHO MAX. NA HORA ANT. (AUT) (°C);TEMPERATURA ORVALHO MIN. NA HORA ANT. (AUT) (°C);UMIDADE REL. MAX. NA HORA ANT. (AUT) (%);UMIDADE REL. MIN. NA HORA ANT. (AUT) (%);UMIDADE RELATIVA DO AR, HORARIA (%);VENTO, DIRECAO HORARIA (gr) (° (gr));VENTO, RAJADA MAXIMA (m/s);VENTO, VELOCIDADE HORARIA (m/s);
2022/10/01;0000 UTC;0,4;860,1;860,2;860,0;0;12,5;11,8;13,0;12,1;12,0;11,5;96;94;95;180;4,5;2,1;
2022/10/01;0100 UTC;0;860,0;860,1;859,9;360,0;11,0;10,2;12,5;10,8;11,8;10,0;95;92;93;190;3,8;1,5;
2022/10/01;0200 UTC;-9999;860,0;860,0;860,0;;-9999;10,0;11,0;10,0;10,0;10,0;92;90;;190;3,0;;
"""


def test_parse_inmet_csv_header_and_records_utc(tmp_path: Path):
    p = tmp_path / "INMET_S_SC_A815_SAO JOAQUIM_2022.CSV"
    p.write_text(SAMPLE_INMET_CSV, encoding="latin-1")

    hdr = parse_inmet_csv_header(p)
    assert hdr["station_id"] == "A815"
    assert hdr["uf"] == "SC"
    assert hdr["municipality_key"] == "SAO JOAQUIM"
    assert hdr["lat"] == pytest.approx(-28.27555555)
    assert hdr["lon"] == pytest.approx(-49.93444444)
    assert hdr["elevation_m"] == pytest.approx(1415.0)

    recs = parse_inmet_csv_records(p)
    assert len(recs) == 3
    assert recs[0].ts == datetime(2022, 10, 1, 0, 0, tzinfo=UTC)
    assert recs[0].precip_mm == pytest.approx(0.4)
    assert recs[0].temp_c == pytest.approx(12.5)
    assert recs[0].rh_pct == pytest.approx(95.0)
    assert recs[0].wind_ms == pytest.approx(2.1)
    assert recs[0].wet is None

    assert recs[1].ts == datetime(2022, 10, 1, 1, 0, tzinfo=UTC)
    assert recs[1].rad_wm2 == pytest.approx(100.0)  # 360 Kj/m2 / 3.6 = 100 W/m2

    # Sentinela -9999 e celulas vazias viram None
    assert recs[2].precip_mm is None
    assert recs[2].temp_c is None
    assert recs[2].rh_pct is None
    assert recs[2].rad_wm2 is None


def test_ibge_pam_parser_and_producer_filter():
    payload = [
        {
            "resultados": [
                {
                    "classificacoes": [{"categoria": {"40260": "Maçã"}}],
                    "series": [
                        {"localidade": {"nome": "São Joaquim - SC"}, "serie": {"2025": "11500"}},
                        {"localidade": {"nome": "Itajaí - SC"}, "serie": {"2025": "-"}},
                    ],
                },
                {
                    "classificacoes": [{"categoria": {"40126": "Tomate"}}],
                    "series": [
                        {"localidade": {"nome": "São Joaquim - SC"}, "serie": {"2025": "0"}},
                        {"localidade": {"nome": "Itajaí - SC"}, "serie": {"2025": "-"}},
                    ],
                },
                {
                    "classificacoes": [{"categoria": {"40274": "Uva"}}],
                    "series": [
                        {"localidade": {"nome": "São Joaquim - SC"}, "serie": {"2025": "350"}},
                        {"localidade": {"nome": "Itajaí - SC"}, "serie": {"2025": "-"}},
                    ],
                },
            ]
        }
    ]
    pam = parse_ibge_pam_sc_payload(payload, year=2025)
    assert normalize_br_name("São Joaquim - SC") == "SAO JOAQUIM"
    assert pam["SAO JOAQUIM"]["maca_ha"] == 11500.0
    assert pam["SAO JOAQUIM"]["uva_ha"] == 350.0
    assert is_producing_municipality(pam["SAO JOAQUIM"]) is True
    assert is_producing_municipality(pam["ITAJAI"]) is False


def test_southern_hemisphere_qc_without_lwd_sensor():
    # Janela da macieira no Hemisferio Sul: 15 set a 31 dez (108 dias = 2592 h)
    start_utc = datetime(2022, 9, 15, 0, 0, tzinfo=UTC)
    recs: list[HourlyRecord] = []
    for h in range(112 * 24):
        ts = start_utc + timedelta(hours=h)
        recs.append(HourlyRecord(ts=ts, temp_c=16.0, rh_pct=80.0, precip_mm=0.0, wet=None))

    res_no_lwd = evaluate_station_season_qc(
        recs,
        network="inmet",
        station_id="A815",
        crop="apple",
        season_year=2022,
        tz_name="America/Sao_Paulo",
        hemisphere="southern_hemisphere",
        require_lwd_sensor=False,
    )
    assert res_no_lwd.passed is True
    assert res_no_lwd.coverage_frac == pytest.approx(1.0)
    assert res_no_lwd.wet_fraction is None

    # Com require_lwd_sensor=True (padrao), wet=None reprova por cobertura zero
    res_with_lwd = evaluate_station_season_qc(
        recs,
        network="inmet",
        station_id="A815",
        crop="apple",
        season_year=2022,
        tz_name="America/Sao_Paulo",
        hemisphere="southern_hemisphere",
        require_lwd_sensor=True,
    )
    assert res_with_lwd.passed is False
