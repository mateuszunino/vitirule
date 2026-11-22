"""
Testes unitarios do pacote `vitirule_v2`.

Politica de oraculos (docs/v2/implementacoes.md):
- Todos os testes principais usam exclusivamente as tabelas e definicoes
  publicadas nas fontes primarias:
  * Baldacci (1947) / Goidanich (1964) para Regra 3-10
  * Muller & Sleumer (1934) / Goidanich (1964) para incubacao de Goidanich
  * MacHardy & Gadoury (1989) + Stensvand et al. (1997) + OMAFRA para Mills
  * Madden et al. (1978) / Pitblado (1992) / Gillespie et al. (1993) para TOM-CAST
- A conferencia cruzada com os modulos congelados da v1 vive apenas na classe
  separada `TestV1Consistency`, marcada explicitamente como conferencia de
  consistencia e nao como oraculo.
"""
from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from vitirule_v2.qc import draw_stratified_lockbox, evaluate_station_season_qc
from vitirule_v2.rules import (
    HourlyRecord,
    TomcastDay,
    compute_tomcast_daily,
    detect_mills_infections,
    detect_rule_3_10,
    get_phenology_window,
    goidanich_daily_progress_pct,
    in_phenology_window,
    load_params,
    mills_lookup,
    round_half_up,
    season_label_for_date,
    simulate_tomcast_sprays,
    tomcast_dsv_lookup,
    track_goidanich_incubation,
)

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _make_hourly_days(
    start_date: date,
    n_days: int,
    temp_c: float = 20.0,
    rh_pct: float = 80.0,
    precip_by_day: dict[int, float] | None = None,
    wet_hours_per_day: int = 0,
    tz_name: str = "UTC",
) -> list[HourlyRecord]:
    """Gera serie horaria sintetica deterministica em `tz_name`."""
    tz = ZoneInfo(tz_name)
    precip_by_day = precip_by_day or {}
    out: list[HourlyRecord] = []
    for d_idx in range(n_days):
        cur_d = start_date + timedelta(days=d_idx)
        day_rain = precip_by_day.get(d_idx, 0.0)
        for hr in range(24):
            local_dt = datetime(cur_d.year, cur_d.month, cur_d.day, hr, 0, tzinfo=tz)
            out.append(
                HourlyRecord(
                    ts=local_dt.astimezone(UTC),
                    temp_c=temp_c,
                    rh_pct=rh_pct,
                    precip_mm=day_rain if hr == 6 else 0.0,
                    wet=(hr < wet_hours_per_day),
                )
            )
    return out


# ==========================================================================
# 1. Isolamento do pacote v2 e integridade de params.json
# ==========================================================================
class TestPackageIsolationAndParams:
    def test_v2_rules_only_uses_stdlib(self):
        """Pacote `vitirule_v2/rules` nao importa modulos da v1 nem libs pesadas (Pyodide-ready)."""
        forbidden = {
            "downy_mildew",
            "epidemiology_assimilation",
            "leaf_wetness",
            "lwd_sensor_validation",
            "osse_benchmark",
            "simulator",
            "weather_collector",
            "numpy",
            "pandas",
            "scipy",
            "requests",
        }
        rules_dir = ROOT / "vitirule_v2" / "rules"
        for py_file in rules_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        assert top not in forbidden, f"{py_file.name} importa {top}"
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    top = node.module.split(".")[0]
                    assert top not in forbidden, f"{py_file.name} importa {top}"

    def test_params_json_has_bibliographic_sources_and_divergences(self):
        params = load_params()
        for rule_key in ("rule_3_10", "goidanich", "mills_revised", "tomcast"):
            cfg = params[rule_key]
            assert cfg["primary_reference"], f"{rule_key} sem referencia primaria"
            assert cfg["literature_divergences"], f"{rule_key} sem divergencias documentadas"
            for div in cfg["literature_divergences"]:
                assert div["parameter"]
                assert len(div["variants"]) >= 2
                assert div["rationale"]

    def test_round_half_up_boundaries(self):
        assert round_half_up(17.49) == 17
        assert round_half_up(17.5) == 18
        assert round_half_up(20.5) == 21
        assert round_half_up(25.5) == 26
        assert round_half_up(0.0) == 0


