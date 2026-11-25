"""Alembic environment: runs on the connection that :mod:`reframe.queue.store` hands over."""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("The queue store runs its migrations; there is no offline mode.")
context.configure(connection=connection, transactional_ddl=True, transaction_per_migration=True)
with context.begin_transaction():
    context.run_migrations()
