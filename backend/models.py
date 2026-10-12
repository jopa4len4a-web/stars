from sqlalchemy import String, Integer, DateTime, Text, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[str] = mapped_column(String(40), index=True)
    telegram_username: Mapped[str] = mapped_column(String(100), default="")
    recipient_username: Mapped[str] = mapped_column(String(100))
    stars: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2))
    total_price: Mapped[float] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(40), default="created")
    provider_reference: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