# ==========================================================================
# 2. Janelas fenologicas fixas
# ==========================================================================
class TestPhenologyWindows:
    def test_northern_hemisphere_bounds(self):
        assert not in_phenology_window(date(2022, 3, 31), "grapevine", "northern_hemisphere")
        assert in_phenology_window(date(2022, 4, 1), "grapevine", "northern_hemisphere")
        assert in_phenology_window(date(2022, 9, 30), "grapevine", "northern_hemisphere")
        assert not in_phenology_window(date(2022, 10, 1), "grapevine", "northern_hemisphere")

        assert not in_phenology_window(date(2022, 3, 14), "apple", "northern_hemisphere")
        assert in_phenology_window(date(2022, 3, 15), "apple", "northern_hemisphere")
        assert in_phenology_window(date(2022, 6, 30), "apple", "northern_hemisphere")
        assert not in_phenology_window(date(2022, 7, 1), "apple", "northern_hemisphere")

        assert not in_phenology_window(date(2022, 4, 30), "tomato", "northern_hemisphere")
        assert in_phenology_window(date(2022, 5, 1), "tomato", "northern_hemisphere")
        assert in_phenology_window(date(2022, 9, 30), "tomato", "northern_hemisphere")

    def test_southern_hemisphere_cross_year_season_label(self):
        win = get_phenology_window("grapevine", "southern_hemisphere")
        assert win.cross_year is True
        assert season_label_for_date(date(2024, 10, 1), "grapevine", "southern_hemisphere") == "2024-2025"
        assert season_label_for_date(date(2025, 3, 31), "grapevine", "southern_hemisphere") == "2024-2025"
        assert season_label_for_date(date(2025, 4, 1), "grapevine", "southern_hemisphere") is None


# ==========================================================================
# 3. Oraculo primario: Regra 3-10 (Baldacci 1947) e Goidanich (1934/1964)
# ==========================================================================
class TestDownyMildewPrimaryOracle:
    def test_rule_3_10_triggers_on_48h_rain_and_debounces_dry_next_day(self):
        # Dia 0: 6 mm, Dia 1: 5 mm (soma 48h = 11 mm >= 10 mm -> dispara no Dia 1)
        # Dia 2: 0 mm (soma 48h = 5 mm -> nao dispara)
        # Dia 5: 12 mm (dispara no Dia 5), Dia 6: 0 mm (soma 48h = 12 mm, mas sem chuva ativa -> NAO dispara)
        records = _make_hourly_days(
            start_date=date(2023, 5, 1),
            n_days=8,
            temp_c=14.0,
            precip_by_day={0: 6.0, 1: 5.0, 5: 12.0},
        )
        events = detect_rule_3_10(records, tz_name="UTC")
        assert [ev.trigger_date for ev in events] == [date(2023, 5, 2), date(2023, 5, 6)]
        assert events[0].is_first_of_season is True
        assert events[1].is_first_of_season is False
        assert events[0].rain_48h_mm == pytest.approx(11.0)

    def test_rule_3_10_rejects_cold_or_out_of_phenology_or_insufficient_rain(self):
        # Frio (9.9 C) -> nao dispara
        cold = _make_hourly_days(date(2023, 5, 1), 3, temp_c=9.9, precip_by_day={1: 15.0})
        assert detect_rule_3_10(cold, tz_name="UTC") == []

        # Fora da janela fenologica (marco) -> nao dispara
        early = _make_hourly_days(date(2023, 3, 20), 3, temp_c=15.0, precip_by_day={1: 15.0})
        assert detect_rule_3_10(early, tz_name="UTC") == []

        # Chuva insuficiente (9.9 mm) -> nao dispara
        light_rain = _make_hourly_days(date(2023, 5, 1), 3, temp_c=15.0, precip_by_day={1: 9.9})
        assert detect_rule_3_10(light_rain, tz_name="UTC") == []

    def test_rule_3_10_debounces_multi_day_storm_to_onset_day(self):
        records = _make_hourly_days(
            date(2023, 5, 10),
            5,
            temp_c=16.0,
            precip_by_day={1: 12.0, 2: 14.0, 3: 11.0},
        )
        events = detect_rule_3_10(records, tz_name="UTC")
        assert len(events) == 1
        assert events[0].trigger_date == date(2023, 5, 11)

    @pytest.mark.parametrize(
        "temp_c,rh_pct,expected_pct",
        [
            (8.0, 80.0, 0.0),
            (10.0, 80.0, 5.0),
            (12.0, 80.0, 7.7),
            (14.0, 80.0, 10.0),
            (16.0, 80.0, 13.3),
            (18.0, 80.0, 16.7),
            (20.0, 80.0, 20.0),
            (22.0, 80.0, 25.0),
            (25.0, 80.0, 25.0),
            (28.0, 80.0, 16.7),
            (30.0, 80.0, 0.0),
            # Ajuste de umidade baixa (< 75%) de Goidanich (1964)
            (22.0, 65.0, 21.25),
        ],
    )
    def test_goidanich_published_anchor_table(self, temp_c, rh_pct, expected_pct):
        assert goidanich_daily_progress_pct(temp_c, rh_pct) == pytest.approx(expected_pct, abs=1e-3)

    def test_goidanich_incubation_duration_at_22c_and_12c(self):
        # A 22 C e UR 80%: 25%/dia -> 4 dias exatos apos o gatilho
        warm = _make_hourly_days(date(2023, 6, 1), 10, temp_c=22.0, rh_pct=80.0, precip_by_day={0: 15.0})
        cohorts_warm = track_goidanich_incubation(warm, tz_name="UTC")
        assert len(cohorts_warm) == 1
        assert cohorts_warm[0].completed is True
        assert cohorts_warm[0].duration_days == 4
        assert cohorts_warm[0].completion_date == date(2023, 6, 5)
        assert cohorts_warm[0].preventive_80_date == date(2023, 6, 5)  # 75% no dia 3, 100% no dia 4

        # A 12 C e UR 80%: 7.7%/dia -> 13 dias (13 * 7.7 = 100.1%)
        cool = _make_hourly_days(date(2023, 4, 10), 20, temp_c=12.0, rh_pct=80.0, precip_by_day={0: 15.0})
        cohorts_cool = track_goidanich_incubation(cool, tz_name="UTC")
        assert len(cohorts_cool) == 1
        assert cohorts_cool[0].completed is True
        assert cohorts_cool[0].duration_days == 13


