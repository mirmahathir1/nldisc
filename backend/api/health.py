from __future__ import annotations

from flask import Blueprint, current_app

from backend.api.responses import ok


bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    config = current_app.config["NLDISC_CONFIG"]
    return ok(
        {
            "service": "nldisc-backend",
            "version": "0.1.0",
            "datalake_dir": str(config.datalake_dir),
            "preprocessed_dir": str(config.preprocessed_dir),
        }
    )
