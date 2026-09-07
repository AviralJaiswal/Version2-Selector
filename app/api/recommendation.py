from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas.api import RecommendRequest, PlanRecommendationData
from app.schemas.envelope import ResponseEnvelope, success_response
from app.services.plan_service import recommend
from app.chat.session import session_store
from app.utils.trace import trace, trace_async

router = APIRouter(prefix="/api/v1", tags=["Recommendation API"])
legacy_router = APIRouter(tags=["Legacy Recommendation API"])


def _has_complete_qualified_address(addr: dict) -> bool:
    return bool(
        addr
        and addr.get("serviceable")
        and addr.get("address_qualified")
        and addr.get("pincode")
        and (addr.get("street_address") or addr.get("formatted_address"))
    )


def _address_required_response() -> dict:
    return {"plans": [], "count": 0, "message": "Please qualify your complete street address and PIN code before viewing regional plans."}


@router.get("/plans/recommendations", response_model=ResponseEnvelope[PlanRecommendationData])
@trace
def get_plan_recommendations(
    session_id: str = Query(..., description="Session identifier"),
    preference: Optional[str] = Query(None, description="Plan preference e.g. gaming, streaming, work"),
    pincode: Optional[str] = Query(None, description="Optional pincode filter"),
    db: Session = Depends(get_db)
):
    """Step 3: Recommendation API - Recommend plans matching geographical region and preference."""
    context = session_store.get(session_id)
    addr = context.get("qualified_address") or {}

    if pincode and not addr.get("pincode"):
        from app.services.address_service import qualify
        addr = qualify(db, pincode)
        session_store.update(session_id, {"qualified_address": addr, "pincode": pincode})

    if addr and not addr.get("serviceable"):
        res_data = {"plans": [], "count": 0, "message": "Please qualify a serviceable address first."}
        return success_response(res_data, message="Address is unserviceable")

    if not _has_complete_qualified_address(addr):
        res_data = _address_required_response()
        session_store.update(session_id, {"recommended_plans": [], "catalog_plans": []})
        return success_response(res_data, message=res_data["message"])

    state_or_region = addr.get("state") or addr.get("region") or addr.get("city")
    max_speed = addr.get("max_speed_available_mbps") if addr else None
    plans = recommend(db, max_speed=max_speed, preference=preference, state_or_region=state_or_region)
    session_store.update(session_id, {"recommended_plans": plans})
    
    res_data = {
        "plans": plans,
        "count": len(plans),
        "message": f"Retrieved {len(plans)} regional plans for {state_or_region or 'your area'}."
    }
    return success_response(res_data, message="Regional plans retrieved successfully")


@router.post("/recommendations/plans")
@trace
def post_plan_recommendations(request: RecommendRequest, db: Session = Depends(get_db)):
    """API 04: POST /api/v1/recommendations/plans - Calculate optimal plans based on qualification and requirements."""
    context = session_store.get(request.session_id)
    addr = context.get("qualified_address") or {}
    if not _has_complete_qualified_address(addr):
        res_data = _address_required_response()
        session_store.update(request.session_id, {"recommended_plans": [], "catalog_plans": []})
        return success_response({
            "recommendationId": f"REC-{request.session_id[:8]}",
            **res_data,
        }, message=res_data["message"])

    state_or_region = addr.get("state") or addr.get("region") or addr.get("city")
    plans = recommend(db, addr.get("max_speed_available_mbps"), request.preference, state_or_region=state_or_region)
    session_store.update(request.session_id, {"recommended_plans": plans})
    return success_response({
        "recommendationId": f"REC-{request.session_id[:8]}",
        "plans": plans
    }, message="Plan recommendations generated")


@legacy_router.post("/recommend-plan")
@trace
def recommend_plan_legacy(request: RecommendRequest, db: Session = Depends(get_db)):
    context = session_store.get(request.session_id)
    addr = context.get("qualified_address") or {}
    if not addr.get("serviceable"):
        return success_response({"plans": [], "message": "Please qualify a serviceable address first."})
    if not _has_complete_qualified_address(addr):
        res_data = _address_required_response()
        session_store.update(request.session_id, {"recommended_plans": [], "catalog_plans": []})
        return success_response(res_data, message=res_data["message"])
    state_or_region = addr.get("state") or addr.get("region") or addr.get("city")
    plans = recommend(db, addr.get("max_speed_available_mbps"), request.preference, state_or_region=state_or_region)
    session_store.update(request.session_id, {"recommended_plans": plans})
    return success_response({"plans": plans})
