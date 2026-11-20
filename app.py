#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py
======
API Flask do DSS de doenças foliares do tomateiro (contrato seção 5.5 do SKILL.md).

Regras de operação:
* Uma única instância de `VisionPipeline` por processo, protegida por
  `threading.Lock` (GPU GTX 1660 Super de 6 GB).
* Todo acesso ao banco passa por `db.py` (psycopg2, sem ORM).
* Erros sempre em JSON no formato `{"error": {"code": "...", "message": "..."}}`.
* Vídeos são salvos em `data/videos/AAAA-MM-DD/` antes do processamento e nunca
  são sobrescritos nem apagados.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, jsonify, request

import db
import decision_engine as de
import epidemiology_assimilation as ea
import vision_pipeline as vp

load_dotenv()

log = logging.getLogger("app")

UTC = timezone.utc
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def _error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _check_gpu() -> bool:
    try:
        import torch  # type: ignore
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _check_weights(cfg: vp.PipelineConfig) -> bool:
    return bool(
        cfg.weights_a and Path(cfg.weights_a).is_file()
        and cfg.weights_b and Path(cfg.weights_b).is_file()
    )


def create_app(
    db_conn_factory: Optional[Callable[[], Any]] = None,
    vision_pipeline: Optional[vp.VisionPipeline] = None,
    vision_config: Optional[vp.PipelineConfig] = None,
    data_dir: str | Path = "data",
    station_id: Optional[str] = None,
    transplant_date: Optional[str] = None,
) -> Flask:
    """Fábrica da aplicação Flask com injeção de dependências para testes e produção."""
    app = Flask(__name__)

    conn_factory = db_conn_factory or db.get_connection
    v_cfg = vision_config or vp.PipelineConfig()
    if os.environ.get("VISION_HALF") == "0":
        v_cfg.half = "off"
    pipeline = vision_pipeline or vp.VisionPipeline(v_cfg)
    vision_lock = threading.Lock()

    base_data = Path(data_dir)
    videos_root = base_data / "videos"
    debug_root = base_data / "debug"
    st_id = station_id or os.environ.get("STATION_ID", "sj_vasos")
    tp_date = transplant_date or os.environ.get("TRANSPLANT_DATE")

    def open_conn():
        return conn_factory()

    # ------------------------------------------------------------------
    # 1. POST /api/v1/assessments
    # ------------------------------------------------------------------
    @app.post("/api/v1/assessments")
    def post_assessment():
        leaf_id = request.form.get("leaf_id", "").strip()
        captured_at_raw = request.form.get("captured_at", "").strip()
        video_file = request.files.get("video")

        try:
            db.validate_leaf_id(leaf_id)
        except ValueError as exc:
            return _error("invalid_leaf_id", str(exc), 400)

        try:
            captured_utc = db.ensure_utc(captured_at_raw, "captured_at")
        except ValueError as exc:
            return _error("invalid_timestamp", str(exc), 400)

        if video_file is None or not video_file.filename:
            return _error("missing_video", "campo multipart 'video' é obrigatório", 400)

        payload_bytes = video_file.read()
        if not payload_bytes:
            return _error("empty_video", "arquivo de vídeo vazio", 400)
        sha256 = hashlib.sha256(payload_bytes).hexdigest()

        conn = open_conn()
        try:
            existing = db.get_assessment_by_sha256(conn, sha256)
            if existing is not None:
                return jsonify({
                    "assessment_id": existing["assessment_id"],
                    "vision": existing["result"],
                }), 200

            captured_local = captured_utc.astimezone(LOCAL_TZ)
            day_dir = videos_root / captured_local.date().isoformat()
            day_dir.mkdir(parents=True, exist_ok=True)
            ext = Path(video_file.filename).suffix.lower() or ".mp4"
            base_name = f"{leaf_id}_{captured_local.strftime('%Y%m%dT%H%M')}{ext}"
            saved_path = day_dir / base_name
            if saved_path.exists():
                saved_path = day_dir / f"{leaf_id}_{captured_local.strftime('%Y%m%dT%H%M')}_{sha256[:8]}{ext}"
            saved_path.write_bytes(payload_bytes)

            with vision_lock:
                vision_res = pipeline.process(
                    str(saved_path),
                    leaf_id=leaf_id,
                    captured_at=captured_local.isoformat(),
                    debug_dir=str(debug_root),
                )

            assessment_id, created = db.insert_video_assessment(conn, vision_res, str(saved_path))
            if not created:
                existing = db.get_assessment_by_sha256(conn, sha256)
                return jsonify({
                    "assessment_id": existing["assessment_id"],
                    "vision": existing["result"],
                }), 200

            status_code = 201 if vision_res.get("quality", {}).get("ok") else 422
            return jsonify({"assessment_id": assessment_id, "vision": vision_res}), status_code
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 2. POST /api/v1/pots/<pot_id>/assimilate?disease=
    # ------------------------------------------------------------------
    @app.post("/api/v1/pots/<pot_id>/assimilate")
    def post_assimilate(pot_id: str):
        disease = request.args.get("disease", "").strip()
        try:
            db.validate_pot_id(pot_id)
        except ValueError as exc:
            return _error("invalid_pot_id", str(exc), 400)
        try:
            db.validate_disease(disease)
        except ValueError as exc:
            return _error("invalid_disease", str(exc), 400)

        conn = open_conn()
        try:
            assessments = db.get_accepted_assessments_for_pot(conn, pot_id, disease=disease, simulated=False)
            if not assessments:
                return _error(
                    "no_accepted_assessments",
                    f"nenhuma avaliação aceita encontrada para o vaso {pot_id}",
                    404,
                )
            pot_obs = ea.aggregate_leaves_to_pot(assessments)
            first_ts = pot_obs[0]["ts"]
            now_utc = datetime.now(UTC)

            weather_obs = db.get_weather_hourly(conn, station_id=st_id, kind="observed", start=first_ts, end=now_utc)
            weather_fc = db.get_weather_hourly(conn, station_id=st_id, kind="forecast", start=now_utc)
            prev_fit = db.get_latest_epi_fit(conn, pot_id, disease, simulated=False)
            prev_state = prev_fit["state"] if prev_fit else None
            sprays = db.get_spray_events(conn, pot_id, simulated=False)

            fit_res = ea.assimilate(
                unit_id=pot_id,
                disease=disease,
                observations=pot_obs,
                weather_observed=weather_obs,
                weather_forecast=weather_fc,
                prev_state=prev_state,
                spray_events=[s["applied_at"] for s in sprays],
                now=now_utc,
            )
            db.insert_epi_fit(conn, fit_res, simulated=False)

            # SKILL.md seção 4: a decisão roda depois de cada assimilação dos vasos V11 a V20
            if pot_id in de.DSS_POTS:
                dsv_rows = db.get_dsv_daily(conn, station_id=st_id, kind="observed")
                if not dsv_rows and weather_obs:
                    dsv_rows = de.compute_dsv_daily_rows(weather_obs, station_id=st_id, kind="observed")
                    db.upsert_dsv_daily(conn, dsv_rows)
                last_spray = sprays[-1] if sprays else None
                decision_res = de.decide(
                    epi_result=fit_res,
                    dsv_daily=dsv_rows,
                    last_spray=last_spray,
                    transplant_date=tp_date,
                    now=now_utc,
                )
                db.insert_decision(conn, decision_res, simulated=False)

            return jsonify(fit_res), 200
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 3. GET /api/v1/pots/<pot_id>/projection?disease=
    # ------------------------------------------------------------------
    @app.get("/api/v1/pots/<pot_id>/projection")
    def get_projection(pot_id: str):
        disease = request.args.get("disease", "").strip()
        try:
            db.validate_pot_id(pot_id)
        except ValueError as exc:
            return _error("invalid_pot_id", str(exc), 400)
        try:
            db.validate_disease(disease)
        except ValueError as exc:
            return _error("invalid_disease", str(exc), 400)

        conn = open_conn()
        try:
            latest = db.get_latest_epi_fit(conn, pot_id, disease, simulated=False)
            if latest is None:
                return _error("projection_not_found", f"sem projeção gravada para {pot_id}/{disease}", 404)
            return jsonify(latest["result"]), 200
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 4. GET /api/v1/pots/<pot_id>/decision?disease=
    # ------------------------------------------------------------------
    @app.get("/api/v1/pots/<pot_id>/decision")
    def get_decision(pot_id: str):
        disease = request.args.get("disease", "").strip()
        try:
            db.validate_pot_id(pot_id)
        except ValueError as exc:
            return _error("invalid_pot_id", str(exc), 400)
        try:
            db.validate_disease(disease)
        except ValueError as exc:
            return _error("invalid_disease", str(exc), 400)

        conn = open_conn()
        try:
            latest = db.get_latest_decision(conn, pot_id, disease, simulated=False)
            if latest is not None:
                return jsonify(latest["result"]), 200

            latest_fit = db.get_latest_epi_fit(conn, pot_id, disease, simulated=False)
            if latest_fit is None:
                return _error("decision_not_found", f"sem decisão nem ajuste gravado para {pot_id}/{disease}", 404)

            dsv_rows = db.get_dsv_daily(conn, station_id=st_id, kind="observed")
            last_spray = db.get_last_spray_event(conn, pot_id, simulated=False)
            decision_res = de.decide(
                epi_result=latest_fit["result"],
                dsv_daily=dsv_rows,
                last_spray=last_spray,
                transplant_date=tp_date,
            )
            db.insert_decision(conn, decision_res, simulated=False)
            return jsonify(decision_res), 200
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 5. POST /api/v1/sprays
    # ------------------------------------------------------------------
    @app.post("/api/v1/sprays")
    def post_spray():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return _error("invalid_json", "corpo JSON obrigatório", 400)

        pot_id = str(body.get("pot_id", "")).strip()
        applied_at_raw = body.get("applied_at")
        product = str(body.get("product", "")).strip()
        dose = body.get("dose")
        notes = body.get("notes")

        try:
            db.validate_pot_id(pot_id)
        except ValueError as exc:
            return _error("invalid_pot_id", str(exc), 400)
        try:
            applied_utc = db.ensure_utc(applied_at_raw, "applied_at")
        except ValueError as exc:
            return _error("invalid_timestamp", str(exc), 400)
        if not product:
            return _error("invalid_product", "campo 'product' é obrigatório", 400)

        conn = open_conn()
        try:
            spray_id = db.insert_spray_event(
                conn,
                pot_id=pot_id,
                applied_at=applied_utc,
                product=product,
                dose=dose,
                notes=notes,
                simulated=False,
            )
            return jsonify({
                "spray_id": spray_id,
                "pot_id": pot_id,
                "applied_at": applied_utc.astimezone(LOCAL_TZ).isoformat(),
                "product": product,
                "dose": dose,
                "notes": notes,
            }), 201
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 6. GET /api/v1/weather/summary
    # ------------------------------------------------------------------
    @app.get("/api/v1/weather/summary")
    def get_weather_summary_route():
        conn = open_conn()
        try:
            return jsonify(db.get_weather_summary(conn, station_id=st_id)), 200
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 7. GET /api/v1/health
    # ------------------------------------------------------------------
    @app.get("/api/v1/health")
    def get_health():
        db_ok = False
        try:
            conn = open_conn()
            try:
                db_ok = db.check_health(conn)
            finally:
                conn.close()
        except Exception:
            db_ok = False
        return jsonify({
            "db": db_ok,
            "gpu": _check_gpu(),
            "weights": _check_weights(pipeline.cfg),
        }), 200

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    application = create_app()
    application.run(
        host=os.environ.get("FLASK_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_PORT", "5000")),
        threaded=True,
    )
