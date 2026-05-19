from __future__ import annotations

from flask import Blueprint, current_app, request

from backend.api.responses import error_response, ok


bp = Blueprint("join_search", __name__)


@bp.post("/join-search")
def join_search():
    payload = request.get_json(silent=True) or {}
    datalake = payload.get("datalake") or payload.get("name")
    nl_query = payload.get("natural_language_query") or payload.get("nl_query") or payload.get("query") or ""
    confirmed_rows = (
        payload.get("confirmed_query_table_rows")
        or payload.get("selected_query_table_rows")
        or payload.get("rows")
        or payload.get("query_table", {}).get("rows", [])
    )
    if not datalake:
        return error_response("Missing required field: datalake", code="bad_request", status_code=400)
    if not isinstance(confirmed_rows, list) or not confirmed_rows:
        return error_response("Missing required field: confirmed_query_table_rows", code="bad_request", status_code=400)

    service = current_app.config["JOIN_SEARCH_SERVICE"]
    top_k = payload.get("top_k", payload.get("k", 5))
    dedup_threshold = payload.get("dedup_threshold", 0.8)
    try:
        data = service.search(
            datalake=datalake,
            natural_language_query=str(nl_query),
            confirmed_rows=confirmed_rows,
            top_k=int(top_k),
            dedup_threshold=float(dedup_threshold),
        )
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)
    return ok(data)
