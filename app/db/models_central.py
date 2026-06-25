import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, new_uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="provisioning", nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    connection: Mapped["TenantConnection | None"] = relationship(back_populates="tenant", uselist=False)
    catalog_items: Mapped[list["CatalogItem"]] = relationship(back_populates="tenant")
    users: Mapped[list["User"]] = relationship(back_populates="tenant")


class TenantConnection(Base, TimestampMixin):
    __tablename__ = "tenant_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), unique=True
    )
    db_host: Mapped[str] = mapped_column(String(255), nullable=False)
    db_port: Mapped[int] = mapped_column(Integer, default=5432)
    db_name: Mapped[str] = mapped_column(String(128), nullable=False)
    db_role: Mapped[str] = mapped_column(String(128), nullable=False)
    db_password_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pool_class: Mapped[str] = mapped_column(String(32), default="default")

    tenant: Mapped["Tenant"] = relationship(back_populates="connection")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant | None"] = relationship(back_populates="users")


class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (Index("ix_catalog_items_tenant_available", "tenant_id", "is_available"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    tenant_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="catalog_items")


class WhatsAppNumber(Base):
    __tablename__ = "whatsapp_numbers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class OrderRoutingIndex(Base):
    __tablename__ = "order_routing_index"
    __table_args__ = (
        Index("ix_routing_tenant_status_placed", "tenant_id", "status", "placed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="greeting")
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
