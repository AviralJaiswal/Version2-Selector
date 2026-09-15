from datetime import datetime
from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Order(Base):
    __tablename__ = "orders"
    order_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    plan_id: Mapped[str] = mapped_column(String(30))
    service_pincode: Mapped[str] = mapped_column(String(6))
    payment_status: Mapped[str] = mapped_column(String(30))
    amount_inr: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

