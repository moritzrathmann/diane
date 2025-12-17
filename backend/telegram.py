import os, tempfile, requests
from faster_whisper import WhisperModel

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_whisper = None

def get_whisper():
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper

def download_telegram_file(file_id: str) -> bytes:
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
        json={"file_id": file_id},
        timeout=30
    )
    r.raise_for_status()
    path = r.json()["result"]["file_path"]

    r2 = requests.get(
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{path}",
        timeout=60
    )
    r2.raise_for_status()
    return r2.content

def transcribe_bytes(audio: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as f:
        f.write(audio)
        p = f.name
    segments, _ = get_whisper().transcribe(p)
    return " ".join(s.text.strip() for s in segments).strip()
