"""Initial tenant schema

Revision ID: 001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "restaurant_profile",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("business_hours", postgresql.JSONB(), nullable=True),
        sa.Column("settings", postgresql.JSONB(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "menu_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "menu_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("image_url", sa.String(512), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["menu_categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menu_items_category_available", "menu_items", ["category_id", "is_available"])
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("addresses", postgresql.JSONB(), nullable=True),
        sa.Column("orders_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("last_order_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customers_phone"), "customers", ["phone"])
    op.create_table(
        "staff_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("source_agent", sa.String(64), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_orders_status_placed", "orders", ["status", "placed_at"])
    op.create_index("ix_orders_placed_at", "orders", ["placed_at"])
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("item_name_snapshot", sa.String(255), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.Column("modifiers", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"])
    op.create_index(op.f("ix_order_items_menu_item_id"), "order_items", ["menu_item_id"])
    op.create_table(
        "order_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.String(32), nullable=True),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "daily_sales_rollup",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("orders_count", sa.Integer(), nullable=False),
        sa.Column("gross_revenue", sa.Numeric(14, 2), nullable=False),
        sa.Column("avg_order_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("items_sold", sa.Integer(), nullable=False),
        sa.Column("by_status", postgresql.JSONB(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("day"),
    )
    op.create_table(
        "menu_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "routing_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    for t in [
        "routing_outbox", "menu_outbox", "daily_sales_rollup", "order_status_history",
        "order_items", "orders", "staff_users", "customers", "menu_items",
        "menu_categories", "restaurant_profile",
    ]:
        op.drop_table(t)
