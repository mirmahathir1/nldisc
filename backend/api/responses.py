from __future__ import annotations

from typing import Any

from flask import jsonify


def ok(data: Any, status_code: int = 200):
    return jsonify({"status": "ok", "data": data, "error": None}), status_code


def error_response(message: str, code: str = "error", status_code: int = 400):
    payload = {"status": "error", "data": None, "error": {"code": code, "message": message}}
    return jsonify(payload), status_code

