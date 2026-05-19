from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from backend.api.responses import error_response
from backend.config import BackendConfig, load_config
from backend.services.datalake import DataLakeError, DataLakeService
from backend.services.preprocessing import build_preprocessing_service


def create_app(config: BackendConfig | None = None) -> Flask:
    app = Flask(__name__)
    backend_config = config or load_config()
    datalake_service = DataLakeService(backend_config.datalake_dir)
    app.config["NLDISC_CONFIG"] = backend_config
    app.config["DATALAKE_SERVICE"] = datalake_service
    app.config["PREPROCESSING_SERVICE"] = build_preprocessing_service(backend_config, datalake_service)

    CORS(app, origins=backend_config.cors_origins)

    from backend.api import datalakes, health, preprocess

    app.register_blueprint(health.bp, url_prefix="/api")
    app.register_blueprint(datalakes.bp, url_prefix="/api")
    app.register_blueprint(preprocess.bp, url_prefix="/api")

    @app.errorhandler(DataLakeError)
    def handle_datalake_error(exc: DataLakeError):
        return error_response(str(exc), code=exc.code, status_code=exc.status_code)

    @app.errorhandler(404)
    def handle_not_found(_exc):
        return error_response("Endpoint not found", code="not_found", status_code=404)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
