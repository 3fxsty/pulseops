from alembic import command


def test_migrations_downgrade_and_upgrade_cleanly(migrated_database, alembic_config):
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_models_match_migrations(migrated_database, alembic_config):
    # Raises if a model changed without a matching migration.
    command.check(alembic_config)
