#!/usr/bin/env python3
"""
Bluetooth Audio Manager
=======================

Primary Device: M3 (MAC: 12:11:67:29:5C:E2)
Secondary Device: Noise Buds VS102 (MAC: 0D:B0:21:9E:9D:51)

Features:
    - Primary device has priority over secondary device.
    - Automatically attempts reconnection in the background.
    - Uses Bluetooth audio sinks through PipeWire/PulseAudio.
    - Supports offline Piper text-to-speech.
    - Optimized for minimal CPU usage on Raspberry Pi.
"""

import os
import time
import wave
import shutil
import tempfile
import subprocess
import threading
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

PRIMARY_MAC = os.environ.get("BLUETOOTH_PRIMARY_MAC", "12:11:67:29:5C:E2").strip().upper()
SECONDARY_MAC = os.environ.get("BLUETOOTH_SECONDARY_MAC", "0D:B0:21:9E:9D:51").strip().upper()

MONITOR_INTERVAL = 10
CONNECT_TIMEOUT = 10

VOICE_MODEL = BASE_DIR / "voices" / "en_US-lessac-medium.onnx"
VOICE_CONFIG = BASE_DIR / "voices" / "en_US-lessac-medium.onnx.json"

PIPER_EXECUTABLE = shutil.which("piper")
PAPLAY_EXECUTABLE = shutil.which("paplay")

# ============================================================
# GLOBAL STATE
# ============================================================

_monitor_thread = None
_monitor_stop_event = threading.Event()
_monitor_lock = threading.Lock()

_tts_lock = threading.Lock()

_piper_voice = None
_piper_voice_initialized = False

_current_sink = None
_active_device = None

# ============================================================
# COMMAND EXECUTION
# ============================================================

def _run_command(command, timeout=10):
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        print(f"[AUDIO] Command timed out: {command}")
        return False, "Command timed out"
    except FileNotFoundError:
        print(f"[AUDIO] Command not found: {command[0]}")
        return False, f"{command[0]} not found"
    except Exception as exc:
        print(f"[AUDIO] Command execution failed: {exc}")
        return False, str(exc)

# ============================================================
# BLUETOOTH DEVICE MANAGEMENT
# ============================================================

def _device_name(mac):
    if mac == PRIMARY_MAC: return "M3 (Primary)"
    if mac == SECONDARY_MAC: return "Noise Buds (Secondary)"
    return mac

def _is_paired(mac):
    success, output = _run_command(["bluetoothctl", "info", mac], timeout=3)
    if not success: return False
    return "Paired: yes" in output

def _connect_device(mac):
    if not _is_paired(mac):
        print(f"[AUDIO] {_device_name(mac)} is not paired.")
        return False

    print(f"[AUDIO] Connecting to {_device_name(mac)}...")
    _run_command(["bluetoothctl", "connect", mac], timeout=CONNECT_TIMEOUT)
    
    # Check if pactl sees it
    sink = _find_sink_for_device(mac)
    if sink:
        print(f"[AUDIO] Connected to {_device_name(mac)}.")
        return True

    print(f"[AUDIO] Could not connect to {_device_name(mac)}.")
    return False

def _disconnect_device(mac):
    print(f"[AUDIO] Disconnecting {_device_name(mac)}...")
    _run_command(["bluetoothctl", "disconnect", mac], timeout=5)
    time.sleep(0.5)

# ============================================================
# AUDIO SINK MANAGEMENT
# ============================================================

def _get_audio_sinks():
    success, output = _run_command(["pactl", "list", "short", "sinks"], timeout=3)
    if not success: return []
    sinks = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1].startswith("bluez_output"):
            sinks.append(fields[1])
    return sinks

def _mac_to_sink_fragment(mac):
    return mac.replace(":", "_").upper()

def _find_sink_for_device(mac):
    sinks = _get_audio_sinks()
    fragment = _mac_to_sink_fragment(mac)
    for sink in sinks:
        if fragment in sink.upper():
            return sink
    return None

def _select_bluetooth_sink():
    global _current_sink

    # If primary is connected, we must use it. Otherwise, try secondary.
    primary_sink = _find_sink_for_device(PRIMARY_MAC)
    secondary_sink = _find_sink_for_device(SECONDARY_MAC)

    sink = primary_sink if primary_sink else secondary_sink

    if not sink:
        return False

    if sink == _current_sink:
        return True

    success, _ = _run_command(["pactl", "set-default-sink", sink], timeout=3)
    if success:
        _current_sink = sink
        print(f"[AUDIO] Selected Bluetooth sink: {sink}")
        return True
    return False

# ============================================================
# PRIORITY MONITOR
# ============================================================

