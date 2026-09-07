from datetime import date as date_type
from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AppointmentSlot(Base):
    __tablename__ = "appointment_slots"
    slot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    date: Mapped[date_type] = mapped_column(Date)
    time_window: Mapped[str] = mapped_column(String(40))
    fdh_id: Mapped[str] = mapped_column(String(40), index=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
