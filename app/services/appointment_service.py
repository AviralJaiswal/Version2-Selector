from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.appointment import AppointmentSlot
from app.utils.trace import trace, trace_async


@trace
def available_slots(db: Session, fdh_id: str, limit: int = 200) -> list[dict]:
    """Return every configured V1 demo slot for the selected FDH.

    Appointment capacity is intentionally not consumed in this prototype, so
    attendees can repeat the guided demo without a previously selected slot
    disappearing from the calendar.
    """
    slots = db.scalars(
        select(AppointmentSlot)
        .where(AppointmentSlot.fdh_id == fdh_id, AppointmentSlot.date >= date.today())
        .order_by(AppointmentSlot.date, AppointmentSlot.time_window)
        .limit(limit)
    )
    return [{"slot_id": slot.slot_id, "date": slot.date.isoformat(), "time_window": slot.time_window,
             "fdh_id": slot.fdh_id} for slot in slots]


@trace
def select_slot(db: Session, slot_id: str, fdh_id: str) -> dict:
    if slot_id.startswith("DEMO-"):
        parts = slot_id.split("-")
        compact_date = next((p for p in parts if len(p) == 8 and p.isdigit()), "")
        time_window = parts[-1] if parts else ""
        selected_date = f"{compact_date[:4]}-{compact_date[4:6]}-{compact_date[6:]}" if compact_date else date.today().isoformat()
        
        slot_labels = {
            "0900_1200": "09:00 AM - 12:00 PM",
            "1200_1500": "12:00 PM - 03:00 PM",
            "1500_1800": "03:00 PM - 06:00 PM",
            "09_00___12_00": "09:00 AM - 12:00 PM",
            "12_00___15_00": "12:00 PM - 03:00 PM",
            "15_00___18_00": "03:00 PM - 06:00 PM",
        }
        display_time = slot_labels.get(time_window)
        if not display_time:
            if "-" in time_window and ":" in time_window:
                display_time = time_window.strip()
            else:
                display_time = "09:00 AM - 12:00 PM"
        return {"slot_id": slot_id, "date": selected_date, "time_window": display_time, "fdh_id": fdh_id}
    
    slot = db.scalar(select(AppointmentSlot).where(
        AppointmentSlot.slot_id == slot_id
    ))
    if not slot:
        return {"slot_id": slot_id, "date": date.today().isoformat(), "time_window": "09:00 - 12:00", "fdh_id": fdh_id}
    return {"slot_id": slot.slot_id, "date": slot.date.isoformat(), "time_window": slot.time_window, "fdh_id": slot.fdh_id}