def _monitor_loop():
    global _active_device, _current_sink
    
    while not _monitor_stop_event.is_set():
        try:
            # 1. Check what sinks are currently available (fast pactl call)
            primary_sink = _find_sink_for_device(PRIMARY_MAC)
            secondary_sink = _find_sink_for_device(SECONDARY_MAC)

            if primary_sink:
                if _active_device != PRIMARY_MAC or _current_sink != primary_sink:
                    _active_device = PRIMARY_MAC
                    if secondary_sink:
                        _disconnect_device(SECONDARY_MAC)
                    _select_bluetooth_sink()
            elif secondary_sink:
                if _active_device != SECONDARY_MAC or _current_sink != secondary_sink:
                    _active_device = SECONDARY_MAC
                    _select_bluetooth_sink()
            else:
                # Neither is connected as a sink. Try to wake up primary.
                _active_device = None
                _connect_device(PRIMARY_MAC)

        except Exception as exc:
            print(f"[AUDIO] Monitor error: {exc}")

        _monitor_stop_event.wait(MONITOR_INTERVAL)

def connect_bluetooth_audio():
    global _monitor_thread

    print("[AUDIO] Initializing Bluetooth manager...")
    print(f"[AUDIO] Primary: {PRIMARY_MAC} | Secondary: {SECONDARY_MAC}")

    # Initial connection attempt
    if not _find_sink_for_device(PRIMARY_MAC):
        _connect_device(PRIMARY_MAC)
    
    _select_bluetooth_sink()

    with _monitor_lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_stop_event.clear()
            _monitor_thread = threading.Thread(
                target=_monitor_loop, name="BluetoothMonitor", daemon=True
            )
            _monitor_thread.start()
            print("[AUDIO] Bluetooth priority monitor started.")

    return _active_device is not None

def stop_bluetooth_monitor():
    _monitor_stop_event.set()

# ============================================================
# PIPER TEXT-TO-SPEECH
# ============================================================

def _load_piper_voice():
    global _piper_voice, _piper_voice_initialized

    if _piper_voice_initialized:
        return _piper_voice

    _piper_voice_initialized = True

    if not VOICE_MODEL.is_file() or not VOICE_CONFIG.is_file():
        print("[AUDIO] Piper model/config missing.")
        return None

    try:
        from piper.voice import PiperVoice
        _piper_voice = PiperVoice.load(str(VOICE_MODEL), config_path=str(VOICE_CONFIG))
        print("[AUDIO] Piper voice loaded successfully.")
    except Exception as exc:
        print(f"[AUDIO] Could not load Piper: {exc}")
        _piper_voice = None

    return _piper_voice

def _synthesize_with_python(text, output_path):
    voice = _load_piper_voice()
    if voice is None:
        return False
    try:
        with wave.open(str(output_path), "wb") as wav_file:
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, wav_file)
            else:
                voice.synthesize(text, wav_file)
        return output_path.is_file() and output_path.stat().st_size > 44
    except Exception:
        return False

def _synthesize_with_cli(text, output_path):
    if not PIPER_EXECUTABLE:
        return False

    command = [
        PIPER_EXECUTABLE, "--model", str(VOICE_MODEL),
        "--output_file", str(output_path)
    ]
    if VOICE_CONFIG.is_file():
        command.extend(["--config", str(VOICE_CONFIG)])

    try:
        # Piper reads from stdin
        result = subprocess.run(
            command, input=text, capture_output=True, text=True, timeout=60, check=False
        )
        if result.returncode == 0:
            return output_path.is_file() and output_path.stat().st_size > 44
    except Exception:
        pass
    return False

# ============================================================
# SPEECH PLAYBACK
# ============================================================

def speak(text):
    if not text:
        return False

    text = str(text).strip()
    if not text or not PAPLAY_EXECUTABLE:
        return False

    with _tts_lock:
        try:
            # Ensure we have an active sink, otherwise fail gracefully
            if not _active_device:
                _select_bluetooth_sink()
                
            if not _current_sink:
                print("[AUDIO] Cannot speak: No active Bluetooth sink.")
                return False

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                output_path = Path(temp_file.name)

            try:
                # Try Python API first, then CLI
                synthesized = _synthesize_with_python(text, output_path)
                if not synthesized:
                    synthesized = _synthesize_with_cli(text, output_path)

                if not synthesized:
                    print("[AUDIO] Synthesis failed.")
                    return False

                success, output = _run_command(
                    [PAPLAY_EXECUTABLE, "--device", _current_sink, str(output_path)],
                    timeout=120
                )

                if not success:
                    print(f"[AUDIO] Playback failed: {output}")
                    return False

                return True
            finally:
                try:
                    output_path.unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception as exc:
            print(f"[AUDIO] Speech error: {exc}")
            return False

def speak_text(text):
    """Alias for speak(), for compatibility with application code."""
    return speak(text)

def warmup_tts():
    voice = _load_piper_voice()
    if voice is not None:
        print("[AUDIO] Piper TTS warm-up completed.")
        return True
    print("[AUDIO] Piper warm-up failed, CLI may be used.")
    return False

# ============================================================
# STATUS REPORT
# ============================================================

def get_bluetooth_status():
    return {
        "primary_connected": bool(_find_sink_for_device(PRIMARY_MAC)),
        "secondary_connected": bool(_find_sink_for_device(SECONDARY_MAC)),
        "active_device": _active_device,
        "active_sink": _current_sink
    }
