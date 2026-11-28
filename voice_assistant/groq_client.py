import os
import requests
from web_dashboard import queries
from config import DATABASE_PATH, GROQ_API_KEY

WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

# One shared session keeps the TLS connection to api.groq.com alive between
# the speech-to-text call and the chat call (saves a handshake per query).
_session = requests.Session()

def transcribe_audio(file_path):
    """Sends WAV to Groq Whisper Turbo for STT."""
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "audio/wav")}
            data = {"model": "whisper-large-v3-turbo", "response_format": "json"}
            resp = _session.post(WHISPER_URL, headers=headers, files=files, data=data, timeout=15)
        
        if resp.status_code == 200:
            return resp.json().get("text", "").strip()
        print(f"[AI] Whisper Error: {resp.text}")
        return None
    except Exception as e:
        print(f"[AI] Whisper Request Failed: {e}")
        return None

def generate_response(user_text):
    """Sends text to the chat model via Groq, injecting RAG history."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # RAG: Fetch last 3 conversations from SQLite
    history = queries.get_recent_context(limit=3, db_path=DATABASE_PATH)
    
    messages = [
        {"role": "system", "content": "You are a concise cognitive assistant. Keep all answers under 2 sentences."}
    ]
    
    for h in history:
        messages.append({"role": "user", "content": h["user_query"]})
        messages.append({"role": "assistant", "content": h["assistant_response"]})
        
    messages.append({"role": "user", "content": user_text})
    
    payload = {
        "model": "openai/gpt-oss-20b",
        "messages": messages,
        "max_tokens": 250,  # <--- INCREASED from 60. Reasoning models need room to think.
        "temperature": 0.3
    }
    
    try:
        resp = _session.post(CHAT_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"].strip()
            finish_reason = choice.get("finish_reason", "unknown")
            
            if not content:
                print(f"[AI] LLM Warning: Empty response. Finish reason: {finish_reason}")
                return None
                
            return content
            
        print(f"[AI] LLM Error: {resp.text}")
        return None
    except Exception as e:
        print(f"[AI] LLM Request Failed: {e}")
        return None
