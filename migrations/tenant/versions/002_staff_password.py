"""Add password_hash to staff_users for standalone tenant login."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_users", sa.Column("password_hash", sa.String(255), nullable=False, server_default=""))
    op.create_unique_constraint("uq_staff_users_email", "staff_users", ["email"])
    op.alter_column("staff_users", "password_hash", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_staff_users_email", "staff_users", type_="unique")
    op.drop_column("staff_users", "password_hash")
