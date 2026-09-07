from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.api import AppointmentRequest, AppointmentData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.appointment_service import available_slots, select_slot
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Appointment API"])
legacy_router = APIRouter(tags=["Legacy Appointment API"])


@router.post("/appointments", response_model=ResponseEnvelope[AppointmentData])
@trace
def manage_appointment(request: AppointmentRequest, db: Session = Depends(get_db)):
    """Step 5: Appointment API - List or select installation appointment slots."""
    context = session_store.get(request.session_id)
    fdh_id = request.fdh_id or context.get("qualified_address", {}).get("fdh_id") or "FDH-CHENNAI-01"
    
    if request.slot_id:
        try:
            appointment = select_slot(db, request.slot_id, fdh_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session_store.update(request.session_id, {"appointment": appointment})
        return success_response(appointment, message="Appointment slot reserved successfully")
    
    slots = available_slots(db, fdh_id)
    data = {"fdh_id": fdh_id, "slots": slots}
    return success_response(data, message="Available appointment slots retrieved")


@router.post("/appointments/availability")
@trace
def check_appointment_availability(request: AppointmentRequest, db: Session = Depends(get_db)):
    """API 05: POST /api/v1/appointments/availability - Check technician availability slots."""
    context = session_store.get(request.session_id)
    fdh_id = request.fdh_id or context.get("qualified_address", {}).get("fdh_id") or "FDH-CHENNAI-01"
    slots = available_slots(db, fdh_id)
    return success_response({"slots": slots, "fdh_id": fdh_id}, message="Available slots retrieved")


@legacy_router.post("/appointment-slots")
@trace
def appointment_slots_legacy(request: AppointmentRequest, db: Session = Depends(get_db)):
    context = session_store.get(request.session_id)
    fdh_id = context.get("qualified_address", {}).get("fdh_id") or "FDH-CHENNAI-01"
    return success_response({"slots": available_slots(db, fdh_id)})


@legacy_router.post("/select-appointment")
@trace
def select_appointment_legacy(request: AppointmentRequest, db: Session = Depends(get_db)):
    context = session_store.get(request.session_id)
    fdh_id = context.get("qualified_address", {}).get("fdh_id") or "FDH-CHENNAI-01"
    try:
        appointment = select_slot(db, request.slot_id, fdh_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session_store.update(request.session_id, {"appointment": appointment})
    return success_response(appointment)
