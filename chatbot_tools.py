import os
from datetime import datetime, timezone

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
GOOGLE_TOKEN_FILE = os.path.join(BASE_DIR, "token.json")
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

search_tool = DuckDuckGoSearchRun()


def get_google_calendar_service():
    """Build an authenticated Google Calendar API service using local OAuth token storage."""
    creds = None

    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, GOOGLE_CALENDAR_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE,
                GOOGLE_CALENDAR_SCOPES,
            )
            creds = flow.run_local_server(port=0)

        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _normalize_attendees(attendees):
    """Convert attendee email strings into Calendar API attendee objects."""
    if not attendees:
        return []

    normalized = []
    for attendee in attendees:
        if not attendee:
            continue
        if isinstance(attendee, str):
            normalized.append({"email": attendee})
        elif isinstance(attendee, dict) and attendee.get("email"):
            normalized.append({"email": attendee["email"]})
    return normalized


@tool
def calculator(first_num: float, second_num: float, operation: str) -> dict:
    """A simple calculator tool that can perform basic arithmetic operations."""
    if operation == "add":
        result = first_num + second_num
    elif operation == "subtract":
        result = first_num - second_num
    elif operation == "multiply":
        result = first_num * second_num
    elif operation == "divide":
        if second_num == 0:
            return {"error": "Error: Division by zero is undefined."}
        result = first_num / second_num
    else:
        return {"error": "Invalid operation. Supported operations are: add, subtract, multiply, divide."}
    return {"first_num": first_num, "second_num": second_num, "operation": operation, "result": result}


@tool
def get_stock_price(symbol: str) -> dict:
    """
    Fetch latest stock price for a given symbol (e.g. 'AAPL', 'TSLA') using Alpha Vantage.
    """
    api_key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not api_key:
        return {"error": "ALPHAVANTAGE_API_KEY is not configured."}

    r = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "GLOBAL_QUOTE",
            "symbol": symbol,
            "apikey": api_key,
        },
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


@tool
def schedule_calendar_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    timezone: str = "UTC",
    calendar_id: str = "primary",
    attendees: list[str] | None = None,
) -> dict:
    """Schedule a Google Calendar event."""
    try:
        service = get_google_calendar_service()
        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": timezone},
            "end": {"dateTime": end_time, "timeZone": timezone},
            "attendees": _normalize_attendees(attendees),
        }

        if not event_body["attendees"]:
            event_body.pop("attendees")

        created_event = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body, sendUpdates="none")
            .execute()
        )

        return {
            "ok": True,
            "event_id": created_event.get("id"),
            "html_link": created_event.get("htmlLink"),
            "calendar_id": calendar_id,
            "summary": summary,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": timezone,
            "attendees": attendees or [],
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "summary": summary,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": timezone,
            "calendar_id": calendar_id,
            "attendees": attendees or [],
        }


@tool
def list_upcoming_calendar_events(
    max_results: int = 10,
    calendar_id: str = "primary",
) -> dict:
    """List upcoming Google Calendar events from the chosen calendar."""
    try:
        service = get_google_calendar_service()
        now = datetime.now(timezone.utc).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=now,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        simplified_events = []
        for event in events:
            simplified_events.append(
                {
                    "id": event.get("id"),
                    "summary": event.get("summary", "(No title)"),
                    "start": event.get("start", {}),
                    "end": event.get("end", {}),
                    "html_link": event.get("htmlLink"),
                    "location": event.get("location"),
                    "attendees": event.get("attendees", []),
                }
            )

        return {
            "ok": True,
            "calendar_id": calendar_id,
            "count": len(simplified_events),
            "events": simplified_events,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "calendar_id": calendar_id}


@tool
def delete_calendar_event(calendar_event_id: str, calendar_id: str = "primary") -> dict:
    """Delete a calendar event by event ID."""
    try:
        service = get_google_calendar_service()
        service.events().delete(calendarId=calendar_id, eventId=calendar_event_id).execute()
        return {"ok": True, "calendar_id": calendar_id, "event_id": calendar_event_id, "deleted": True}
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "calendar_id": calendar_id,
            "event_id": calendar_event_id,
        }


@tool
def reschedule_calendar_event(
    calendar_event_id: str,
    calendar_id: str = "primary",
    summary: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    timezone: str | None = None,
    attendees: list[str] | None = None,
) -> dict:
    """Update an existing calendar event's time, title, description, and attendees."""
    try:
        service = get_google_calendar_service()
        existing_event = service.events().get(calendarId=calendar_id, eventId=calendar_event_id).execute()

        if summary is not None:
            existing_event["summary"] = summary
        if description is not None:
            existing_event["description"] = description
        if start_time is not None:
            existing_event.setdefault("start", {})["dateTime"] = start_time
            if timezone is not None:
                existing_event["start"]["timeZone"] = timezone
        if end_time is not None:
            existing_event.setdefault("end", {})["dateTime"] = end_time
            if timezone is not None:
                existing_event["end"]["timeZone"] = timezone
        if timezone is not None:
            existing_event.setdefault("start", {}).setdefault("timeZone", timezone)
            existing_event.setdefault("end", {}).setdefault("timeZone", timezone)
        if attendees is not None:
            normalized_attendees = _normalize_attendees(attendees)
            if normalized_attendees:
                existing_event["attendees"] = normalized_attendees
            elif "attendees" in existing_event:
                existing_event.pop("attendees")

        updated_event = (
            service.events()
            .update(calendarId=calendar_id, eventId=calendar_event_id, body=existing_event, sendUpdates="none")
            .execute()
        )

        return {
            "ok": True,
            "calendar_id": calendar_id,
            "event_id": calendar_event_id,
            "html_link": updated_event.get("htmlLink"),
            "summary": updated_event.get("summary"),
            "start": updated_event.get("start", {}),
            "end": updated_event.get("end", {}),
            "attendees": updated_event.get("attendees", []),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "calendar_id": calendar_id,
            "event_id": calendar_event_id,
        }


tools = [
    calculator,
    get_stock_price,
    search_tool,
    schedule_calendar_event,
    list_upcoming_calendar_events,
    delete_calendar_event,
    reschedule_calendar_event,
]
tool_node = ToolNode(tools)
