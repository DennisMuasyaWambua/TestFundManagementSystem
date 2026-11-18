"""Alembic environment.

The target metadata is the application's own, and the URL comes from the application
settings, so a migration can never be generated against a different schema than the
one the code expects.

``render_item`` renders the application's custom column types as their plain SQL
equivalents.  A migration is a historical record of the database: it has to keep
working after the Python types are renamed or refactored, so it must not import
application code.
"""

from __future__ import annotations

from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db import Base, EnumStr, MoneyT, RateT, append_only_ddl
from app.models import *  # noqa: F403  (import every model so metadata is complete)

config = context.config
# Tests drive Alembic in-process and configure their own logging.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# A caller may pin the URL (tests, or `alembic -x`); otherwise use the app settings,
# so a migration can never be generated against a different database than the code.
if not config.get_main_option("sqlalchemy.url", ""):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata

__all__ = ["append_only_ddl", "render_item", "target_metadata"]


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Render MoneyT / RateT / EnumStr as plain ``sa`` types in generated migrations."""
    if type_ != "type":
        return False
    if isinstance(obj, MoneyT):
        return "sa.Numeric(precision=24, scale=2)"
    if isinstance(obj, RateT):
        return "sa.Numeric(precision=24, scale=8)"
    if isinstance(obj, EnumStr):
        return f"sa.String(length={obj.length})"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_item=render_item,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
