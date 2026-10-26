#!/usr/bin/env python3
"""Low-overhead Bluetooth audio + offline Piper TTS for Raspberry Pi."""

import os
import shutil
import subprocess
import tempfile
import time
import wave

BLUETOOTH_MAC = os.environ.get("BLUETOOTH_MAC", "0D:B0:21:9E:9D:51").strip()
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_MODEL = os.path.join(MODULE_DIR, "voices", "en_US-lessac-medium.onnx")
VOICE_CONFIG = VOICE_MODEL + ".json"
COMMAND_TIMEOUT = 10

_piper_voice = None
_piper_load_attempted = False


def _run(command, timeout=COMMAND_TIMEOUT):
    try:
        p = subprocess.run(command, capture_output=True, text=True,
                           timeout=timeout, check=False)
        return p.returncode == 0, p.stdout.strip(), p.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, "", str(exc)


def _is_connected(mac):
    ok, stdout, _ = _run(["bluetoothctl", "info", mac], timeout=2)
    return ok and "Connected: yes" in stdout


def _select_bluetooth_sink():
    ok, stdout, err = _run(["pactl", "list", "short", "sinks"], timeout=4)
    if not ok:
        print(f"[AUDIO] Cannot list sinks: {err or stdout}")
        return False
    sinks = [line.split()[1] for line in stdout.splitlines()
             if len(line.split()) >= 2 and line.split()[1].startswith("bluez_output")]
    if not sinks:
        print("[AUDIO] No Bluetooth audio sink found.")
        return False
    ok, _, err = _run(["pactl", "set-default-sink", sinks[0]], timeout=4)
    if not ok:
        print(f"[AUDIO] Cannot select Bluetooth sink: {err}")
        return False
    print(f"[AUDIO] Bluetooth output selected: {sinks[0]}")
    return True


def connect_bluetooth_audio():
    """Connect once at startup; never retry continuously in the recognition loop."""
    mac = BLUETOOTH_MAC
    if not mac:
        print("[BLUETOOTH] MAC not configured.")
        return False

    if not _is_connected(mac):
        print(f"[BLUETOOTH] Connecting to {mac}...")
        _run(["bluetoothctl", "connect", mac], timeout=8)
    else:
        print(f"[BLUETOOTH] Already connected to {mac}.")

    for _ in range(4):
        if _is_connected(mac):
            return _select_bluetooth_sink()
        time.sleep(0.5)
    print("[BLUETOOTH] Earbuds unavailable; continuing without Bluetooth.")
    return False


def _load_piper_once():
    """Load the neural voice once per process instead of reloading it for every phrase."""
    global _piper_voice, _piper_load_attempted
    if _piper_load_attempted:
        return _piper_voice
    _piper_load_attempted = True
    if not (os.path.isfile(VOICE_MODEL) and os.path.isfile(VOICE_CONFIG)):
        print("[AUDIO] Piper voice files missing; speech is disabled.")
        return None
    try:
        from piper.voice import PiperVoice
        _piper_voice = PiperVoice.load(VOICE_MODEL, config_path=VOICE_CONFIG)
        print("[AUDIO] Piper voice loaded and cached.")
    except Exception as exc:
        print(f"[AUDIO] Piper Python API unavailable; will use CLI fallback: {exc}")
    return _piper_voice


def warmup_tts():
    """Load the Piper voice in the background before the first announcement."""
    _load_piper_once()


def speak_text(text):
    """Synthesize offline; cache Piper in memory and play a temporary WAV."""
    if not text:
        return
    if not (os.path.isfile(VOICE_MODEL) and os.path.isfile(VOICE_CONFIG)):
        print("[AUDIO] Missing Piper voice files; cannot speak.")
        return
    paplay = shutil.which("paplay")
    if not paplay:
        print("[AUDIO] paplay not found; install pulseaudio-utils.")
        return

    fd, wav_path = tempfile.mkstemp(prefix="tts_", suffix=".wav")
    os.close(fd)
    try:
        voice = _load_piper_once()
        if voice is not None:
            # Piper's Python API avoids starting/loading the model on every message.
            with wave.open(wav_path, "wb") as wav_file:
                voice.synthesize_wav(str(text), wav_file)
        else:
            piper = shutil.which("piper")
            if not piper:
                print("[AUDIO] Piper CLI not found.")
                return
            result = subprocess.run(
                [piper, "--model", VOICE_MODEL, "--output_file", wav_path],
                input=str(text), text=True, capture_output=True, timeout=45, check=False
            )
            if result.returncode:
                print("[AUDIO] Piper failed:", result.stderr.strip())
                return

        result = subprocess.run([paplay, wav_path], capture_output=True, text=True,
                                timeout=30, check=False)
        if result.returncode:
            print("[AUDIO] Playback failed:", result.stderr.strip())
    except Exception as exc:
        print(f"[AUDIO] Speech error: {exc}")
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


if __name__ == "__main__":
    if connect_bluetooth_audio():
        speak_text("Bluetooth audio test.")
    else:
        print("Bluetooth not ready.")
