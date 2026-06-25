import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, new_uuid


class RestaurantProfile(Base):
    __tablename__ = "restaurant_profile"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="PKR")
    business_hours: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MenuCategory(Base):
    __tablename__ = "menu_categories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    items: Mapped[list["MenuItem"]] = relationship(back_populates="category")


class MenuItem(Base):
    __tablename__ = "menu_items"
    __table_args__ = (Index("ix_menu_items_category_available", "category_id", "is_available"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    category: Mapped["MenuCategory | None"] = relationship(back_populates="items")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    addresses: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_placed", "status", "placed_at"),
        Index("ix_orders_placed_at", "placed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), default="whatsapp")
    status: Mapped[str] = mapped_column(String(32), default="placed")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer: Mapped["Customer"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    menu_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    item_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    modifiers: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped["Order"] = relationship(back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="status_history")


class StaffUser(Base):
    __tablename__ = "staff_users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailySalesRollup(Base):
    __tablename__ = "daily_sales_rollup"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    avg_order_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    items_sold: Mapped[int] = mapped_column(Integer, default=0)
    by_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MenuOutbox(Base):
    __tablename__ = "menu_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoutingOutbox(Base):
    __tablename__ = "routing_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
