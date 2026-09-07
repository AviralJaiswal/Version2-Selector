from pydantic import BaseModel, EmailStr, Field


class SessionRequest(BaseModel):
    session_id: str | None = None


class CustomerInput(BaseModel):
    customer_id: str | None = None
    name: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    existing_pincode: str | None = None


class PlanOut(BaseModel):
    plan_id: str
    name: str
    speed_mbps: int
    price_inr: int
    type: str
    reason: str | None = None

