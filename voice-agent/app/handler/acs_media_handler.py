"""Handles media streaming to Azure Voice Live API via WebSocket.

Adapted for the Energy Fraud Detection demo:
  * Function calling now queries the deployed read-only dashboard API
    (FRAUD_API_BASE_URL) instead of the old hackathon APIM.
  * Voice Live points at the shared Foundry (frauddetozah) + gpt-realtime model.
  * The agent helps an energy customer who received a fraud-investigation notice
    look up the status of their case by their customer id (e.g. CUST1010).
"""

import asyncio
import base64
import json
import logging
import uuid
import os
import aiohttp

from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential
from azure.communication.email.aio import EmailClient
from websockets.asyncio.client import connect as ws_connect
from websockets.typing import Data

logger = logging.getLogger(__name__)


# Read-only Energy Fraud Detection API (the deployed dashboard backend).
FRAUD_API_BASE_URL = os.getenv("FRAUD_API_BASE_URL", "http://localhost:8000").rstrip("/")
# Optional subscription key when the API is fronted by APIM (empty = call directly).
FRAUD_API_SUBSCRIPTION_KEY = os.getenv("FRAUD_API_SUBSCRIPTION_KEY", "")


def _fraud_api_headers() -> dict:
    headers = {"Accept": "application/json"}
    if FRAUD_API_SUBSCRIPTION_KEY:
        headers["Ocp-Apim-Subscription-Key"] = FRAUD_API_SUBSCRIPTION_KEY
    return headers


# --- Function: look up a customer's fraud investigations -------------------
async def get_customer_investigations(customer_id):
    """Return the fraud investigations recorded for a customer id (e.g. CUST1010)."""
    logger.info("🔍 FUNCTION CALLED: get_customer_investigations(%s)", customer_id)
    if not customer_id:
        return {"error": "customer_id is required"}
    url = f"{FRAUD_API_BASE_URL}/api/investigations/{customer_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_fraud_api_headers()) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info("✅ %s investigations for %s", len(data) if isinstance(data, list) else 1, customer_id)
                    return data
                text = await resp.text()
                logger.error("❌ API %s: %s", resp.status, text)
                return {"error": f"API returned status {resp.status}"}
    except Exception as exc:  # pragma: no cover
        logger.exception("❌ ERROR get_customer_investigations: %s", exc)
        return {"error": str(exc)}


# --- Function: detail of a single investigation ----------------------------
async def get_investigation_detail(analysis_id):
    """Return the full detail of one investigation by its analysis_id."""
    logger.info("🔍 FUNCTION CALLED: get_investigation_detail(%s)", analysis_id)
    if not analysis_id:
        return {"error": "analysis_id is required"}
    url = f"{FRAUD_API_BASE_URL}/api/investigation/{analysis_id}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=_fraud_api_headers()) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 404:
                    return {"error": f"No investigation found with id {analysis_id}"}
                text = await resp.text()
                logger.error("❌ API %s: %s", resp.status, text)
                return {"error": f"API returned status {resp.status}"}
    except Exception as exc:  # pragma: no cover
        logger.exception("❌ ERROR get_investigation_detail: %s", exc)
        return {"error": str(exc)}


# --- Function: email a conversation summary to the customer (optional) ------
async def send_support_summary_email(recipient_email, recipient_name, conversation_summary):
    """Send the customer an email summary of the call (via ACS Email)."""
    logger.info("📨 Sending summary email to %s (%s)", recipient_email, recipient_name)
    connection_string = os.getenv("ACS_CONNECTION_STRING")
    sender_address = os.getenv("ACS_SENDER_EMAIL", "")
    if not connection_string or not sender_address:
        return {"success": False, "error": "ACS email not configured (ACS_CONNECTION_STRING / ACS_SENDER_EMAIL)"}

    case_id = str(uuid.uuid4())[:13]
    html_content = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Resumen {case_id}</title></head>
<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
    <p>Estimado/a <strong>{recipient_name}</strong>,</p>
    <p>Gracias por contactarnos. A continuación encontrará un resumen de nuestra conversación de hoy.</p>
    <h3 style="color: #005f75;">Resumen:</h3>
    <div style="background:#f9f9f9; padding:15px; border-left:4px solid #005f75;">{conversation_summary}</div>
    <p>Si necesita más información, no dude en contactarnos.</p>
    <p>Atentamente,<br><strong>El Equipo de Atención al Cliente</strong></p>
