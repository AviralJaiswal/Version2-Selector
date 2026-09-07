from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.api import CustomerRequest, CustomerData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.customer_service import find_or_validate
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Customer API"])
legacy_router = APIRouter(tags=["Legacy Customer API"])


@router.post("/customers", response_model=ResponseEnvelope[CustomerData])
@trace
def save_customer_details(request: CustomerRequest, db: Session = Depends(get_db)):
    """Step 4: Customer Details API - Capture and validate customer contact details."""
    try:
        data = find_or_validate(db, **request.customer.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    session_store.update(request.session_id, {"customer": data})
    return success_response(data, message="Customer details saved successfully")


@router.get("/customers/{customer_id}")
@trace
def get_customer_details(customer_id: str, db: Session = Depends(get_db)):
    """API 03: GET /api/v1/customers/{customerId} - Retrieve account history from CRM."""
    from app.models.customer import Customer
    from sqlalchemy import select
    cust = db.scalars(select(Customer).where(Customer.customer_id == customer_id)).first()
    if not cust:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    data = {
        "customerId": cust.customer_id,
        "firstName": cust.name.split()[0] if cust.name else "",
        "lastName": cust.name.split()[-1] if len(cust.name.split()) > 1 else "",
        "email": cust.email,
        "phone": cust.phone,
        "customerType": "EXISTING" if cust.current_plan_id else "NEW",
        "accountStatus": cust.subscription_status,
        "existingServices": [cust.current_plan_id] if cust.current_plan_id else []
    }
    return success_response(data, message="Customer profile retrieved successfully")


@legacy_router.post("/customer-details")
@trace
def customer_details_legacy(request: CustomerRequest, db: Session = Depends(get_db)):
    try:
        data = find_or_validate(db, **request.customer.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_store.update(request.session_id, {"customer": data})
    return success_response(data)
