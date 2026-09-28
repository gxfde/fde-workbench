from hashlib import sha256

from flask import Flask, current_app, request
from redis import Redis
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from fde_api.config import Settings
from fde_api.storage import AliyunOssStorage, LocalObjectStorage, ObjectStorage


class Database:
    def init_app(self, app: Flask, settings: Settings) -> None:
        engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
        if engine.dialect.name == "mysql":
            event.listen(engine, "connect", self._set_mysql_utc_timezone)
        app.extensions["fde_api_db"] = engine
        app.extensions["fde_api_session_factory"] = sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> Engine:
        return current_app.extensions["fde_api_db"]

    def session(self) -> Session:
        session_factory: sessionmaker[Session] = current_app.extensions[
            "fde_api_session_factory"
        ]
        return session_factory()

    @staticmethod
    def _set_mysql_utc_timezone(dbapi_connection, _) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


class RedisClient:
    def init_app(self, app: Flask, settings: Settings) -> None:
        app.extensions["fde_api_redis"] = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )

    def ping(self) -> bool:
        client: Redis = current_app.extensions["fde_api_redis"]
        return bool(client.ping())


class ObjectStorageExtension:
    _extension_key = "fde_api_object_storage"

    def init_app(self, app: Flask, settings: Settings) -> None:
        if settings.storage_backend == "local":
            storage: ObjectStorage = LocalObjectStorage(
                settings.local_storage_root,
                base_url_provider=lambda: request.host_url.rstrip("/"),
                signing_key=sha256(
                    f"fde-local-storage:{settings.jwt_secret}".encode()
                ).digest(),
            )
        else:
            storage = AliyunOssStorage(
                endpoint=settings.oss_endpoint,
                bucket_name=settings.oss_bucket or "",
                access_key_id=settings.oss_access_key_id,
                access_key_secret=settings.oss_access_key_secret,
            )
        app.extensions[self._extension_key] = storage

    @property
    def current(self) -> ObjectStorage:
        return current_app.extensions[self._extension_key]


db = Database()
redis_client = RedisClient()
object_storage = ObjectStorageExtension()
