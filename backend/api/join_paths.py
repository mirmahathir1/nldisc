from __future__ import annotations

from flask import Blueprint, Response, current_app, request

from backend.api.responses import error_response, ok
from backend.services.materialization import JoinPathNotFound


bp = Blueprint("join_paths", __name__)


@bp.get("/join-paths/<path_id>")
def join_path_metadata(path_id: str):
    datalake = request.args.get("datalake") or request.args.get("name")
    if not datalake:
        return error_response("Missing required query parameter: datalake", code="bad_request", status_code=400)

    service = current_app.config["MATERIALIZATION_SERVICE"]
    try:
        return ok(service.path_metadata(datalake, path_id))
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except JoinPathNotFound as exc:
        return error_response(str(exc), code="join_path_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)


@bp.get("/join-paths/<path_id>/sql")
def join_path_sql(path_id: str):
    datalake = request.args.get("datalake") or request.args.get("name")
    if not datalake:
        return error_response("Missing required query parameter: datalake", code="bad_request", status_code=400)

    service = current_app.config["MATERIALIZATION_SERVICE"]
    try:
        return ok(service.sql(datalake, path_id))
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except JoinPathNotFound as exc:
        return error_response(str(exc), code="join_path_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)


@bp.route("/join-paths/<path_id>/materialize", methods=["GET", "POST"])
def join_path_materialize(path_id: str):
    body = request.get_json(silent=True) if request.method == "POST" else None
    body = body if isinstance(body, dict) else {}
    datalake = (
        body.get("datalake")
        or body.get("name")
        or request.args.get("datalake")
        or request.args.get("name")
    )
    if not datalake:
        return error_response("Missing required query parameter: datalake", code="bad_request", status_code=400)

    service = current_app.config["MATERIALIZATION_SERVICE"]
    try:
        limit_value = body.get("limit") if body.get("limit") is not None else request.args.get("limit", "50")
        limit = int(limit_value)
        query_columns = body.get("query_columns") or []
        query_semantic_types = body.get("query_semantic_types") or {}
        if not isinstance(query_columns, list):
            raise ValueError("query_columns must be a list of strings")
        if not isinstance(query_semantic_types, dict):
            raise ValueError("query_semantic_types must be a JSON object")
        return ok(
            service.materialize(
                datalake,
                path_id,
                limit=limit,
                query_columns=[str(column) for column in query_columns],
                query_semantic_types={str(k): str(v) for k, v in query_semantic_types.items()},
            )
        )
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except JoinPathNotFound as exc:
        return error_response(str(exc), code="join_path_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)


@bp.route("/join-paths/<path_id>/csv", methods=["GET", "POST"])
def join_path_csv(path_id: str):
    body = request.get_json(silent=True) if request.method == "POST" else None
    body = body if isinstance(body, dict) else {}
    datalake = (
        body.get("datalake")
        or body.get("name")
        or request.args.get("datalake")
        or request.args.get("name")
    )
    if not datalake:
        return error_response("Missing required query parameter: datalake", code="bad_request", status_code=400)

    service = current_app.config["MATERIALIZATION_SERVICE"]
    try:
        query_columns = body.get("query_columns") or []
        query_semantic_types = body.get("query_semantic_types") or {}
        if not isinstance(query_columns, list):
            raise ValueError("query_columns must be a list of strings")
        if not isinstance(query_semantic_types, dict):
            raise ValueError("query_semantic_types must be a JSON object")
        csv_text, filename = service.csv(
            datalake,
            path_id,
            query_columns=[str(column) for column in query_columns],
            query_semantic_types={str(k): str(v) for k, v in query_semantic_types.items()},
        )
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except JoinPathNotFound as exc:
        return error_response(str(exc), code="join_path_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)

    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
