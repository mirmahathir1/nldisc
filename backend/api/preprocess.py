from __future__ import annotations

from flask import Blueprint, current_app, request

from backend.api.responses import error_response, ok
from backend.services.preprocessing import normalize_preprocess_params


bp = Blueprint("preprocess", __name__)


@bp.post("/preprocess")
def preprocess_datalake():
    payload = request.get_json(silent=True) or {}
    datalake = payload.get("datalake") or payload.get("name")
    if not datalake:
        return error_response("Missing required field: datalake", code="bad_request", status_code=400)

    params = normalize_preprocess_params(payload.get("params") or payload)
    force = bool(payload.get("force", False))
    service = current_app.config["PREPROCESSING_SERVICE"]
    return ok(service.preprocess(datalake, params, force=force))


@bp.get("/preprocess/<name>/artifacts")
def preprocess_artifacts(name: str):
    service = current_app.config["PREPROCESSING_SERVICE"]
    try:
        return ok(service.load_artifacts(name))
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)

