#!/usr/bin/env python3
"""
One-time setup script: create the Vapi assistant and provision a phone number.

Usage:
    python setup_vapi.py               # create new assistant + Vapi-managed number
    python setup_vapi.py --use-twilio  # create new assistant + Twilio number
    python setup_vapi.py --update      # patch existing assistant (reads VAPI_ASSISTANT_ID from env)

Required env vars:
    VAPI_API_KEY
    PERSONA_API_URL    — public URL of your deployed persona-api

Optional:
    VAPI_ASSISTANT_ID  — set this after first run; used with --update
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN  — required if --use-twilio

Output writes VAPI_ASSISTANT_ID and VAPI_PHONE_NUMBER to stdout for easy copy-paste into .env.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

VAPI_BASE = "https://api.vapi.ai"


# ── Config loading ────────────────────────────────────────────────────────────

def load_vapi_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    cfg.pop("_notes", None)   # strip documentation field before sending
    return cfg


def inject_webhook_url(config: dict, webhook_url: str) -> dict:
    config["serverUrl"] = f"{webhook_url.rstrip('/')}/voice-webhook"
    return config


# ── Assistant CRUD ────────────────────────────────────────────────────────────

def create_assistant(config: dict, api_key: str) -> str:
    resp = httpx.post(
        f"{VAPI_BASE}/assistant",
        headers=_headers(api_key),
        json=config,
        timeout=30.0,
    )
    _raise(resp, "create assistant")
    assistant_id = resp.json()["id"]
    print(f"  Created assistant: {assistant_id}")
    return assistant_id


def update_assistant(config: dict, assistant_id: str, api_key: str) -> str:
    resp = httpx.patch(
        f"{VAPI_BASE}/assistant/{assistant_id}",
        headers=_headers(api_key),
        json=config,
        timeout=30.0,
    )
    _raise(resp, "update assistant")
    print(f"  Updated assistant: {assistant_id}")
    return assistant_id


# ── Phone number provisioning ─────────────────────────────────────────────────

def provision_vapi_number(assistant_id: str, api_key: str) -> str:
    """Buy a Vapi-managed number (no Twilio account needed)."""
    resp = httpx.post(
        f"{VAPI_BASE}/phone-number",
        headers=_headers(api_key),
        json={
            "provider":              "vapi",
            "assistantId":           assistant_id,
            "numberDesiredAreaCode": "415",   # San Francisco — change if you prefer another area code
        },
        timeout=30.0,
    )
    _raise(resp, "provision Vapi number")
    number = resp.json().get("number", resp.json().get("phoneNumber", ""))
    print(f"  Vapi-managed number: {number}")
    return number


def provision_twilio_number(assistant_id: str, api_key: str) -> str:
    """Buy a Twilio number and import it into Vapi."""
    try:
        from twilio.rest import Client as TwilioClient
    except ImportError:
        print("ERROR: twilio package not installed. Run: pip install twilio")
        sys.exit(1)

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token  = os.getenv("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        print("ERROR: TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set for --use-twilio")
        sys.exit(1)

    twilio = TwilioClient(account_sid, auth_token)

    # Find an available US local number
    available = twilio.available_phone_numbers("US").local.list(
        voice_enabled=True, limit=5
    )
    if not available:
        print("ERROR: No Twilio numbers available in the US")
        sys.exit(1)

    # Buy the first available number
    purchased = twilio.incoming_phone_numbers.create(
        phone_number=available[0].phone_number,
        friendly_name="Kanishk AI Persona",
    )
    raw_number = purchased.phone_number
    print(f"  Purchased Twilio number: {raw_number}")

    # Import into Vapi — Vapi reconfigures the Twilio webhook automatically
    resp = httpx.post(
        f"{VAPI_BASE}/phone-number",
        headers=_headers(api_key),
        json={
            "provider":          "twilio",
            "number":            raw_number,
            "twilioAccountSid":  account_sid,
            "twilioAuthToken":   auth_token,
            "assistantId":       assistant_id,
        },
        timeout=30.0,
    )
    _raise(resp, "import Twilio number into Vapi")
    print(f"  Twilio number linked to Vapi: {raw_number}")
    return raw_number


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }


def _raise(resp: httpx.Response, context: str) -> None:
    if not resp.is_success:
        print(f"ERROR in {context}: HTTP {resp.status_code}")
        try:
            print(json.dumps(resp.json(), indent=2))
        except Exception:
            print(resp.text)
        sys.exit(1)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Provision Vapi assistant and phone number")
    parser.add_argument("--config",      default="vapi_config.json", help="Path to vapi_config.json")
    parser.add_argument("--update",      action="store_true",        help="Patch an existing assistant (needs VAPI_ASSISTANT_ID)")
    parser.add_argument("--use-twilio",  action="store_true",        help="Use Twilio for phone number (default: Vapi-managed)")
    args = parser.parse_args()

    api_key      = os.getenv("VAPI_API_KEY")
    webhook_url  = os.getenv("PERSONA_API_URL", "")
    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "")

    if not api_key:
        print("ERROR: VAPI_API_KEY not set")
        sys.exit(1)
    if not webhook_url:
        print("ERROR: PERSONA_API_URL not set (the public URL of your deployed persona-api)")
        sys.exit(1)
    if args.update and not assistant_id:
        print("ERROR: --update requires VAPI_ASSISTANT_ID to be set")
        sys.exit(1)

    # Load config, patch webhook URL
    config = load_vapi_config(args.config)
    config = inject_webhook_url(config, webhook_url)

    print("\n[1/2] Setting up Vapi assistant...")
    if args.update:
        new_id = update_assistant(config, assistant_id, api_key)
    else:
        new_id = create_assistant(config, api_key)

    print("\n[2/2] Provisioning phone number...")
    if args.use_twilio:
        phone = provision_twilio_number(new_id, api_key)
    else:
        phone = provision_vapi_number(new_id, api_key)

    print(f"""
╔══════════════════════════════════════════════════════╗
  Vapi setup complete!

  Assistant ID  : {new_id}
  Phone number  : {phone}
  Webhook URL   : {webhook_url}/voice-webhook

  Add to your .env:
    VAPI_ASSISTANT_ID={new_id}
    VAPI_PHONE_NUMBER={phone}
╚══════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