# ==========================================================================
# 4. Oraculo primario: Tabela de Mills revisada (MacHardy & Gadoury 1989;
#    Stensvand et al. 1997; OMAFRA)
# ==========================================================================
class TestMillsRevisedPrimaryOracle:
    @pytest.mark.parametrize(
        "temp_c,light_h,mod_h,heavy_h",
        [
            (1.0, 40, 69, 93),
            (2.0, 34, 69, 93),
            (3.0, 30, 52, 65),
            (4.0, 27, 42, 57),
            (5.0, 21, 34, 50),
            (6.0, 18, 27, 44),
            (7.0, 15, 23, 37),
            (8.0, 13, 21, 34),
            (9.0, 12, 17, 27),
            (10.0, 11, 16, 26),
            (11.0, 9, 14, 22),
            (12.0, 8, 12, 20),
            (13.0, 8, 12, 20),
            (14.0, 7, 11, 19),
            (15.0, 7, 11, 19),
            (15.5, 6.5, 10, 17),
            (16.0, 6, 9, 16),
            (20.0, 6, 9, 16),
            (24.0, 6, 9, 16),
            (25.0, 8, 11, 18),
            (26.0, 10, 14, 23),
        ],
    )
    def test_exact_published_mills_table_rows(self, temp_c, light_h, mod_h, heavy_h):
        assert mills_lookup(temp_c, light_h - 0.1) is None
        assert mills_lookup(temp_c, light_h) == "light"
        assert mills_lookup(temp_c, mod_h - 0.1) == "light"
        assert mills_lookup(temp_c, mod_h) == "moderate"
        assert mills_lookup(temp_c, heavy_h - 0.1) == "moderate"
        assert mills_lookup(temp_c, heavy_h) == "heavy"

    def test_mills_out_of_temperature_range_returns_none(self):
        assert mills_lookup(0.5, 50.0) is None
        assert mills_lookup(26.5, 50.0) is None

    def test_mills_combines_wet_periods_with_8h_dry_gap_and_splits_at_9h(self):
        t0 = datetime(2023, 4, 15, 0, 0, tzinfo=UTC)

        # Caso A: 4 h molhadas + 8 h secas + 3 h molhadas a 18 C = 7 h molhadas >= 6 h (light)
        recs_combine: list[HourlyRecord] = []
        for h in range(15):
            wet = (h < 4) or (h >= 12)
            rain = 1.0 if h == 0 else 0.0
            recs_combine.append(HourlyRecord(ts=t0 + timedelta(hours=h), temp_c=18.0, rh_pct=85.0, precip_mm=rain, wet=wet))
        evs_combine = detect_mills_infections(recs_combine, tz_name="UTC")
        assert len(evs_combine) == 1
        assert evs_combine[0].max_severity == "light"
        assert evs_combine[0].wet_hours == 7
        assert evs_combine[0].light_ts == t0 + timedelta(hours=13)  # 6a hora molhada

        # Caso B: 4 h molhadas + 9 h secas + 4 h molhadas a 18 C -> separa em dois eventos de 4 h (< 6 h)
        recs_split: list[HourlyRecord] = []
        for h in range(17):
            wet = (h < 4) or (h >= 13)
            rain = 1.0 if h in (0, 13) else 0.0
            recs_split.append(HourlyRecord(ts=t0 + timedelta(hours=h), temp_c=18.0, rh_pct=85.0, precip_mm=rain, wet=wet))
        assert detect_mills_infections(recs_split, tz_name="UTC") == []

    def test_mills_requires_rain_for_primary_ascospore_infection(self):
        t0 = datetime(2023, 5, 1, 0, 0, tzinfo=UTC)
        # Orvalho puro por 12 h a 18 C sem chuva -> NAO dispara infeccao primaria
        dew_only = [
            HourlyRecord(ts=t0 + timedelta(hours=h), temp_c=18.0, rh_pct=96.0, precip_mm=0.0, wet=True)
            for h in range(12)
        ]
        assert detect_mills_infections(dew_only, tz_name="UTC") == []

        # 4 h de orvalho antes da chuva + chuva na h4 + 5 h molhadas (h4..h8 = 5 h < 6 h) -> NAO conta orvalho previo
        pre_dew = [
            HourlyRecord(ts=t0 + timedelta(hours=h), temp_c=18.0, rh_pct=95.0, precip_mm=(1.0 if h == 4 else 0.0), wet=True)
            for h in range(9)
        ]
        assert detect_mills_infections(pre_dew, tz_name="UTC") == []

        # Adicionando h9 (6 h apos inicio da chuva) -> dispara light em h9
        pre_dew.append(HourlyRecord(ts=t0 + timedelta(hours=9), temp_c=18.0, rh_pct=95.0, precip_mm=0.0, wet=True))
        evs = detect_mills_infections(pre_dew, tz_name="UTC")
        assert len(evs) == 1
        assert evs[0].onset_ts == t0 + timedelta(hours=4)
        assert evs[0].light_ts == t0 + timedelta(hours=9)