</body></html>"""

    message = {
        "senderAddress": sender_address,
        "recipients": {"to": [{"address": recipient_email}]},
        "content": {
            "subject": "Resumen de su consulta sobre la investigación",
            "plainText": (
                f"Estimado/a {recipient_name},\n\nResumen de la conversación:\n\n"
                f"{conversation_summary}\n\nReferencia: {case_id}\n\nAtentamente,\nAtención al Cliente"
            ),
            "html": html_content,
        },
    }
    client = None
    try:
        client = EmailClient.from_connection_string(connection_string)
        poller = await client.begin_send(message)
        result = await poller.result()
        message_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else None)
        await client.close()
        return {"success": True, "operation_id": message_id or "completed", "case_id": case_id}
    except Exception as ex:  # pragma: no cover
        logger.exception("❌ Exception sending email: %s", ex)
        if client:
            try:
                await client.close()
            except Exception:
                pass
        return {"success": False, "error": str(ex)}


async def send_conversation_summary(recipient_email, recipient_name, conversation_summary):
    """Agent-callable wrapper to email the customer a conversation summary."""
    logger.info("🤖 FUNCTION CALLED: send_conversation_summary for %s", recipient_email)
    result = await send_support_summary_email(recipient_email, recipient_name, conversation_summary)
    if result.get("success"):
        return {
            "message": f"Resumen enviado a {recipient_name} ({recipient_email})",
            "operation_id": result.get("operation_id"),
            "case_id": result.get("case_id"),
        }
    return {"error": f"No se pudo enviar el email: {result.get('error')}"}


def session_config():
    """Returns the default session configuration for Voice Live."""
    return {
        "type": "session.update",
        "session": {
            "instructions": """## Rol
Eres "Amaia", asistente de atención al cliente de una comercializadora de energía.
Atiendes a clientes que han recibido una notificación sobre una posible
investigación por uso fraudulento de energía en su suministro.

## Estilo de comunicación
• Habla siempre en español (España).
• Empieza la conversación con: "Hola, soy Amaia, su asistente de atención al cliente. ¿En qué puedo ayudarle hoy?"
• Tono claro, empático y profesional.
• Explica las cosas en lenguaje sencillo, sin tecnicismos internos.
• Nunca reveles reglas internas de detección, umbrales, ni detalles de seguridad del sistema.
• Habla de categorías de riesgo (consumo anómalo, antigüedad de la cuenta, confianza del contador) en vez de la lógica exacta.

## Funciones disponibles
1. **get_customer_investigations**: Busca las investigaciones de un cliente por su ID de cliente (por ejemplo, CUST1010). Es tu punto de partida.
2. **get_investigation_detail**: Obtiene el detalle completo de una investigación concreta por su analysis_id (cuando necesites profundizar).
3. **send_conversation_summary**: Envía por email un resumen de la conversación al cliente. Úsala ANTES de terminar la llamada.

## Flujo
1. Saluda y pregunta al cliente su **ID de cliente** (aparece en la carta/notificación). Si no lo tiene, pide su nombre.
2. Llama a get_customer_investigations con ese ID para localizar su caso.
3. Explica el estado de su investigación en términos sencillos:
   - Si hay un caso de alto riesgo, indícale que su suministro está bajo revisión y por qué (consumo muy por encima de su media, contador con poca confianza, etc.).
   - Si necesitas más detalle, llama a get_investigation_detail con el analysis_id.
4. Aclara el impacto para el cliente y los próximos pasos (revisión en curso, posible inspección, recomendaciones).
5. ANTES de terminar, ofrece enviar un resumen por email: pide nombre y email y llama a send_conversation_summary.

## Comportamiento
• Si la información es ambigua, pide los mínimos datos necesarios.
• Si no puedes revelar algo, dilo y ofrece una explicación de alto nivel y orientación práctica.
• Mantén el equilibrio entre seguridad/cumplimiento y una comunicación tranquilizadora.

