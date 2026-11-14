"""
Container start-up: make sure everything the server needs exists, then run it.

  1. Piper voice     downloaded into the data volume on first start (~63 MB)
  2. FAQ vector store built on first start
  3. uvicorn

Written in Python rather than a shell script so that Windows line endings in a
checkout can never break the container.
"""
import os
import shutil
import sys
import urllib.request
from pathlib import Path

from app.config import get_settings

settings = get_settings()

VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
BUNDLED_MODELS = Path(__file__).parent / "data" / "tts_models"


def _voice_url(name: str, suffix: str) -> str:
    # "en_US-lessac-medium" → en/en_US/lessac/medium/en_US-lessac-medium.onnx
    locale, speaker, quality = name.split("-")
    return f"{VOICE_BASE_URL}/{locale.split('_')[0]}/{locale}/{speaker}/{quality}/{name}{suffix}"


def ensure_voice(name: str, required: bool) -> None:
    model_dir = Path(settings.tts_model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx.json", ".onnx"):
        target = model_dir / f"{name}{suffix}"
        if target.exists():
            continue
        bundled = BUNDLED_MODELS / target.name
        if bundled.exists() and bundled.resolve() != target.resolve():
            shutil.copy(bundled, target)
            continue
        print(f"Downloading voice file {target.name} ...", flush=True)
        try:
            urllib.request.urlretrieve(_voice_url(name, suffix), target)
        except Exception as e:
            target.unlink(missing_ok=True)
            message = f"Could not download {target.name}: {e}"
            if required:
                sys.exit(message)
            print(f"{message} — replies in that language will be text only", flush=True)
            return


def ensure_knowledge_base() -> None:
    marker = Path(settings.chroma_persist_dir) / "chroma.sqlite3"
    if not marker.exists():
        print("Building the FAQ vector store ...", flush=True)
        from app.rag.ingest import ingest
        ingest()


if __name__ == "__main__":
    ensure_voice(settings.tts_model, required=True)
    for pair in settings.tts_voices.split(","):
        if ":" in pair:
            ensure_voice(pair.split(":", 1)[1].strip(), required=False)
    ensure_knowledge_base()
    os.execvp("uvicorn", ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"])
