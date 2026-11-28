import os
import time
import subprocess
import tempfile
import threading

class AudioRecorder:
    def __init__(self, device="default", max_seconds=7):
        self.device = device
        self.max_seconds = max_seconds
        self.recording = False
        self.process = None

    def start_recording(self):
        """Starts recording in the background and returns the file path."""
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        
        self.recording = True
        self.process = subprocess.Popen([
            "arecord", "-q", "-D", self.device, 
            "-f", "S16_LE", "-r", "16000", "-c", "1", 
            "-d", str(self.max_seconds), path
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return path

    def stop_recording(self):
        """Stops the recording early if the button is pressed again."""
        if self.recording and self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                # arecord ignored SIGTERM; do not block the button handler.
                self.process.kill()
                self.process.wait()
            self.recording = False
