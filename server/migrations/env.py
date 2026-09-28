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
from fde_api.guidance import models as guidance_models  # noqa: F401
from fde_api.control import models as control_models  # noqa: F401
from fde_api.control import model_preferences, weixin_models, chat, lcsc_skills  # noqa: F401


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = config.attributes.get("settings") or Settings()
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.database_url, poolclass=NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
