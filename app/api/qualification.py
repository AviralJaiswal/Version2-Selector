from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.api import AddressQualificationRequest, AddressQualificationData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.address_service import qualify
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Address Qualification API"])
legacy_router = APIRouter(tags=["Legacy Qualification API"])


@router.post("/qualification/address", response_model=ResponseEnvelope[AddressQualificationData])
@router.post("/addresses/qualify")
@trace
def qualify_address(request: AddressQualificationRequest, db: Session = Depends(get_db)):
    """Step 2: Address Qualification API - Validate pincode (2A) or full street address (2B) via Mapbox / OpenStreetMap."""
    result = qualify(db, request.pincode, request.street_address)
    session_store.update(request.session_id, {
        "qualified_address": result,
        "pincode": request.pincode,
        "serviceable": result.get("serviceable", False),
        "address_qualified": result.get("address_qualified", False)
    })
    from app.services.activity_logger import log_activity
    event_type = "address_geocoded" if request.street_address else "pincode_check"
    log_activity(event_type, request.session_id, {
        "pincode": request.pincode,
        "street_address": request.street_address,
        "serviceable": result.get("serviceable", False),
        "circle": result.get("region") or result.get("state")
    })
    msg = result.get("message") or ("Address qualified successfully" if result.get("serviceable") else "Address is currently unserviceable")
    return success_response(result, message=msg)


@legacy_router.post("/qualify-address")
@trace
def qualify_address_legacy(request: AddressQualificationRequest, db: Session = Depends(get_db)):
    result = qualify(db, request.pincode, request.street_address)
    session_store.update(request.session_id, {
        "qualified_address": result,
        "pincode": request.pincode,
        "serviceable": result.get("serviceable", False),
        "address_qualified": result.get("address_qualified", False)
    })
    return success_response(result, message=result.get("message"))
