import os
import socket
import threading
import subprocess
import time
from voice_assistant.recorder import AudioRecorder
from voice_assistant import groq_client
from bluetooth_audio import speak_text
from web_dashboard import queries
from config import DATABASE_PATH, MIC_DEVICE, MAX_RECORD_SECONDS

class AssistantController:
    def __init__(self):
        self.state = "IDLE"  # IDLE, RECORDING, PROCESSING, SPEAKING
        self.recorder = AudioRecorder(device=MIC_DEVICE, max_seconds=MAX_RECORD_SECONDS)
        # Re-entrant: _speak() updates the state and is called both with and
        # without the lock held.
        self.lock = threading.RLock()
        self.timer = None

    def check_internet(self):
        try:
            # Close the probe socket explicitly instead of waiting for GC.
            with socket.create_connection(("8.8.8.8", 53), timeout=2):
                return True
        except OSError:
            return False

    def handle_button_press(self):
        with self.lock:
            if self.state == "IDLE":
                self._start_recording()
            elif self.state == "RECORDING":
                self._stop_recording_and_process()
            elif self.state == "SPEAKING":
                self._interrupt_speech()
            elif self.state == "PROCESSING":
                print("[AI] Ignored button press: currently processing.")

    def _start_recording(self):
        if not self.check_internet():
            print("[AI] No internet.")
            self._speak("No internet. Please connect the internet.")
            return
            
        print("[AI] Recording...")
        self.state = "RECORDING"
        self.audio_path = self.recorder.start_recording()
        
        # Start a timer to auto-stop after MAX_RECORD_SECONDS
        self.timer = threading.Timer(MAX_RECORD_SECONDS + 1, self._on_record_timeout)
        self.timer.daemon = True
        self.timer.start()

    def _on_record_timeout(self):
        # The timer fires on its own thread; take the same lock as the button
        # path so both cannot stop the recording at the same time.
        with self.lock:
            self._stop_recording_and_process()

    def _stop_recording_and_process(self):
        if self.state != "RECORDING":
            return
        
        if self.timer is not None:
            self.timer.cancel()
        self.recorder.stop_recording()
        self.state = "PROCESSING"
        print("[AI] Processing audio...")
        
        # Run API calls in a separate thread to not block the main loop
        threading.Thread(target=self._process_pipeline, daemon=True).start()

    def _process_pipeline(self):
        try:
            # 1. STT
            user_text = groq_client.transcribe_audio(self.audio_path)
            if not user_text:
                raise Exception("Transcription failed or was empty.")
            print(f"[AI] User: {user_text}")

            # 2. LLM
            ai_text = groq_client.generate_response(user_text)
            if not ai_text:
                raise Exception("LLM generation failed.")
            print(f"[AI] Response: {ai_text}")

            # 3. Save to DB
            queries.add_assistant_conversation(user_text, ai_text, db_path=DATABASE_PATH)

            # 4. Speak
            self._speak(ai_text)

        except Exception as e:
            print(f"[AI] Pipeline Error: {e}")
            self._speak("Sorry, I could not process that.")
        finally:
            if os.path.exists(self.audio_path):
                os.remove(self.audio_path)

    def _speak(self, text):
        with self.lock:
            self.state = "SPEAKING"
        
        def play():
            speak_text(text)
            # Only set to IDLE if we weren't interrupted
            with self.lock:
                if self.state == "SPEAKING":
                    self.state = "IDLE"
                    print("[AI] Ready.")
                    
        threading.Thread(target=play, daemon=True).start()

    def _interrupt_speech(self):
        print("[AI] Interrupting speech.")
        # Kill the paplay process instantly
        subprocess.run(["pkill", "-f", "paplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.lock:
            self.state = "IDLE"

# Singleton instance
controller = AssistantController()
