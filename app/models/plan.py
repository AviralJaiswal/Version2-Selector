from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Plan(Base):
    __tablename__ = "plans"
    plan_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    speed_mbps: Mapped[int] = mapped_column(Integer)
    price_inr: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    min_speed_required: Mapped[int] = mapped_column(Integer, default=0)

