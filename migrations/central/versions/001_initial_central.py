"""Initial central schema

Revision ID: 001
Revises:
Create Date: 2026-06-25
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
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_email", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=False)

    op.create_table(
        "tenant_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("db_host", sa.String(255), nullable=False),
        sa.Column("db_port", sa.Integer(), nullable=False),
        sa.Column("db_name", sa.String(128), nullable=False),
        sa.Column("db_role", sa.String(128), nullable=False),
        sa.Column("db_password_enc", sa.LargeBinary(), nullable=False),
        sa.Column("pool_class", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenant_connections")),
        sa.UniqueConstraint("tenant_id", name=op.f("uq_tenant_connections_tenant_id")),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)

    op.create_table(
        "catalog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_items")),
    )
    op.create_index("ix_catalog_items_tenant_available", "catalog_items", ["tenant_id", "is_available"])

    op.create_table(
        "whatsapp_numbers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("phone_number_id", sa.String(64), nullable=False),
        sa.Column("display_number", sa.String(32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_numbers")),
        sa.UniqueConstraint("phone_number_id", name=op.f("uq_whatsapp_numbers_phone_number_id")),
    )
    op.create_index(op.f("ix_whatsapp_numbers_phone_number_id"), "whatsapp_numbers", ["phone_number_id"])

    op.create_table(
        "order_routing_index",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("customer_phone_hash", sa.String(64), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_routing_index")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_order_routing_index_idempotency_key")),
    )
    op.create_index("ix_routing_tenant_status_placed", "order_routing_index", ["tenant_id", "status", "placed_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )

    op.create_table(
        "agent_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_phone_hash", sa.String(64), nullable=False),
        sa.Column("active_tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_conversations")),
    )
    op.create_index(op.f("ix_agent_conversations_customer_phone_hash"), "agent_conversations", ["customer_phone_hash"])


def downgrade() -> None:
    op.drop_table("agent_conversations")
    op.drop_table("audit_log")
    op.drop_table("order_routing_index")
    op.drop_table("whatsapp_numbers")
    op.drop_table("catalog_items")
    op.drop_table("users")
    op.drop_table("tenant_connections")
    op.drop_table("tenants")
