from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field

# --- Shared Base Models ---


class CustomerInput(BaseModel):
    customer_id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    existing_pincode: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class StructuredFields(BaseModel):
    customer: Optional[CustomerInput] = None
    selected_plan: Optional[dict] = None
    pincode: Optional[str] = None
    street_address: Optional[str] = None
    slot_id: Optional[str] = None
    is_existing_customer: Optional[bool] = None
    action: Optional[str] = None
    language: Optional[str] = None
    phone: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Step 1: Session Schemas ---


class SessionRequest(BaseModel):
    session_id: Optional[str] = None


class SessionData(BaseModel):
    session_id: str
    message: str
    status: str = "active"


# --- Step 2: Address Qualification Schemas ---


class AddressQualificationRequest(BaseModel):
    session_id: str
    pincode: str = Field(..., min_length=6, max_length=6, description="6-digit postal PIN code")
    street_address: Optional[str] = Field(default=None, description="Full street address for 2-step location verification")


class AddressQualificationData(BaseModel):
    found: bool
    serviceable: bool
    pincode: str
    street_address: Optional[str] = None
    formatted_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    region: Optional[str] = None
    region_type: Optional[str] = None
    fdh_id: Optional[str] = None
    mst_id: Optional[str] = None
    olt_id: Optional[str] = None
    max_speed_available_mbps: Optional[int] = None
    requires_full_address: Optional[bool] = False
    address_qualified: Optional[bool] = False
    message: Optional[str] = None


# --- Step 3: Recommendation Schemas ---


class RecommendRequest(BaseModel):
    session_id: str
    preference: Optional[str] = Field(default=None, description="Usage preference e.g. gaming, streaming, work")
    pincode: Optional[str] = None


class PlanOut(BaseModel):
    plan_id: str
    name: str
    speed_mbps: int
    price_inr: int
    type: str
    reason: Optional[str] = None


class PlanRecommendationData(BaseModel):
    plans: List[PlanOut]
    count: int
    message: Optional[str] = None


# --- Step 4: Customer Details Schemas ---


class CustomerRequest(BaseModel):
    session_id: str
    customer: CustomerInput


class CustomerData(BaseModel):
    customer_id: Optional[str] = None
    name: str
    phone: str
    email: EmailStr
    existing_pincode: Optional[str] = None


# --- Step 5: Service Appointment Schemas ---


class AppointmentRequest(BaseModel):
    session_id: str
    slot_id: Optional[str] = None
    fdh_id: Optional[str] = None


class AppointmentData(BaseModel):
    slot_id: Optional[str] = None
    date: Optional[str] = None
    time_window: Optional[str] = None
    fdh_id: Optional[str] = None
    slots: Optional[List[dict]] = None


# --- Step 6: Payment Schemas ---


class PaymentRequest(BaseModel):
    session_id: str
    plan_id: str


class PaymentConfirmRequest(BaseModel):
    session_id: str
    confirmation_code: Optional[str] = "DEMO-PAID"


class PaymentData(BaseModel):
    purl: Optional[str] = None
    session_id: str
    amount_inr: int
    status: str
    confirmation_code: Optional[str] = None


# --- Step 7: Order Creation Schemas ---


class OrderRequest(BaseModel):
    session_id: str


class OrderData(BaseModel):
    order_id: str
    status: str
    amount_inr: int
    plan: dict
    service_address: dict
    appointment: dict


# --- Step 8: RAG Assistance Schemas ---


class RAGQueryRequest(BaseModel):
    session_id: str
    message: str = Field(default="", max_length=1000)
    quick_action: Optional[str] = Field(default=None, max_length=40)
    structured_fields: Optional[StructuredFields] = None


class RAGQueryData(BaseModel):
    answer: str
    mode: str
    evidence: List[dict] = Field(default_factory=list)
    sources: List[dict] = Field(default_factory=list)
    intent: Optional[str] = None
    workflow_state: Optional[str] = None
    recommended_plan: Optional[dict] = None
    recommended_followups: List[str] = Field(default_factory=list)
    updated_state: dict = Field(default_factory=dict)
    # Existing-customer flow (plan upgrade/downgrade)
    current_plan: Optional[dict] = None
    upgrade_options: Optional[List[dict]] = None
    downgrade_options: Optional[List[dict]] = None
    proposed_plan: Optional[dict] = None
    catalog_plans: Optional[List[dict]] = None

    model_config = ConfigDict(populate_by_name=True)


# --- Legacy Aliases for Backwards Compatibility ---
WelcomeRequest = SessionRequest
PincodeRequest = AddressQualificationRequest
AddressRequest = BaseModel
