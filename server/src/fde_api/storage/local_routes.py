from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from fde_api.extensions import object_storage
from fde_api.storage.base import StorageError
from fde_api.storage.local import LocalObjectStorage


local_storage_blueprint = Blueprint(
    "local_storage", __name__, url_prefix="/api/v1/local-storage"
)

# The renderer streams signed object-storage bytes directly (part PUT, download),
# so this blueprint must answer cross-origin preflights and expose the ETag header.
_OBJECT_STORAGE_CORS_METHODS = {"PUT", "GET", "HEAD", "OPTIONS"}


@local_storage_blueprint.after_request
def _add_object_storage_cors(response: Response) -> Response:
    origin = request.headers.get("Origin")
    if not origin or not request.path.startswith("/api/v1/local-storage"):
        return response
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "false"
    response.headers["Vary"] = "Origin"
    if request.method == "OPTIONS":
        response.headers["Access-Control-Allow-Methods"] = ", ".join(
            sorted(_OBJECT_STORAGE_CORS_METHODS)
        )
        response.headers["Access-Control-Allow-Headers"] = (
            request.headers.get("Access-Control-Request-Headers") or "Content-Type"
        )
        response.headers["Access-Control-Max-Age"] = "600"
    response.headers["Access-Control-Expose-Headers"] = "ETag"
    return response


@local_storage_blueprint.put(
    "/multipart/<upload_id>/parts/<int:part_number>"
)
def upload_part(upload_id: str, part_number: int):
    try:
        storage = _local_storage()
        etag = storage.accept_signed_part(
            method=request.method,
            key=request.args.get("key", ""),
            upload_id=upload_id,
            part_number=part_number,
            expires=request.args.get("expires", ""),
            signature=request.args.get("signature", ""),
            stream=request.stream,
        )
    except StorageError as error:
        return _storage_error(error)
    response = Response(status=200)
    response.headers["ETag"] = f'"{etag}"'
    return response


@local_storage_blueprint.get("/download")
def download_object():
    try:
        storage = _local_storage()
        stored, stream, disposition = storage.open_signed_download(
            method=request.method,
            key=request.args.get("key", ""),
            filename=request.args.get("filename", ""),
            expires=request.args.get("expires", ""),
            signature=request.args.get("signature", ""),
        )
    except StorageError as error:
        return _storage_error(error)

    def chunks():
        try:
            while chunk := stream.read(1024 * 1024):
                yield chunk
        finally:
            stream.close()

    response = Response(chunks(), content_type=stored.content_type)
    response.content_length = stored.size
    response.headers["Content-Disposition"] = disposition
    return response


def _local_storage() -> LocalObjectStorage:
    storage = object_storage.current
    if not isinstance(storage, LocalObjectStorage):
        raise StorageError("local_storage_unavailable")
    return storage


def _storage_error(error: StorageError):
    status = 404 if error.code in {
        "local_storage_unavailable",
        "object_not_found",
        "multipart_upload_not_found",
    } else 403
    return (
        jsonify(
            {
                "data": None,
                "error": {"code": error.code, "message": error.code, "details": None},
            }
        ),
        status,
    )