# ==========================================================================
# 5. Oraculo primario: TOM-CAST (Madden et al. 1978; Pitblado 1992;
#    Gillespie et al. 1993)
# ==========================================================================
class TestTomcastPrimaryOracle:
    @pytest.mark.parametrize(
        "temp_c,wet_h,expected_dsv",
        [
            # Fora de faixa
            (12.0, 24, 0),
            (30.0, 24, 0),
            (22.0, 0, 0),
            # 13-17 C: 0=0-6, 1=7-15, 2=16-20, 3=21+, 4=N/A
            (13.0, 6, 0),
            (13.0, 7, 1),
            (17.0, 15, 1),
            (17.0, 16, 2),
            (17.0, 20, 2),
            (17.0, 21, 3),
            (17.0, 24, 3),
            # 18-20 C: 0=0-3, 1=4-8, 2=9-15, 3=16-22, 4=23+
            (18.0, 3, 0),
            (18.0, 4, 1),
            (20.0, 8, 1),
            (20.0, 9, 2),
            (20.0, 15, 2),
            (20.0, 16, 3),
            (20.0, 22, 3),
            (20.0, 23, 4),
            # 21-25 C: 0=0-2, 1=3-5, 2=6-12, 3=13-20, 4=21+
            (21.0, 2, 0),
            (21.0, 3, 1),
            (25.0, 5, 1),
            (25.0, 6, 2),
            (25.0, 12, 2),
            (25.0, 13, 3),
            (25.0, 20, 3),
            (25.0, 21, 4),
            # 26-29 C: 0=0-3, 1=4-8, 2=9-15, 3=16-22, 4=23+
            (26.0, 3, 0),
            (26.0, 4, 1),
            (29.0, 9, 2),
            (29.0, 16, 3),
            (29.0, 23, 4),
            # Fronteira half-up: 17.5 -> 18 C (4h = DSV 1 em 18-20 C, mas 0 em 13-17 C)
            (17.5, 4, 1),
        ],
    )
    def test_exact_published_tomcast_dsv_matrix(self, temp_c, wet_h, expected_dsv):
        assert tomcast_dsv_lookup(temp_c, wet_h) == expected_dsv

    def test_tomcast_noon_to_noon_keeps_nocturnal_dew_together(self):
        # 6 h molhadas de 21h do dia 10/06 as 02h do dia 11/06 a 22 C -> 1 dia com 6 h (DSV=2)
        tz = ZoneInfo("Europe/Paris")
        recs: list[HourlyRecord] = []
        base = datetime(2023, 6, 10, 12, 0, tzinfo=tz)
        for h in range(24):
            dt = base + timedelta(hours=h)
            wet = 9 <= h <= 14  # 21:00 a 02:00 locais
            recs.append(HourlyRecord(ts=dt.astimezone(UTC), temp_c=22.0, rh_pct=90.0, precip_mm=0.0, wet=wet))
        days = compute_tomcast_daily(recs, tz_name="Europe/Paris")
        assert len(days) == 1
        assert days[0].day == date(2023, 6, 10)
        assert days[0].wet_hours == 6
        assert days[0].dsv == 2

    def test_tomcast_both_memory_modes_self_reset_and_reference_reset(self):
        # Referencia: 3 DSV/dia -> pulveriza nos dias 5 (cum=15) e 10 (cum=15)
        # Candidata: 4 DSV/dia nos dias 1..4 (antecipa no dia 4), depois 2 DSV/dia nos dias 5..10 (perde o dia 10)
        ref_days = [
            TomcastDay(date(2023, 6, i), "2023", 13, 22.0, 22, 3)
            for i in range(1, 11)
        ]
        cand_dsvs = [4, 4, 4, 4, 2, 2, 2, 2, 2, 2]
        cand_days = [
            TomcastDay(date(2023, 6, i + 1), "2023", 10, 22.0, 22, dsv)
            for i, dsv in enumerate(cand_dsvs)
        ]

        ref_sprays = simulate_tomcast_sprays(ref_days, threshold=15, mode="self_reset")
        assert [s.trigger_date for s in ref_sprays] == [date(2023, 6, 5), date(2023, 6, 10)]

        # Modo 1: self_reset (autonomo)
        cand_self = simulate_tomcast_sprays(cand_days, threshold=15, mode="self_reset")
        assert [s.trigger_date for s in cand_self] == [date(2023, 6, 4)]

        # Modo 2: reference_reset (sincronizado nas datas da referencia)
        cand_sync = simulate_tomcast_sprays(
            cand_days,
            threshold=15,
            mode="reference_reset",
            reference_spray_dates=[s.trigger_date for s in ref_sprays],
        )
        assert len(cand_sync) == 2
        # Intervalo 1 (ate 05/06): candidata atingiu 16 DSV em 04/06 (lead = -1 dia)
        assert cand_sync[0].reached_by_ref_date is True
        assert cand_sync[0].candidate_trigger_date == date(2023, 6, 4)
        assert cand_sync[0].lead_days == -1
        # Intervalo 2 (06/06 a 10/06): candidata somou apenas 10 DSV -> nao atingiu 15
        assert cand_sync[1].reached_by_ref_date is False
        assert cand_sync[1].candidate_dsv_at_ref == 10
        assert cand_sync[1].lead_days is None


