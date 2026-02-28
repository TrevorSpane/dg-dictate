import os
import sys
import asyncio
import threading
from pynput import keyboard
from deepgram import (
    DeepgramClient,
    LiveTranscriptionEvents,
    LiveOptions,
)
import pyaudio
import subprocess
import time
import pystray
from PIL import Image, ImageDraw
import logging

# --- Logging Setup ---
LOG_FILE = os.path.expanduser("~/dg-dictate/dictate.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

# --- Configuration ---
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

# Audio settings
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
CHUNK = 2048

# Target Key: F4
TARGET_KEY = keyboard.Key.f4

class DictationApp:
    def __init__(self):
        self.is_recording = False
        self.started_by_key = False
        self.stop_event = threading.Event()
        self.dg_client = DeepgramClient(DEEPGRAM_API_KEY)
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.running = True
        
        # Debounce timing
        self.last_press_time = 0
        self.last_release_time = 0
        self.debounce_interval = 0.2 # seconds
        
        # Keyboard listener
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

        # Tray Icon
        self.icon = None
        self.setup_tray()

    def create_icon_image(self, color):
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), (31, 31, 31)) # Dark background
        dc = ImageDraw.Draw(image)
        padding = 10
        dc.ellipse((padding, padding, width - padding, height - padding), fill=color)
        return image

    def setup_tray(self):
        try:
            self.icon_off = self.create_icon_image('red')
            self.icon_on = self.create_icon_image('green')
            
            # Toggle Dictation is the default action (invoked on click if supported)
            self.menu_toggle = pystray.MenuItem('Toggle Dictation', self.toggle_dictation, default=True)
            menu = pystray.Menu(
                self.menu_toggle,
                pystray.MenuItem('Quit', self.quit_app)
            )
            self.icon = pystray.Icon("Dictation Tool", self.icon_off, "Dictation Off", menu)
        except Exception as e:
            logging.error(f"Failed to initialize tray icon: {e}")
            self.icon = None

    def on_press(self, key):
        try:
            if key == TARGET_KEY:
                now = time.time()
                if now - self.last_press_time < self.debounce_interval:
                    return
                self.last_press_time = now

                if not self.is_recording:
                    logging.info("F4 pressed: Starting dictation (Toggle ON)")
                    self.started_by_key = True
                    self.start_dictation()
                else:
                    logging.info("F4 pressed: Stopping dictation (Toggle OFF)")
                    self.stop_dictation()
                    self.started_by_key = False
        except Exception as e:
            logging.error(f"Error in on_press: {e}")

    def on_release(self, key):
        # We no longer stop on release for toggle mode
        pass

    def toggle_dictation(self, icon=None, item=None):
        try:
            if self.is_recording:
                logging.info("Tray: Toggling OFF")
                self.stop_dictation()
                self.started_by_key = False
            else:
                logging.info("Tray: Toggling ON")
                self.started_by_key = False # Explicitly GUI start
                self.start_dictation()
        except Exception as e:
            logging.error(f"Error in toggle_dictation: {e}")

    def start_dictation(self):
        if self.is_recording: return
        self.is_recording = True
        self.stop_event.clear()
        
        # Update UI safely
        def update_ui():
            if self.icon:
                self.icon.icon = self.icon_on
                self.icon.title = "Dictation ON (Recording...)"
        
        # pystray update might need to be in main thread but usually works here
        update_ui()
        
        logging.info("Transcription thread starting...")
        threading.Thread(target=self.start_async_loop, daemon=True).start()

    def stop_dictation(self):
        if not self.is_recording: return
        logging.info("Stopping dictation...")
        self.is_recording = False
        self.stop_event.set()
        
        if self.icon:
            self.icon.icon = self.icon_off
            self.icon.title = "Dictation OFF"

    def quit_app(self, icon, item):
        logging.info("Quitting application...")
        self.stop_dictation()
        self.running = False
        self.icon.stop()
        self.listener.stop()
        os._exit(0) # Force exit to clear all threads

    def start_async_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.process_audio())
        except Exception as e:
            logging.error(f"Async loop error: {e}")
        finally:
            loop.close()

    async def process_audio(self):
        dg_connection = None
        try:
            dg_connection = self.dg_client.listen.websocket.v("1")

            def on_transcript(self_conn, result, **kwargs):
                if result.channel.alternatives:
                    sentence = result.channel.alternatives[0].transcript
                    if sentence.strip() and result.is_final:
                        logging.info(f"Transcript: {sentence}")
                        # Small delay to ensure the OS has registered key releases
                        time.sleep(0.1)
                        subprocess.run(["xdotool", "type", "--delay", "0", sentence + " "])

            def on_error(self_conn, error, **kwargs):
                logging.error(f"Deepgram Connection Error: {error}")

            dg_connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
            dg_connection.on(LiveTranscriptionEvents.Error, on_error)

            options = LiveOptions(
                model="nova-2",
                language="en-US",
                smart_format=True,
                encoding="linear16",
                channels=1,
                sample_rate=16000,
            )

            if dg_connection.start(options) is False:
                logging.error("Failed to start Deepgram connection")
                return

            self.stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK,
            )

            logging.info("Audio stream opened and sending...")
            while not self.stop_event.is_set() and self.is_recording:
                try:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                    dg_connection.send(data)
                except Exception as e:
                    logging.error(f"Stream read error: {e}")
                    break
                await asyncio.sleep(0.005)

            logging.info("Closing audio stream...")
            if self.stream:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            
            if dg_connection:
                dg_connection.finish()
            
        except Exception as e:
            logging.error(f"Error in process_audio: {e}")
            if dg_connection:
                try: dg_connection.finish()
                except: pass

    def run(self):
        logging.info("Dictation App started. F4: Hold-to-talk, Tray: Toggle.")
        try:
            if self.icon:
                def setup(icon):
                    def _dock_retry():
                        # The xorg tray manager may not be ready at startup.
                        # Keep re-applying the icon until it actually docks.
                        for _ in range(60):  # retry every 3s for up to 3 minutes
                            time.sleep(3)
                            if not self.running:
                                return
                            icon.visible = True
                            icon.icon = self.icon_on if self.is_recording else self.icon_off
                    threading.Thread(target=_dock_retry, daemon=True).start()
                    icon.visible = True
                    icon.icon = self.icon_off
                self.icon.run(setup=setup)
            else:
                # Fallback if tray icon failed to initialize
                while self.running:
                    time.sleep(1)
        except Exception as e:
            logging.error(f"Tray Icon crash/failure: {e}")
            # Keep running even if tray crashes
            while self.running:
                time.sleep(1)

if __name__ == "__main__":
    if not DEEPGRAM_API_KEY:
        logging.error("DEEPGRAM_API_KEY not set.")
        sys.exit(1)
    
    app = DictationApp()
    app.run()
