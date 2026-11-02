from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from fde_api.auth.models import Base
from fde_api.config import Settings
from fde_api import system_configuration  # noqa: F401
from fde_api.workbench import models as workbench_models  # noqa: F401
from fde_api.files import models as file_models  # noqa: F401
from fde_api.jobs import models as job_models  # noqa: F401
from fde_api.documents import models as document_models  # noqa: F401
from fde_api.solutions import models as solution_models  # noqa: F401
from fde_api.agents import models as agent_models  # noqa: F401  (goal-d3)
from fde_api.meetings import models as meeting_models  # noqa: F401  (goal-d5)
from fde_api.guidance import models as guidance_models  # noqa: F401
from fde_api.control import models as control_models  # noqa: F401
from fde_api.mailing import models as mailing_models  # noqa: F401
from fde_api.dispatch import models as dispatch_models  # noqa: F401
from fde_api.translator import models as translator_models  # noqa: F401  (goal-d9)
from fde_api.evidence import models as evidence_models  # noqa: F401  (V3 T-E1)
from fde_api.workflows import models as workflow_models  # noqa: F401  (V3 T-W1)
from fde_api.control import model_preferences, weixin_models, chat, lcsc_skills  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = config.attributes.get("settings") or Settings()
target_metadata = Base.metadata


def render_custom_types(type_: str, obj: object, autogen_context) -> str | bool:
    """v0.2 (PG 迁移): 自定义类型在迁移文件里的渲染。

    autogenerate 默认把 UTCDateTime() 渲染成 fde_api.auth.models.UTCDateTime()，
    但不会生成对应 import，迁移文件执行时直接 NameError: name 'fde_api' is not defined。
    """
    if type_ == "type" and type(obj).__name__ in ("UTCDateTime", "UTCTimestamp"):
        autogen_context.imports.add("import fde_api.auth.models")
        return "sa.DateTime(timezone=True)"
    return False


def render_custom_types(type_: str, obj: object, autogen_context) -> str | bool:
    """v0.2 (PG 迁移): 自定义类型在迁移文件里的渲染。

    autogenerate 默认把 ``UTCDateTime()`` 渲染成
    ``fde_api.auth.models.UTCDateTime()``，但不会生成对应的 import，
    迁移文件执行时直接 NameError: name 'fde_api' is not defined。

    这里显式返回 ``sa.DateTime(timezone=True)``（PG 语义与 UTCDateTime 等价：
    UTCDateTime 本身就是「UTC 归一 + 存时区」），并把 import 补进迁移文件。
    """
    if type_ == "type" and type(obj).__name__ in ("UTCDateTime", "UTCTimestamp"):
        autogen_context.imports.add("import fde_api.auth.models")
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_custom_types,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url, poolclass=NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=render_custom_types,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
