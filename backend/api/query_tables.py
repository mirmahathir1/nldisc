from __future__ import annotations

from flask import Blueprint, current_app, request

from backend.api.responses import error_response, ok
from backend.services.sample_queries import sample_queries_for


bp = Blueprint("query_tables", __name__)


@bp.get("/sample-queries")
def sample_queries():
    datalake = request.args.get("datalake", "")
    if not datalake:
        return error_response("Missing required query parameter: datalake", code="bad_request", status_code=400)
    service = current_app.config["DATALAKE_SERVICE"]
    service.resolve_lake(datalake)
    return ok({"datalake": datalake, "queries": sample_queries_for(datalake)})


@bp.post("/query-tables")
def query_tables():
    payload = request.get_json(silent=True) or {}
    datalake = payload.get("datalake")
    nl_query = payload.get("natural_language_query") or payload.get("nl_query") or payload.get("query") or ""
    if not datalake:
        return error_response("Missing required field: datalake", code="bad_request", status_code=400)
    if not str(nl_query).strip():
        return error_response("Missing required field: natural_language_query", code="bad_request", status_code=400)

    service = current_app.config["QUERY_TABLE_SERVICE"]
    try:
        data = service.generate(
            datalake=datalake,
            natural_language_query=str(nl_query),
            suggestion_count=int(payload.get("desired_suggestion_count") or payload.get("suggestion_count") or 4),
            ann_topk=int(payload.get("ann_topk") or 25),
        )
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)
    return ok(data)


@bp.post("/query-tables/resubmit")
def resubmit_query_tables():
    payload = request.get_json(silent=True) or {}
    datalake = payload.get("datalake")
    nl_query = payload.get("natural_language_query") or payload.get("nl_query") or payload.get("query") or ""
    edited_rows = (
        payload.get("edited_query_table_rows")
        or payload.get("selected_query_table_rows")
        or payload.get("rows")
        or payload.get("query_table", {}).get("rows", [])
    )
    if not datalake:
        return error_response("Missing required field: datalake", code="bad_request", status_code=400)
    if not str(nl_query).strip():
        return error_response("Missing required field: natural_language_query", code="bad_request", status_code=400)
    if not isinstance(edited_rows, list) or not edited_rows:
        return error_response("Missing required field: edited_query_table_rows", code="bad_request", status_code=400)

    service = current_app.config["QUERY_TABLE_SERVICE"]
    try:
        data = service.resubmit(
            datalake=datalake,
            natural_language_query=str(nl_query),
            edited_rows=edited_rows,
            prior_selected_table_name=payload.get("prior_selected_table_name") or payload.get("selected_table_name"),
            suggestion_count=int(payload.get("desired_suggestion_count") or payload.get("suggestion_count") or 4),
            ann_topk=int(payload.get("ann_topk") or 25),
        )
    except FileNotFoundError as exc:
        return error_response(str(exc), code="preprocess_artifacts_not_found", status_code=404)
    except ValueError as exc:
        return error_response(str(exc), code="bad_request", status_code=400)
    return ok(data)