# ==========================================================================
# 6. Controle de qualidade cego e sorteio de lockbox
# ==========================================================================
class TestBlindQualityControlAndLockbox:
    def _clean_season(self, start_d: date, end_d: date) -> list[HourlyRecord]:
        n_days = (end_d - start_d).days + 1
        out: list[HourlyRecord] = []
        for d_idx in range(n_days):
            cur = start_d + timedelta(days=d_idx)
            for hr in range(24):
                ts = datetime(cur.year, cur.month, cur.day, hr, 0, tzinfo=UTC)
                # Orvalho noturno (0h-5h) com UR alta, tarde seca (11h-16h) com folha seca
                is_night = hr < 6
                out.append(
                    HourlyRecord(
                        ts=ts,
                        temp_c=18.0 if is_night else 24.0,
                        rh_pct=92.0 if is_night else 50.0,
                        precip_mm=2.0 if (d_idx % 7 == 0 and hr == 2) else 0.0,
                        wet=is_night,
                    )
                )
        return out

    def test_qc_passes_clean_season(self):
        recs = self._clean_season(date(2023, 5, 1), date(2023, 9, 30))
        res = evaluate_station_season_qc(recs, "synthetic", "ST01", "tomato", 2023, "UTC")
        assert res.passed is True
        assert res.reasons == ()
        assert res.coverage_frac == 1.0
        assert res.max_gap_hours == 0

    def test_qc_rejects_drifting_sensor_on_dry_midday_and_high_wet_fraction(self):
        recs = self._clean_season(date(2023, 5, 1), date(2023, 9, 30))
        # Simula sensor travado em molhado 99% do tempo (como um sensor com deriva severa)
        stuck = [HourlyRecord(r.ts, r.temp_c, r.rh_pct, r.precip_mm, wet=True) for r in recs]
        res = evaluate_station_season_qc(stuck, "synthetic", "ST_DRIFT", "tomato", 2023, "UTC")
        assert res.passed is False
        assert "wet_fraction_above_0.80" in res.reasons
        assert "dry_midday_wet_above_0.15" in res.reasons
        assert "rainless_wet_streak_gt_96h" in res.reasons

    def test_qc_rejects_disconnected_sensor_and_large_gap(self):
        recs = self._clean_season(date(2023, 5, 1), date(2023, 9, 30))
        # Sensor desconectado (0% molhado)
        dry = [HourlyRecord(r.ts, r.temp_c, r.rh_pct, r.precip_mm, wet=False) for r in recs]
        res_dry = evaluate_station_season_qc(dry, "synthetic", "ST_OFF", "tomato", 2023, "UTC")
        assert res_dry.passed is False
        assert "wet_fraction_below_0.01" in res_dry.reasons

        # Lacuna de 30 horas consecutivas (> 24 h) na politica de sensibilidade original `reject_24h`
        gapped = recs[:100] + recs[130:]
        res_gap = evaluate_station_season_qc(
            gapped, "synthetic", "ST_GAP", "tomato", 2023, "UTC", gap_policy="reject_24h"
        )
        assert res_gap.passed is False
        assert "max_gap_gt_24h" in res_gap.reasons
        assert res_gap.max_gap_hours == 30

    def test_stratified_lockbox_excludes_v1_and_is_deterministic(self):
        pool = [
            {"station_id": "33080002", "region": "A"},  # v1 -> deve ser excluida
            {"station_id": "68066002", "region": "B"},  # v1 -> deve ser excluida
        ] + [
            {"station_id": f"NEW_{i:02d}", "region": ("A" if i < 10 else "B")}
            for i in range(20)
        ]
        draw1 = draw_stratified_lockbox(pool, fraction=0.20, min_count=2, seed=20261122)
        draw2 = draw_stratified_lockbox(pool, fraction=0.20, min_count=2, seed=20261122)
        assert draw1 == draw2
        assert len(draw1) == 4  # 20% de 20 novas
        assert "33080002" not in draw1
        assert "68066002" not in draw1
        # Estratificacao: 2 da regiao A e 2 da regiao B
        n_a = sum(int(sid.split("_")[1]) < 10 for sid in draw1)
        n_b = sum(int(sid.split("_")[1]) >= 10 for sid in draw1)
        assert (n_a, n_b) == (2, 2)


