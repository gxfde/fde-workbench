"""P0/P1 指标报表路由（goal-d8，只读；PRD §10 分期业务指标聚合）。"""
from __future__ import annotations

from flask import Blueprint, jsonify

from fde_api.auth.decorators import require_auth
from fde_api.extensions import db
from fde_api.metrics.service import build_metrics_report

metrics_blueprint = Blueprint("metrics", __name__, url_prefix="/api/v1/metrics")


@metrics_blueprint.get("/report")
@require_auth
def metrics_report_route():
    """PRD §10 指标报表（脱敏聚合：计数/占比/中位数，无客户数据）。"""
    with db.session() as session:
        return jsonify({"data": build_metrics_report(session), "error": None})
