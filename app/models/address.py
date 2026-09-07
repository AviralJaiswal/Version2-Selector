from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Address(Base):
    __tablename__ = "addresses"
    id: Mapped[int] = mapped_column(primary_key=True)
    pincode: Mapped[str] = mapped_column(String(6), index=True)
    city: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(80))
    region_type: Mapped[str] = mapped_column(String(30))
    fdh_id: Mapped[str] = mapped_column(String(40))
    mst_id: Mapped[str] = mapped_column(String(40))
    olt_id: Mapped[str] = mapped_column(String(40))
    serviceable: Mapped[bool] = mapped_column(Boolean, default=False)
    max_speed_available_mbps: Mapped[int] = mapped_column(Integer)

