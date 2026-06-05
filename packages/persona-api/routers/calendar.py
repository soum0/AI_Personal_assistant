import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()
log    = logging.getLogger("persona-api")


class BookingRequest(BaseModel):
    slot:            str  # ISO 8601, e.g. "2026-06-10T14:00:00+05:30"
    attendee_email:  str
    attendee_name:   str


class BookingResponse(BaseModel):
    confirmed:  bool
    event_link: str
    meet_link:  str


class AvailabilityResponse(BaseModel):
    slots: list[dict]


@router.post("/check-availability", response_model=AvailabilityResponse)
async def check_availability() -> AvailabilityResponse:
    from calendar_service import get_available_slots
    try:
        slots = get_available_slots()
        log.info(f"check-availability  →  {len(slots)} open slots")
        return AvailabilityResponse(slots=slots)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.error(f"check-availability error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Calendar service error")


@router.post("/book-meeting", response_model=BookingResponse)
async def book_meeting(req: BookingRequest) -> BookingResponse:
    from calendar_service import book_meeting as _book
    try:
        result = _book(
            slot_iso       = req.slot,
            attendee_email = req.attendee_email,
            attendee_name  = req.attendee_name,
        )
        return BookingResponse(
            confirmed  = result["confirmed"],
            event_link = result["event_link"],
            meet_link  = result["meet_link"],
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        log.error(f"book-meeting error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Booking failed")
