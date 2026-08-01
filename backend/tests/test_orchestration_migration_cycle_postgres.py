import os
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import get_settings


def test_migration_upgrade_downgrade_upgrade_on_isolated_postgres_database():
    original_url = get_settings().database_url
    base_url = make_url(original_url)
    database_name = f"finos_migration_test_{uuid.uuid4().hex}"
    admin_url = base_url.set(database=base_url.database)
    isolated_url = base_url.set(database=database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    try:
        os.environ["DATABASE_URL"] = isolated_url.render_as_string(hide_password=False)
        get_settings.cache_clear()
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        isolated_engine = create_engine(isolated_url)
        with isolated_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "5c1a7e9d3b20"
        isolated_engine.dispose()
    finally:
        os.environ["DATABASE_URL"] = original_url
        get_settings.cache_clear()
        with admin_engine.connect() as connection:
            connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()
