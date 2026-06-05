"""
Google Calendar + Gmail service layer.

Credentials setup:
  1. Create an OAuth2 client ID in Google Cloud Console (Desktop app type).
  2. Run the one-time auth flow:
       python -c "
       from google_auth_oauthlib.flow import InstalledAppFlow
       import json
       flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', [
           'https://www.googleapis.com/auth/calendar',
           'https://www.googleapis.com/auth/gmail.send',
       ])
       creds = flow.run_local_server(port=0)
       print(json.dumps({
           'token': creds.token, 'refresh_token': creds.refresh_token,
           'token_uri': creds.token_uri, 'client_id': creds.client_id,
           'client_secret': creds.client_secret, 'scopes': list(creds.scopes),
       }))"
  3. Set the printed JSON as the GOOGLE_CREDENTIALS_JSON env var.
"""
import base64
import json
import logging
import os
import uuid
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

log = logging.getLogger("persona-api")

IST              = ZoneInfo("Asia/Kolkata")
SLOT_MINS        = 30
BUSINESS_START_H = 9   # 9 AM IST
BUSINESS_END_H   = 18  # 6 PM IST

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.send",
]


# ── Credentials ───────────────────────────────────────────────────────────────

def _credentials() -> Credentials:
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError(
            "GOOGLE_CREDENTIALS_JSON is not set. "
            "Run the one-time OAuth2 flow described in calendar_service.py."
        )
    data  = json.loads(raw)
    creds = Credentials(
        token         = data.get("token"),
        refresh_token = data.get("refresh_token"),
        token_uri     = data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id     = data.get("client_id"),
        client_secret = data.get("client_secret"),
        scopes        = SCOPES,
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


# ── Availability ──────────────────────────────────────────────────────────────

def get_available_slots() -> list[dict]:
    """
    Return available 30-min slots in the next 7 days during business hours (Mon–Fri, IST).
    Each slot: {"start": ISO str, "end": ISO str, "label": human-readable str}
    """
    creds  = _credentials()
    svc    = build("calendar", "v3", credentials=creds, cache_discovery=False)
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

    now      = datetime.now(IST).replace(microsecond=0)
    time_min = now
    time_max = now + timedelta(days=7)

    try:
        fb = svc.freebusy().query(body={
            "timeMin":  time_min.isoformat(),
            "timeMax":  time_max.isoformat(),
            "timeZone": "Asia/Kolkata",
            "items":    [{"id": cal_id}],
        }).execute()
    except HttpError as exc:
        log.error(f"freebusy query failed: {exc}")
        raise RuntimeError(f"Google Calendar error: {exc}") from exc

    busy_raw = fb.get("calendars", {}).get(cal_id, {}).get("busy", [])
    busy     = [
        (
            datetime.fromisoformat(b["start"]).astimezone(IST),
            datetime.fromisoformat(b["end"]).astimezone(IST),
        )
        for b in busy_raw
    ]

    slots: list[dict] = []
    # Start from the next whole half-hour
    cursor = _next_half_hour(now)

    while cursor < time_max:
        slot_end = cursor + timedelta(minutes=SLOT_MINS)
        if (
            cursor.weekday() < 5                          # Mon–Fri
            and BUSINESS_START_H <= cursor.hour < BUSINESS_END_H
            and not _overlaps(cursor, slot_end, busy)
        ):
            slots.append({
                "start": cursor.isoformat(),
                "end":   slot_end.isoformat(),
                "label": cursor.strftime("%a %d %b, %I:%M %p IST"),
            })
        cursor += timedelta(minutes=SLOT_MINS)

    return slots


def _next_half_hour(dt: datetime) -> datetime:
    mins = dt.minute
    add  = (30 - mins % 30) % 30 or 30
    return (dt + timedelta(minutes=add)).replace(second=0, microsecond=0)


def _overlaps(start: datetime, end: datetime, busy: list[tuple]) -> bool:
    return any(start < b_end and end > b_start for b_start, b_end in busy)


# ── Booking ───────────────────────────────────────────────────────────────────

def book_meeting(slot_iso: str, attendee_email: str, attendee_name: str) -> dict:
    """
    Create a Google Calendar event with a Meet link.
    sendUpdates='all' automatically mails calendar invites to all attendees.
    Also sends a plain-text confirmation via Gmail.

    Returns: {"confirmed": bool, "event_link": str, "meet_link": str, "event_id": str}
    """
    creds  = _credentials()
    cal    = build("calendar", "v3", credentials=creds, cache_discovery=False)
    cal_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    owner  = os.getenv("OWNER_EMAIL", "")

    start = datetime.fromisoformat(slot_iso).astimezone(IST)
    end   = start + timedelta(minutes=SLOT_MINS)

    event_body = {
        "summary":     f"Chat with {attendee_name}",
        "description": "Discussion with Kanishk Krishna (scheduled via AI persona).",
        "start":       {"dateTime": start.isoformat(), "timeZone": "Asia/Kolkata"},
        "end":         {"dateTime": end.isoformat(),   "timeZone": "Asia/Kolkata"},
        "attendees":   (
            [{"email": attendee_email}]
            + ([{"email": owner}] if owner else [])
        ),
        "conferenceData": {
            "createRequest": {
                "requestId":             str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
        "reminders": {"useDefault": True},
    }

    try:
        created = cal.events().insert(
            calendarId=cal_id,
            body=event_body,
            conferenceDataVersion=1,
            sendUpdates="all",
        ).execute()
    except HttpError as exc:
        log.error(f"Calendar event insert failed: {exc}")
        raise RuntimeError(f"Google Calendar error: {exc}") from exc

    event_link = created.get("htmlLink", "")
    meet_link  = _extract_meet_link(created)

    log.info(f"Booked meeting: {created.get('id')} for {attendee_email} at {start.isoformat()}")

    if owner:
        try:
            _send_confirmation(
                creds          = creds,
                to_email       = attendee_email,
                attendee_name  = attendee_name,
                start          = start,
                meet_link      = meet_link,
                event_link     = event_link,
            )
        except Exception as exc:
            # Confirmation email is best-effort — don't fail the booking
            log.warning(f"Failed to send confirmation email: {exc}")

    return {
        "confirmed":  True,
        "event_link": event_link,
        "meet_link":  meet_link,
        "event_id":   created.get("id", ""),
    }


def _extract_meet_link(event: dict) -> str:
    for ep in event.get("conferenceData", {}).get("entryPoints", []):
        if ep.get("entryPointType") == "video":
            return ep.get("uri", "")
    return event.get("hangoutLink", "")


# ── Gmail confirmation ────────────────────────────────────────────────────────

def _send_confirmation(
    creds,
    to_email:      str,
    attendee_name: str,
    start:         datetime,
    meet_link:     str,
    event_link:    str,
) -> None:
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)

    time_str = start.strftime("%A, %d %B %Y at %I:%M %p IST")

    plain = f"""\
Hi {attendee_name},

Your meeting with Kanishk Krishna is confirmed!

  Date/Time : {time_str}
  Google Meet: {meet_link or "link will arrive in the calendar invite"}
  Calendar   : {event_link}

Looking forward to speaking with you!

Best,
Kanishk's AI Representative
(this email was sent automatically)
"""

    msg            = MIMEMultipart("alternative")
    msg["To"]      = to_email
    msg["Subject"] = f"Meeting confirmed — {start.strftime('%d %b %Y, %I:%M %p IST')}"
    msg.attach(MIMEText(plain, "plain"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()
    log.info(f"Confirmation email sent to {to_email}")