## Objetivo
Ayudar al cliente a entender qué ha pasado con su suministro y qué puede hacer, de forma sencilla y tranquilizadora, y dejarle un resumen por escrito por email.""",
            "tools": [
                {
                    "type": "function",
                    "name": "get_customer_investigations",
                    "description": "Busca las investigaciones de fraude registradas para un cliente por su ID de cliente (p. ej. CUST1010). Devuelve estado, nivel de riesgo, score y resumen de cada caso.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "customer_id": {
                                "type": "string",
                                "description": "El ID de cliente, por ejemplo CUST1010.",
                            }
                        },
                        "required": ["customer_id"],
                    },
                },
                {
                    "type": "function",
                    "name": "get_investigation_detail",
                    "description": "Obtiene el detalle completo de una investigación concreta por su analysis_id (perfil del cliente, lectura analizada, decisión y motivos).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "analysis_id": {
                                "type": "string",
                                "description": "El identificador único de la investigación (analysis_id).",
                            }
                        },
                        "required": ["analysis_id"],
                    },
                },
                {
                    "type": "function",
                    "name": "send_conversation_summary",
                    "description": "Envía un resumen de la conversación por email al cliente. Úsala ANTES de terminar la llamada.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "recipient_email": {"type": "string", "description": "Email del cliente."},
                            "recipient_name": {"type": "string", "description": "Nombre del cliente."},
                            "conversation_summary": {
                                "type": "string",
                                "description": "Resumen detallado de la conversación en español: notificación, explicación de la decisión y próximos pasos.",
                            },
                        },
                        "required": ["recipient_email", "recipient_name", "conversation_summary"],
                    },
                },
            ],
            "turn_detection": {
                "type": "azure_semantic_vad",
                "threshold": 0.3,
                "prefix_padding_ms": 200,
                "silence_duration_ms": 200,
                "remove_filler_words": False,
                "interrupt_response": True,
                "auto_truncate": True,
            },
            "input_audio_noise_reduction": {"type": "azure_deep_noise_suppression"},
            "input_audio_echo_cancellation": {"type": "server_echo_cancellation"},
            "voice": {
                "name": "es-ES-Ximena:DragonHDLatestNeural",
                "type": "azure-standard",
                "temperature": 0.8,
            },
        },
    }


# Maps Voice Live function names to the coroutine that executes them and the
# argument keys to extract from the model's JSON arguments.
_FUNCTION_DISPATCH = {
    "get_customer_investigations": (get_customer_investigations, ["customer_id"]),
    "get_investigation_detail": (get_investigation_detail, ["analysis_id"]),
    "send_conversation_summary": (
        send_conversation_summary,
        ["recipient_email", "recipient_name", "conversation_summary"],
    ),
}


class ACSMediaHandler:
    """Manages audio streaming between client and Azure Voice Live API."""

    def __init__(self, config):
        self.endpoint = (config["AZURE_VOICE_LIVE_ENDPOINT"] or "").strip()
        self.model = (config["VOICE_LIVE_MODEL"] or "").strip()
        self.api_key = (config["AZURE_VOICE_LIVE_API_KEY"] or "").strip()
        self.client_id = (config["AZURE_USER_ASSIGNED_IDENTITY_CLIENT_ID"] or "").strip()
        self.send_queue = asyncio.Queue()
        self.ws = None
        self.send_task = None
        self.incoming_websocket = None
        self.is_raw_audio = True
        self.active_response = False

    def _generate_guid(self):
        return str(uuid.uuid4())

    async def connect(self):
        """Connects to Azure Voice Live API via WebSocket."""
        endpoint = (self.endpoint or "").rstrip("/")
        if not endpoint:
            raise ValueError("AZURE_VOICE_LIVE_ENDPOINT is not set")

        api_version = os.getenv("VOICE_LIVE_API_VERSION", "2026-04-10")
        url = f"{endpoint}/voice-live/realtime?api-version={api_version}&model={self.model}"
        if url.startswith("https://"):
            url = "wss://" + url[len("https://"):]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://"):]

        logger.info("[VoiceLive] connecting to %s (model=%s)", url, self.model)
        headers = {"x-ms-client-request-id": self._generate_guid()}

        if self.api_key:
            # Key auth (only works if local auth is enabled on the resource).
            headers["api-key"] = self.api_key
        else:
            # API keys are often disabled by policy -> authenticate with Entra ID.
            # DefaultAzureCredential uses `az login` locally and managed identity in Azure.
            if self.client_id:
                credential = ManagedIdentityCredential(managed_identity_client_id=self.client_id)
            else:
                credential = DefaultAzureCredential()
            token = await credential.get_token("https://cognitiveservices.azure.com/.default")
            headers["Authorization"] = f"Bearer {token.token}"
            await credential.close()

        self.ws = await ws_connect(url, additional_headers=headers)
        logger.info("[VoiceLive] Connected")

        await self._send_json(session_config())
        await self._send_json({"type": "response.create"})

        asyncio.create_task(self._receiver_loop())
        self.send_task = asyncio.create_task(self._sender_loop())

    async def init_incoming_websocket(self, socket, is_raw_audio=True):
        """Sets up incoming ACS/web WebSocket."""
        self.incoming_websocket = socket
        self.is_raw_audio = is_raw_audio

    async def audio_to_voicelive(self, audio_b64: str):
        await self.send_queue.put(
            json.dumps({"type": "input_audio_buffer.append", "audio": audio_b64})
        )

    async def _send_json(self, obj):
        if self.ws:
            await self.ws.send(json.dumps(obj))

    async def _sender_loop(self):
        try:
            while True:
                msg = await self.send_queue.get()
                if self.ws:
                    await self.ws.send(msg)
        except Exception:
            logger.exception("[VoiceLive] Sender loop error")

    async def _dispatch_function_call(self, function_name, arguments, call_id):
        """Execute a tool call and return its output to the model."""
        entry = _FUNCTION_DISPATCH.get(function_name)
        if not entry:
            logger.warning("Unknown function call: %s", function_name)
            result = {"error": f"Unknown function {function_name}"}
        else:
            func, arg_keys = entry
            try:
                args_dict = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
                kwargs = {k: args_dict.get(k) for k in arg_keys}
                result = await func(**kwargs)
            except Exception as exc:  # pragma: no cover
                logger.exception("❌ ERROR executing %s: %s", function_name, exc)
                result = {"error": str(exc)}

        await self._send_json(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                },
            }
        )
        await self._send_json({"type": "response.create"})

    async def _receiver_loop(self):
        """Handles incoming events from the Voice Live WebSocket."""
        try:
            async for message in self.ws:
                event = json.loads(message)
                event_type = event.get("type")

                match event_type:
                    case "session.created":
                        logger.info("[VoiceLive] Session ID: %s", event.get("session", {}).get("id"))

                    case "response.created":
                        self.active_response = True

                    case "response.done":
                        self.active_response = False

                    case "input_audio_buffer.speech_started":
                        # Barge-in: the user started talking. Stop client playback
                        # AND cancel the model's in-flight response so it stops generating.
                        await self.stop_audio()
                        if self.active_response:
                            await self._send_json({"type": "response.cancel"})
                            self.active_response = False

                    case "conversation.item.input_audio_transcription.completed":
                        logger.info("User: %s", event.get("transcript"))

                    case "response.function_call_arguments.done":
                        function_name = event.get("name")
                        arguments = event.get("arguments")
                        call_id = event.get("call_id")
                        logger.info("🤖 FUNCTION CALLING: %s args=%s", function_name, arguments)
                        await self._dispatch_function_call(function_name, arguments, call_id)

                    case "response.audio_transcript.done":
                        transcript = event.get("transcript")
                        logger.info("AI: %s", transcript)
                        await self.send_message(json.dumps({"Kind": "Transcription", "Text": transcript}))

                    case "response.audio.delta":
                        delta = event.get("delta")
                        if self.is_raw_audio:
                            await self.send_message(base64.b64decode(delta))
                        else:
                            await self.voicelive_to_acs(delta)

                    case "error":
                        logger.error("Voice Live Error: %s", event)

                    case _:
                        logger.debug("[VoiceLive] Other event: %s", event_type)
        except Exception:
            logger.exception("[VoiceLive] Receiver loop error")

    async def send_message(self, message: Data):
        try:
            await self.incoming_websocket.send(message)
        except Exception:
            logger.exception("[VoiceLive] Failed to send message")

    async def voicelive_to_acs(self, base64_data):
        try:
            data = {"kind": "AudioData", "audioData": {"data": base64_data}, "stopAudio": None}
            await self.send_message(json.dumps(data))
        except Exception:
            logger.exception("[VoiceLive] Error in voicelive_to_acs")

    async def stop_audio(self):
        """Tell the client to stop/clear playback (barge-in). Format differs by client."""
        if self.is_raw_audio:
            # Web client (index.html) checks `msg.Kind === "StopAudio"`.
            await self.send_message(json.dumps({"Kind": "StopAudio"}))
        else:
            # ACS telephony protocol.
            await self.send_message(
                json.dumps({"kind": "StopAudio", "audioData": None, "stopAudio": {}})
            )

    async def acs_to_voicelive(self, stream_data):
        try:
            data = json.loads(stream_data)
            if data.get("kind") == "AudioData":
                audio_data = data.get("audioData", {})
                if not audio_data.get("silent", True):
                    await self.audio_to_voicelive(audio_data.get("data"))
        except Exception:
            logger.exception("[VoiceLive] Error processing ACS audio")

    async def web_to_voicelive(self, audio_bytes):
        audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        await self.audio_to_voicelive(audio_b64)
