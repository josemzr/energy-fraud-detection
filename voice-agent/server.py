"""Real-time voice agent server (Quart) for the Energy Fraud Detection demo.

Exposes:
  GET  /                      -> static web client (mic test)
  WS   /web/ws                -> browser audio <-> Voice Live
  WS   /acs/ws                -> ACS phone audio <-> Voice Live
  POST /acs/incomingcall      -> ACS EventGrid incoming-call webhook
  POST /acs/callbacks/<id>    -> ACS call callbacks

ACS is optional: if ACS_CONNECTION_STRING is not set, the web client still works.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from quart import Quart, request, websocket

from app.handler.acs_media_handler import ACSMediaHandler

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s"
)
logger = logging.getLogger("voice-agent")

app = Quart(__name__)

# Voice Live (Foundry resource hosting the realtime model). API keys may be disabled
# by policy on the resource, so leave AZURE_VOICE_LIVE_API_KEY empty to use Entra ID
# (az login locally / managed identity in Azure).
app.config["AZURE_VOICE_LIVE_API_KEY"] = os.getenv("AZURE_VOICE_LIVE_API_KEY", "")
app.config["AZURE_VOICE_LIVE_ENDPOINT"] = os.getenv("AZURE_VOICE_LIVE_ENDPOINT", "")
# Voice Live uses the native model name (e.g. gpt-realtime), not a deployment name.
app.config["VOICE_LIVE_MODEL"] = os.getenv("VOICE_LIVE_MODEL", "gpt-realtime")
app.config["AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID"] = os.getenv(
    "AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID", ""
)
# ACS (optional — only needed for phone calls / email summaries)
app.config["ACS_CONNECTION_STRING"] = os.getenv("ACS_CONNECTION_STRING", "")
app.config["ACS_DEV_TUNNEL"] = os.getenv("ACS_DEV_TUNNEL", "")

# Lazily create the ACS event handler only when configured.
acs_handler = None
if app.config["ACS_CONNECTION_STRING"]:
    from app.handler.acs_event_handler import AcsEventHandler

    acs_handler = AcsEventHandler(app.config)
    logger.info("ACS event handler enabled (phone calls available).")
else:
    logger.warning("ACS_CONNECTION_STRING not set — phone calls disabled, web client only.")


@app.route("/acs/incomingcall", methods=["POST"])
async def incoming_call_handler():
    """Handles initial incoming call event from EventGrid."""
    if acs_handler is None:
        return {"error": "ACS not configured"}, 503
    events = await request.get_json()
    host_url = request.host_url.replace("http://", "https://", 1).rstrip("/")
    return await acs_handler.process_incoming_call(events, host_url, app.config)


@app.route("/acs/callbacks/<context_id>", methods=["POST"])
async def acs_event_callbacks(context_id):
    """Handles ACS event callbacks for call connection and streaming events."""
    if acs_handler is None:
        return {"error": "ACS not configured"}, 503
    raw_events = await request.get_json()
    return await acs_handler.process_callback_events(context_id, raw_events, app.config)


@app.websocket("/acs/ws")
async def acs_ws():
    """WebSocket endpoint for ACS to send audio to Voice Live."""
    logger.info("Incoming ACS WebSocket connection")
    handler = ACSMediaHandler(app.config)
    await handler.init_incoming_websocket(websocket, is_raw_audio=False)
    asyncio.create_task(handler.connect())
    try:
        while True:
            msg = await websocket.receive()
            await handler.acs_to_voicelive(msg)
    except Exception:
        logger.exception("ACS WebSocket connection closed")


@app.websocket("/web/ws")
async def web_ws():
    """WebSocket endpoint for web clients to send audio to Voice Live."""
    logger.info("Incoming Web WebSocket connection")
    handler = ACSMediaHandler(app.config)
    await handler.init_incoming_websocket(websocket, is_raw_audio=True)
    asyncio.create_task(handler.connect())
    try:
        while True:
            msg = await websocket.receive()
            await handler.web_to_voicelive(msg)
    except Exception:
        logger.exception("Web WebSocket connection closed")


@app.route("/")
async def index():
    """Serves the static web client."""
    return await app.send_static_file("index.html")


@app.route("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
