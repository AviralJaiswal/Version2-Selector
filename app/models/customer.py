from datetime import date as date_type
from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Customer(Base):
    __tablename__ = "customers"
    customer_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20), index=True)
    email: Mapped[str] = mapped_column(String(150))
    existing_pincode: Mapped[str] = mapped_column(String(6))
    current_plan_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subscription_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    joined_on: Mapped[date_type | None] = mapped_column(Date, nullable=True)

