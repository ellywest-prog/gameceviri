"""
Apex Legends Gerçek Zamanlı Türkçe→İngilizce Ses Çeviri Sunucusu

Kullanım:
    python server.py
    Tarayıcıda http://localhost:8765 aç
"""

import asyncio
import base64
import json
import logging
import queue
import signal
import sys
import threading
import time
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from typing import Optional

import ctypes
import numpy as np
import sounddevice as sd
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("apex-ceviri")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAMPLE_RATE = 24_000          # OpenAI Realtime Translation API requires 24 kHz
CHANNELS = 1                  # Mono
DTYPE = "int16"               # PCM16
CHUNK_DURATION_MS = 100       # Send audio every 100ms
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 2400 samples

OPENAI_TRANSLATE_MODEL = "gpt-realtime-translate"
OPENAI_REALTIME_URL = (
    f"wss://api.openai.com/v1/realtime/translations?model={OPENAI_TRANSLATE_MODEL}"
)
OUTPUT_LANGUAGE = "en"        # Target language (English)
SAFETY_IDENTIFIER = "apex-ceviri-user"  # Stable, privacy-preserving end-user id

COST_PER_MINUTE = 0.034       # USD (approximate, input audio duration)
PTT_KEY = "t"                  # Global push-to-talk key

# Grace period to let OpenAI flush remaining translated audio on disconnect
SESSION_CLOSE_TIMEOUT = 2.0  # seconds


# ---------------------------------------------------------------------------
# Audio Device Helpers
# ---------------------------------------------------------------------------
PREFERRED_API = "Windows DirectSound"
FALLBACK_API = "MME"


def get_audio_devices():
    """Return simplified, deduplicated audio devices for the frontend.

    Only shows Windows DirectSound devices (clean names, no duplicates).
    Marks default devices and auto-detects CABLE virtual devices.
    """
    devices = sd.query_devices()
    defaults = sd.default.device  # (input_idx, output_idx)

    # Group devices by host API
    api_devices = {}
    for i, dev in enumerate(devices):
        api_name = sd.query_hostapis(dev["hostapi"])["name"]
        if api_name not in api_devices:
            api_devices[api_name] = []
        api_devices[api_name].append((i, dev))

    # Pick best API: prefer DirectSound, fallback to MME
    chosen_api = PREFERRED_API
    if chosen_api not in api_devices:
        chosen_api = FALLBACK_API
    if chosen_api not in api_devices:
        # Use whatever is available
        chosen_api = next(iter(api_devices)) if api_devices else None

    if not chosen_api:
        return {"input": [], "output": []}

    input_devices = []
    output_devices = []

    for idx, dev in api_devices[chosen_api]:
        name = dev["name"].strip()

        # Skip "Primary" / generic system mapper devices
        lower = name.lower()
        if any(skip in lower for skip in [
            "birincil", "primary", "mapper", "microsoft ses",
        ]):
            continue

        # Determine if this is the system default
        is_default_in = (idx == defaults[0]) or (
            dev["max_input_channels"] > 0
            and defaults[0] is not None
            and devices[defaults[0]]["name"] in name
        )
        is_default_out = (idx == defaults[1]) or (
            dev["max_output_channels"] > 0
            and defaults[1] is not None
            and devices[defaults[1]]["name"] in name
        )

        # Check if CABLE device
        is_cable = "cable" in lower or "vb-audio" in lower

        # Build display name
        display = name
        tags = []
        if is_cable:
            tags.append("Sanal Kablo")
        if dev["max_input_channels"] > 0 and is_default_in:
            tags.append("Varsayilan")
        if dev["max_output_channels"] > 0 and is_default_out:
            tags.append("Varsayilan")
        if tags:
            display = f"{name} ({', '.join(tags)})"

        info = {
            "index": idx,
            "name": display,
            "is_default": is_default_in or is_default_out,
            "is_cable": is_cable,
        }

        if dev["max_input_channels"] > 0:
            input_devices.append(info)
        if dev["max_output_channels"] > 0:
            output_devices.append(info)

    # Sort: defaults first, then CABLE, then alphabetical
    def sort_key(d):
        return (not d["is_default"], not d["is_cable"], d["name"])

    input_devices.sort(key=sort_key)
    output_devices.sort(key=sort_key)

    return {"input": input_devices, "output": output_devices}


