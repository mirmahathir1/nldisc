from __future__ import annotations

from flask import Blueprint, current_app

from backend.api.responses import ok


bp = Blueprint("datalakes", __name__)


@bp.get("/datalakes")
def list_datalakes():
    service = current_app.config["DATALAKE_SERVICE"]
    return ok({"datalakes": service.list_lakes()})


@bp.get("/datalakes/<name>/summary")
def datalake_summary(name: str):
    config = current_app.config["NLDISC_CONFIG"]
    service = current_app.config["DATALAKE_SERVICE"]
    return ok(service.summary(name, sample_limit=config.sample_row_limit))