# ==========================================================================
# 7. Conferencia de consistencia com a v1 (NAO e oraculo de teste)
# ==========================================================================
class TestV1Consistency:
    """
    Conferencia de consistencia separada contra os modulos congelados da v1.
    Nao serve como oraculo de correcao; serve apenas para documentar onde a v2
    coincide com a v1 e onde diverge intencionalmente (ex.: arredondamento half-up).
    """

    def test_goidanich_matches_v1_interpolation_points(self):
        import downy_mildew as dm_v1

        for temp_c in (8.0, 10.0, 12.0, 15.0, 18.0, 22.0, 25.0, 28.0, 30.0):
            for rh_pct in (60.0, 85.0):
                assert goidanich_daily_progress_pct(temp_c, rh_pct) == pytest.approx(
                    dm_v1.goidanich_daily_incubation_pct(temp_c, rh_pct),
                    abs=1e-2,
                )

    def test_tomcast_matches_v1_lookup_on_integer_temperatures(self):
        import epidemiology_assimilation as ea_v1

        for temp_c in range(10, 33):
            for wet_h in (0, 2, 3, 4, 6, 7, 9, 13, 16, 21, 23):
                v1_val = ea_v1._lookup(ea_v1.TOMCAST_TABLE, temp_c, wet_h) if wet_h > 0 else 0
                assert tomcast_dsv_lookup(float(temp_c), wet_h) == v1_val
