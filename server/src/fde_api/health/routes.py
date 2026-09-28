from flask import Blueprint, jsonify

from fde_api.errors import error_response
from fde_api.extensions import db, redis_client


health_blueprint = Blueprint("health", __name__, url_prefix="/api/v1/health")


def mysql_ping() -> bool:
    try:
        return db.ping()
    except Exception:
        return False


def redis_ping() -> bool:
    try:
        return redis_client.ping()
    except Exception:
        return False


@health_blueprint.get("/live")
def live():
    return jsonify({"data": {"status": "ok"}, "error": None})


@health_blueprint.get("/ready")
def ready():
    mysql_status = "ok" if mysql_ping() else "unavailable"
    redis_status = "ok" if redis_ping() else "degraded"
    data = {"mysql": mysql_status, "redis": redis_status}

    if mysql_status != "ok":
        return error_response("service_unavailable", "MySQL is unavailable.", 503)

    return jsonify({"data": data, "error": None})
