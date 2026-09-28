from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException


def error_response(code: str, message: str, status: int, details=None):
    return (
        jsonify(
            {
                "data": None,
                "error": {"code": code, "message": message, "details": details},
            }
        ),
        status,
    )


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        status = error.code or 500
        if status == 404:
            return error_response(
                "not_found",
                "请求的接口不存在，请检查客户端与服务端版本是否一致。",
                status,
            )
        if status == 405:
            return error_response("method_not_allowed", "当前接口不支持该操作。", status)
        return error_response("http_error", "请求处理失败，请检查输入后重试。", status)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        app.logger.exception("Unhandled API error", exc_info=error)
        return error_response("internal_error", "系统发生异常，请稍后重试。", 500)