# ---------------------------------------------------------------------------
# Translation Session
# ---------------------------------------------------------------------------
class TranslationSession:
    """Manages a single translation session: mic → OpenAI → virtual cable."""

    def __init__(
        self,
        api_key: str,
        input_device: int,
        output_device: int,
        client_ws: WebSocket,
    ):
        self.api_key = api_key
        self.input_device = input_device
        self.output_device = output_device
        self.client_ws = client_ws

        # State
        self.is_recording = False
        self.is_connected = False
        self.should_stop = False
        self._stopping = False  # Guards against double stop()

        # OpenAI WebSocket
        self.openai_ws: Optional[websockets.WebSocketClientProtocol] = None

        # Set when OpenAI confirms session.closed (graceful shutdown handshake)
        self._closed_event: Optional[asyncio.Event] = None

        # Audio buffers (using thread-safe Jitter Buffer with lock)
        self._audio_out_buffer = bytearray()
        self._audio_out_lock = threading.Lock()
        self._playback_started = False
        self._mic_stream: Optional[sd.InputStream] = None
        self._speaker_stream: Optional[sd.OutputStream] = None
        self._hang_time_task: Optional[asyncio.Task] = None
        self._ws_lock = asyncio.Lock()  # Prevent concurrent WebSocket send races
        
        # Pre-recording lookback buffer to prevent initial syllable cutoff
        self._pre_buffer = bytearray()
        self._pre_buffer_max_bytes = 9600  # 200ms of PCM16 Mono 24kHz audio (24000 * 2 * 0.2)

        # Cost tracking
        self._recording_start: Optional[float] = None
        self._total_seconds: float = 0.0

    # -- Lifecycle -----------------------------------------------------------

    async def start(self):
        """Connect to OpenAI and start audio I/O."""
        try:
            await self._send_status("connecting")

            self._closed_event = asyncio.Event()

            # Connect to OpenAI Realtime Translation API
            # The model is selected via the `?model=` query parameter.
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "OpenAI-Safety-Identifier": SAFETY_IDENTIFIER,
            }

            self.openai_ws = await websockets.connect(
                OPENAI_REALTIME_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                max_size=10 * 1024 * 1024,  # 10 MB
            )

            log.info("OpenAI WebSocket connected (translation endpoint)")

            # Configure session: translate incoming speech to English
            # The translation API only needs the output language; it
            # auto-detects the source language from the audio stream.
            session_config = {
                "type": "session.update",
                "session": {
                    "audio": {
                        "output": {
                            "language": OUTPUT_LANGUAGE,
                        }
                    },
                },
            }
            await self.openai_ws.send(json.dumps(session_config))
            log.info("Session configured: auto-detect → %s", OUTPUT_LANGUAGE.upper())

            # Start continuous input stream (keeps mic active to eliminate open/close latency)
            self._start_input_stream()

            # Start output stream to virtual cable
            self._start_output_stream()

            self.is_connected = True
            await self._send_status("idle")

            # Run receive loop
            await self._receive_loop()

        except websockets.exceptions.InvalidStatusCode as e:
            error_msg = f"OpenAI bağlantı hatası: HTTP {e.status_code}"
            if e.status_code == 401:
                error_msg = "API key geçersiz! Lütfen doğru bir OpenAI API key girin."
            elif e.status_code == 429:
                error_msg = "Rate limit aşıldı. Biraz bekleyip tekrar deneyin."
            log.error(error_msg)
            await self._send_error(error_msg)
        except Exception as e:
            log.error(f"Session error: {e}")
            await self._send_error(str(e))
        finally:
            await self.stop()

    async def stop(self):
        """Clean up all resources.

        Performs a graceful shutdown of the translation session by sending
        ``session.close`` and waiting for ``session.closed`` (with a timeout)
        so any remaining translated audio/transcripts are flushed before the
        WebSocket is closed.
        """
        if self._stopping:
            return
        self._stopping = True

        self.is_connected = False
        self.is_recording = False

        # Stop capturing audio immediately
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

        # Gracefully close the OpenAI translation session.
        # Per the docs, send session.close and keep reading events until
        # session.closed arrives, otherwise pending translated output may be
        # dropped. The receive_loop (running in this same task) will set
        # _closed_event when it sees session.closed.
        if self.openai_ws is not None:
            ws = self.openai_ws
            self.openai_ws = None  # receive_loop treats None as "not connected"

            try:
                await ws.send(json.dumps({"type": "session.close"}))
            except Exception as e:
                log.debug(f"Failed to send session.close: {e}")

            closed_evt = self._closed_event
            if closed_evt is not None:
                try:
                    await asyncio.wait_for(
                        closed_evt.wait(), timeout=SESSION_CLOSE_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    log.debug("session.closed not received in time, closing socket")
                except Exception:
                    pass

            try:
                await ws.close()
            except Exception:
                pass

        # Stop the speaker stream last so queued audio can drain
        if self._speaker_stream is not None:
            try:
                self._speaker_stream.stop()
                self._speaker_stream.close()
            except Exception:
                pass
            self._speaker_stream = None

        self.should_stop = True
        await self._send_status("disconnected")
        log.info("Session stopped")

    # -- Push-to-Talk --------------------------------------------------------

    async def ptt_start(self):
        """Start recording from microphone. Cancels any pending delayed stop."""
        if not self.is_connected:
            return

        # If we were in the middle of hang time delay, cancel it and keep recording
        if self._hang_time_task is not None and not self._hang_time_task.done():
            self._hang_time_task.cancel()
            self._hang_time_task = None
            self.is_recording = True
            await self._send_status("recording")
            log.info("🎤 PTT re-engaged during hang time")
            return

        if self.is_recording:
            return

        self.is_recording = True
        self._recording_start = time.time()
        await self._send_status("recording")

        # Clear old audio buffer to prevent ghosting from previous translation
        with self._audio_out_lock:
            self._audio_out_buffer.clear()
            self._playback_started = False

        log.info("🎤 Recording started (streaming active)")

    async def ptt_stop(self):
        """Stop recording with a 500ms delay to prevent cutting off words."""
        if not self.is_recording:
            return

        self.is_recording = False
        log.info("⏹ ... Key released. Waiting 500ms hang time to capture trailing audio...")
        self._hang_time_task = asyncio.create_task(self._ptt_stop_delayed())

    async def _ptt_stop_delayed(self):
        """Perform actual stream shutdown after hang time delay."""
        try:
            await asyncio.sleep(0.5)  # 500ms trailing audio window
            
            # Track recording duration
            if self._recording_start is not None:
                duration = time.time() - self._recording_start
                self._total_seconds += duration
                self._recording_start = None

                # Send cost update
                total_minutes = self._total_seconds / 60
                cost = total_minutes * COST_PER_MINUTE
                await self._send_cost(total_minutes, cost)

            await self._send_status("translating")
            log.info("⏹ Hang time complete. Recording stopped, translating...")
            asyncio.create_task(self._translating_timeout())
        except asyncio.CancelledError:
            # Re-engaged during sleep
            pass

    async def _translating_timeout(self):
        """Safeguard: return to idle state after 5 seconds of translating to prevent hanging."""
        await asyncio.sleep(5.0)
        if not self.should_stop and not self.is_recording:
            log.info("⏰ Translation timeout reached, returning to idle state.")
            await self._send_status("idle")

    # -- Audio I/O -----------------------------------------------------------

    def _start_input_stream(self):
        """Start capturing audio from the real microphone."""
        loop = asyncio.get_event_loop()

        def mic_callback(indata, frames, time_info, status):
            if status:
                log.warning(f"Mic status: {status}")

            audio_bytes = indata.flatten().tobytes()

            if not self.is_recording:
                # Keep last 200ms of audio in lookback buffer
                self._pre_buffer.extend(audio_bytes)
                if len(self._pre_buffer) > self._pre_buffer_max_bytes:
                    del self._pre_buffer[:-self._pre_buffer_max_bytes]
                return

            # If we just transitioned to recording, prepend pre-buffered audio
            if len(self._pre_buffer) > 0:
                pre_data = bytes(self._pre_buffer)
                self._pre_buffer.clear()
                pre_b64 = base64.b64encode(pre_data).decode("utf-8")
                asyncio.run_coroutine_threadsafe(
                    self._send_audio_to_openai(pre_b64), loop
                )

            # Send live audio chunk
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            asyncio.run_coroutine_threadsafe(
                self._send_audio_to_openai(audio_b64), loop
            )

        self._mic_stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=self.input_device,
            blocksize=0,  # Let PortAudio select optimal blocksize for smoother stream
            callback=mic_callback,
        )
        self._mic_stream.start()

    def _start_output_stream(self):
        """Start output stream to virtual cable (VB-Cable)."""

        def speaker_callback(outdata, frames, time_info, status):
            if status:
                log.warning(f"Speaker status: {status}")

            bytes_needed = frames * 2  # 16-bit mono = 2 bytes per sample

            with self._audio_out_lock:
                # Jitter buffer: wait until we have buffered at least 150ms of audio (7200 bytes)
                # before we start playing to absorb network jitter.
                if not self._playback_started:
                    if len(self._audio_out_buffer) >= 7200:
                        self._playback_started = True
                    else:
                        outdata.fill(0)
                        return

                if len(self._audio_out_buffer) >= bytes_needed:
                    data = self._audio_out_buffer[:bytes_needed]
                    del self._audio_out_buffer[:bytes_needed]
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    outdata[:, 0] = audio_array
                else:
                    # Starvation: play whatever is left, then buffer again
                    data = bytes(self._audio_out_buffer)
                    self._audio_out_buffer.clear()
                    self._playback_started = False

                    audio_array = np.frombuffer(data, dtype=np.int16)
                    padded = np.zeros(frames, dtype=np.int16)
                    padded[: len(audio_array)] = audio_array
                    outdata[:, 0] = padded

        self._speaker_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            device=self.output_device,
            blocksize=0,  # Let PortAudio select optimal blocksize for smoother playback
            callback=speaker_callback,
        )
        self._speaker_stream.start()

    async def _send_audio_to_openai(self, audio_b64: str):
        """Send base64 audio chunk to OpenAI translation session."""
        if self.openai_ws is None:
            return
        try:
            # Increment and log audio send counter
            self._send_chunk_count = getattr(self, "_send_chunk_count", 0) + 1
            if self._send_chunk_count % 10 == 0:
                log.info(f"📤 [Ses Gonderimi] OpenAI'ye {self._send_chunk_count} ses paketi gonderildi")

            await self.openai_ws.send(
                json.dumps(
                    {
                        "type": "session.input_audio_buffer.append",
                        "audio": audio_b64,
                    }
                )
            )
        except Exception as e:
            log.error(f"Failed to send audio: {e}")

    # -- OpenAI Event Handling -----------------------------------------------

    async def _receive_loop(self):
        """Process events from the OpenAI translation session.

        Translation sessions emit a different set of events than voice-agent
        sessions. All server events use the ``session.*`` namespace:

          * ``session.created`` / ``session.updated``    – lifecycle acks
          * ``session.output_audio.delta`` / ``.done``   – translated audio
          * ``session.output_transcript.delta`` / ``.done`` – translated text
          * ``session.input_transcript.delta`` / ``.done``  – source (TR) text
          * ``session.closed``                            – graceful close ack
          * ``error``                                     – error from the API
        """
        if self.openai_ws is None:
            return

        try:
            async for message in self.openai_ws:
                if self.should_stop:
                    break

                event = json.loads(message)
                event_type = event.get("type", "")

                # Log all incoming non-audio events to make OpenAI status clear in logs
                if event_type != "session.output_audio.delta":
                    log.info(f"📥 OpenAI Event: {event_type}")

                if event_type == "session.created":
                    log.info("✅ Translation session created")

                elif event_type == "session.updated":
                    log.info("✅ Session config applied (TR → %s)", OUTPUT_LANGUAGE.upper())

                elif event_type == "session.output_audio.delta":
                    # Translated audio chunk (base64 PCM16 24kHz)
                    # Increment and log audio receive counter
                    self._recv_chunk_count = getattr(self, "_recv_chunk_count", 0) + 1
                    if self._recv_chunk_count % 10 == 0:
                        log.info(f"📥 [Ses Alimi] OpenAI'den {self._recv_chunk_count} ses paketi alindi")

                    audio_b64 = event.get("delta", "")
                    if audio_b64:
                        audio_bytes = base64.b64decode(audio_b64)
                        
                        # Decode to np.int16 and stretch to 90% speed (1.11x duration)
                        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
                        if len(audio_array) > 0:
                            stretched_len = int(len(audio_array) / 0.9)
                            new_indices = np.linspace(0, len(audio_array) - 1, stretched_len)
                            stretched_array = np.interp(
                                new_indices, np.arange(len(audio_array)), audio_array
                            ).astype(np.int16)
                            audio_bytes = stretched_array.tobytes()

                        with self._audio_out_lock:
                            self._audio_out_buffer.extend(audio_bytes)

                elif event_type == "session.output_audio.done":
                    log.info("🔊 Translated audio output complete")
                    if not self.is_recording:
                        await self._send_status("idle")

                elif event_type == "session.output_transcript.delta":
                    # English translation text (streaming)
                    text = event.get("delta", "")
                    if text:
                        await self._send_transcript("en", text)

                elif event_type == "session.output_transcript.done":
                    text = event.get("transcript") or event.get("text", "")
                    if text:
                        log.info(f"🔊 [EN] {text}")
                        await self._send_transcript("en_final", text)
                    # Translation for this utterance is complete — go idle
                    # (the translated audio may still be draining to the
                    # speaker, but the server-side work is done).
                    if not self.is_recording:
                        await self._send_status("idle")

                elif event_type == "session.input_transcript.delta":
                    # Turkish source transcript (streaming)
                    text = event.get("delta", "")
                    if text:
                        await self._send_transcript("tr", text)

                elif event_type == "session.input_transcript.done":
                    text = event.get("transcript") or event.get("text", "")
                    if text:
                        log.info(f"📝 [TR] {text}")
                        await self._send_transcript("tr_final", text)

                elif event_type == "session.closed":
                    log.info("🔒 OpenAI session closed (graceful)")
                    if self._closed_event is not None:
                        self._closed_event.set()
                    break

                elif event_type == "error":
                    error_data = event.get("error", {})
                    error_msg = error_data.get("message", "Bilinmeyen hata")
                    log.error(f"OpenAI error: {error_msg}")
                    await self._send_error(error_msg)

                else:
                    log.debug(f"Unhandled event: {event_type}")

        except websockets.exceptions.ConnectionClosed as e:
            log.warning(f"OpenAI connection closed: {e}")
            if self._closed_event is not None:
                self._closed_event.set()
            if not self._stopping:
                await self._send_error("OpenAI bağlantısı koptu. Tekrar bağlanın.")

    # -- Client Communication ------------------------------------------------

    async def _send_status(self, state: str):
        async with self._ws_lock:
            try:
                await self.client_ws.send_json({"type": "status", "state": state})
            except Exception:
                pass

    async def _send_transcript(self, lang: str, text: str):
        async with self._ws_lock:
            try:
                await self.client_ws.send_json(
                    {"type": "transcript", "lang": lang, "text": text}
                )
            except Exception:
                pass

    async def _send_error(self, message: str):
        async with self._ws_lock:
            try:
                await self.client_ws.send_json({"type": "error", "message": message})
            except Exception:
                pass

    async def _send_cost(self, minutes: float, cost_usd: float):
        async with self._ws_lock:
            try:
                await self.client_ws.send_json(
                    {
                        "type": "cost",
                        "minutes": round(minutes, 2),
                        "cost_usd": round(cost_usd, 4),
                    }
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("🎮 Apex Çeviri Sunucusu Başlatıldı")
    log.info("📡 http://localhost:8765 adresinden arayüze ulaşabilirsin")
    yield
    log.info("Sunucu kapatılıyor...")


app = FastAPI(title="Apex Çeviri", lifespan=lifespan)

# Store active sessions
active_sessions: dict[str, TranslationSession] = {}


@app.get("/")
async def index():
    """Serve the web UI."""
    return FileResponse("static/index.html")


@app.get("/api/devices")
async def list_devices():
    """Return available audio devices."""
    return get_audio_devices()


@app.get("/api/test-key")
async def test_api_key(key: str = ""):
    """Test if the given OpenAI API key is valid."""
    if not key or not key.startswith("sk-"):
        return JSONResponse(
            {"valid": False, "message": "API key 'sk-' ile baslamali."},
            status_code=400,
        )

    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
            },
            method="GET",
        )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: urllib.request.urlopen(req, timeout=10),
        )

        if response.status == 200:
            return {"valid": True, "message": "API key gecerli!"}
        else:
            return JSONResponse(
                {"valid": False, "message": f"Beklenmeyen yanit: HTTP {response.status}"},
                status_code=400,
            )
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return JSONResponse(
                {"valid": False, "message": "API key gecersiz! Kontrol edin."},
                status_code=401,
            )
        elif e.code == 429:
            return JSONResponse(
                {"valid": False, "message": "Rate limit asildi. Biraz bekleyin."},
                status_code=429,
            )
        else:
            return JSONResponse(
                {"valid": False, "message": f"OpenAI hatasi: HTTP {e.code}"},
                status_code=400,
            )
    except Exception as e:
        return JSONResponse(
            {"valid": False, "message": f"Baglanti hatasi: {str(e)}"},
            status_code=500,
        )


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """Handle frontend WebSocket connection."""
    global _hotkey_loop
    _hotkey_loop = asyncio.get_running_loop()

    await ws.accept()
    session: Optional[TranslationSession] = None
    session_task: Optional[asyncio.Task] = None
    session_id = str(id(ws))

    log.info(f"Client connected: {session_id}")

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "connect":
                # Start a new translation session
                api_key = data.get("api_key", "").strip()
                input_device = data.get("input_device")
                output_device = data.get("output_device")

                if not api_key:
                    await ws.send_json(
                        {"type": "error", "message": "API key boş olamaz!"}
                    )
                    continue

                if input_device is None or output_device is None:
                    await ws.send_json(
                        {"type": "error", "message": "Mikrofon ve çıkış cihazı seçmelisin!"}
                    )
                    continue

                # Stop existing session if any
                if session is not None:
                    await session.stop()
                    if session_task is not None:
                        session_task.cancel()

                session = TranslationSession(
                    api_key=api_key,
                    input_device=int(input_device),
                    output_device=int(output_device),
                    client_ws=ws,
                )
                active_sessions[session_id] = session
                session_task = asyncio.create_task(session.start())

            elif msg_type == "disconnect":
                if session is not None:
                    await session.stop()
                    if session_task is not None:
                        session_task.cancel()
                    session = None
                    active_sessions.pop(session_id, None)

            elif msg_type == "ptt_start":
                if session is not None:
                    await session.ptt_start()

            elif msg_type == "ptt_stop":
                if session is not None:
                    await session.ptt_stop()

    except WebSocketDisconnect:
        log.info(f"Client disconnected: {session_id}")
    except Exception as e:
        log.error(f"WebSocket error: {e}")
    finally:
        if session is not None:
            await session.stop()
            if session_task is not None:
                session_task.cancel()
            active_sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# Global Hotkey (T key – GetAsyncKeyState Polling to bypass Anti-Cheat)
