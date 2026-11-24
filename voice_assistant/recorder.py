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
        if self.recording and hasattr(self, "process"):
            self.process.terminate()
            self.process.wait()
            self.recording = False
