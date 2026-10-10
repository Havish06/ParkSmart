"""Small additive upgrade for the original prototype databases."""
from sqlalchemy import inspect, text
from . import db


def upgrade_schema():
    inspector = inspect(db.engine)
    existing = inspector.get_table_names()
    with db.engine.begin() as connection:
        for table in db.metadata.sorted_tables:
            if table.name not in existing:
                continue
            columns = {c['name'] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in columns:
                    continue
                sql_type = column.type.compile(dialect=db.engine.dialect)
                default = f' DEFAULT {column.server_default.arg}' if column.server_default else ''
                nullable = '' if column.nullable else ' NOT NULL'
                connection.execute(text(
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {sql_type}{default}{nullable}'
                ))
        if 'parking_session' in existing:
            connection.execute(text("UPDATE parking_session SET status='completed' WHERE exit_time IS NOT NULL AND status='active'"))
            connection.execute(text("UPDATE parking_session SET active_slot_id=slot_id, active_vehicle=vehicle_number WHERE exit_time IS NULL AND status='active'"))
        if 'user' in existing:
            connection.execute(text("UPDATE user SET vehicle_number='NOT PROVIDED' WHERE vehicle_number IS NULL"))
    db.create_all()
    # ALTER TABLE cannot add UNIQUE constraints on SQLite. Explicit indexes also
    # protect admission/payment against duplicate concurrent requests.
    with db.engine.begin() as connection:
        for name, table, column in [
            ('uq_live_slot', 'parking_session', 'active_slot_id'),
            ('uq_live_vehicle', 'parking_session', 'active_vehicle'),
            ('uq_session_payment', 'payment', 'session_id'),
            ('uq_reservation_payment_transaction', 'reservation', 'payment_transaction_id'),
        ]:
            connection.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({column})'))