# ---------------------------------------------------------------------------
_hotkey_loop: Optional[asyncio.AbstractEventLoop] = None
_hotkey_pressed = False


def ptt_polling_loop():
    """Poll the physical state of the PTT key using GetAsyncKeyState.
    This bypasses kernel anti-cheat keyboard hook blocks (e.g. EAC).
    """
    global _hotkey_pressed
    user32 = ctypes.windll.user32
    VK_T = 0x54  # Virtual Key code for 'T'

    while True:
        try:
            # Check if T key is pressed (most significant bit is set)
            is_pressed = (user32.GetAsyncKeyState(VK_T) & 0x8000) != 0

            if is_pressed and not _hotkey_pressed:
                _hotkey_pressed = True
                log.info("🔑 [Global/Poll] T tuşu basıldı")
                if _hotkey_loop and active_sessions:
                    for session in active_sessions.values():
                        asyncio.run_coroutine_threadsafe(session.ptt_start(), _hotkey_loop)

            elif not is_pressed and _hotkey_pressed:
                _hotkey_pressed = False
                log.info("🔑 [Global/Poll] T tuşu bırakıldı")
                if _hotkey_loop and active_sessions:
                    for session in active_sessions.values():
                        asyncio.run_coroutine_threadsafe(session.ptt_stop(), _hotkey_loop)
        except Exception as e:
            log.debug(f"PTT key poll error: {e}")

        time.sleep(0.015)  # 15ms poll rate (~66Hz)


def start_global_hotkey():
    """Start global PTT polling thread. Runs in background."""
    global _hotkey_loop
    _hotkey_loop = asyncio.get_event_loop()

    t = threading.Thread(target=ptt_polling_loop, daemon=True)
    t.start()
    log.info(f"🔑 Anti-cheat uyumlu global PTT dinleyici baslatildi: '{PTT_KEY.upper()}' tusu")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    # Fix Windows console encoding for emoji/unicode
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

    print()
    print("  ====================================================")
    print("  |   APEX LEGENDS CANLI CEVIRI SUNUCUSU             |")
    print("  |   Turkce -> Ingilizce Ses Cevirisi               |")
    print("  ====================================================")
    print()
    print(f"  Tarayicida ac: http://localhost:8765")
    print(f"  Push-to-Talk: '{PTT_KEY.upper()}' tusu")
    print("  Kapatmak icin: Ctrl+C")
    print()

    # Register global hotkey before starting server
    try:
        start_global_hotkey()
    except Exception as e:
        log.warning(f"Global hotkey kaydedilemedi: {e}")
        log.warning("Yönetici olarak çalıştırmayı dene.")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8765,
        log_level="info",
        ws_max_size=10 * 1024 * 1024,
    )
