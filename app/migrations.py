"""Idempotent schema upgrades for the Housing Aggregator database.

The project started without a migration tool, so instead of pulling in Alembic
this module compares the tables SQLAlchemy expects against what is actually in
MySQL and adds whatever is missing. Every step is safe to run repeatedly, so
`python init_db.py` can be used both for a fresh install and to bring an older
database up to date.
"""

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn

from app.extensions import db

# Columns added after the first release of the schema. They are nullable at
# the database level so ALTER TABLE still works on tables that already hold
# rows, and the defaults are applied in Python (and backfilled below).
BACKFILL_DEFAULTS = {
    "properties": {
        "is_active": "1",
        "availability_status": "'unknown'",
        "gps_exact": "0",
    },
    "payment": {
        "simulated": "0",
    },
    "notification": {
        "isread": "0",
    },
    "search_alert": {
        "isactive": "1",
    },
    "scraping_source": {
        "enabled": "1",
        "respects_robots": "1",
    },
}


def _existing_tables():
    return set(inspect(db.engine).get_table_names())


def _existing_columns(table_name):
    return {c["name"] for c in inspect(db.engine).get_columns(table_name)}


def _existing_indexes(table_name):
    return {i["name"] for i in inspect(db.engine).get_indexes(table_name)}


def create_missing_tables():
    """Create any table defined in the models that is not in the database yet."""
    db.create_all()


def add_missing_columns():
    """Add columns that exist in the models but not in the database."""
    added = []
    tables = _existing_tables()

    for table in db.metadata.sorted_tables:
        if table.name not in tables:
            # the table itself is new, create_all() already built it
            continue

        present = _existing_columns(table.name)
        for column in table.columns:
            if column.name in present:
                continue

            ddl = str(CreateColumn(column).compile(dialect=db.engine.dialect))
            db.session.execute(text(f"ALTER TABLE `{table.name}` ADD COLUMN {ddl}"))
            added.append(f"{table.name}.{column.name}")

            if column.index:
                index_name = f"ix_{table.name}_{column.name}"
                if index_name not in _existing_indexes(table.name):
                    db.session.execute(
                        text(
                            f"ALTER TABLE `{table.name}` ADD INDEX `{index_name}` (`{column.name}`)"
                        )
                    )

    if added:
        db.session.commit()
    return added


def backfill_defaults():
    """Give rows that predate a column the default value for that column."""
    changed = 0
    for table_name, columns in BACKFILL_DEFAULTS.items():
        if table_name not in _existing_tables():
            continue
        for column, default in columns.items():
            result = db.session.execute(
                text(
                    f"UPDATE `{table_name}` SET `{column}` = {default} "
                    f"WHERE `{column}` IS NULL"
                )
            )
            changed += result.rowcount or 0
    if changed:
        db.session.commit()
    return changed


# text columns made longer after they were first created: table -> column
WIDENED_COLUMNS = {"payment": ["receipt_email"]}


def widen_columns():
    """Make VARCHAR columns as long as the models now say (MySQL only)."""
    if db.engine.dialect.name != "mysql":
        return []
    changed = []
    tables = {t.name: t for t in db.metadata.sorted_tables}
    for table_name, names in WIDENED_COLUMNS.items():
        if table_name not in _existing_tables():
            continue
        current = {c["name"]: c for c in inspect(db.engine).get_columns(table_name)}
        for name in names:
            wanted = tables[table_name].columns[name].type.length
            have = getattr(current.get(name, {}).get("type"), "length", None)
            if have is not None and wanted and have < wanted:
                db.session.execute(
                    text(f"ALTER TABLE `{table_name}` MODIFY `{name}` VARCHAR({wanted}) NULL")
                )
                changed.append(f"{table_name}.{name}")
    if changed:
        db.session.commit()
    return changed


def run_migrations():
    """Bring an existing database up to the current schema. Safe to re-run."""
    create_missing_tables()
    added = add_missing_columns() + widen_columns()
    backfilled = backfill_defaults()
    return added, backfilled
