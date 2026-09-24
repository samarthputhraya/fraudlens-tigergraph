"""Let Gemini listen: transcribe every narration clip (catches dropped or misread words, which the tail check cannot)
and describe the music candidates, so a human only has to confirm the pick.

Usage:  python video/voice/qa_audio.py [voice|music|all]
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
client = genai.Client(vertexai=True, project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
MODEL = "gemini-2.5-flash"


def words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", s.lower().replace("fincen", "fin sen").replace("mcp", "m c p"))


def voice() -> None:
    man = json.loads((ROOT / "video" / "public" / "voice" / "manifest.json").read_text(encoding="utf-8"))
    bad = 0
    for line in man["lines"]:
        audio = (ROOT / "video" / "public" / line["file"]).read_bytes()
        r = client.models.generate_content(model=MODEL, contents=[
            types.Part.from_bytes(data=audio, mime_type="audio/wav"),
            "Transcribe this narration exactly, word for word. Output only the transcript."])
        heard = (r.text or "").strip()
        want, got = words(line["text"]), words(heard)
        missing = [w for w in want if w not in got]
        ok = len(missing) <= 1
        bad += 0 if ok else 1
        print(f"{'OK ' if ok else '!! '}{line['id']:7s} missing={missing[:6]}\n      heard: {heard[:160]}")
    print(f"{len(man['lines']) - bad}/{len(man['lines'])} clips transcribe cleanly")


def music() -> None:
    for p in sorted((ROOT / "video" / "music" / "clips").glob("*.wav")):
        r = client.models.generate_content(model=MODEL, contents=[
            types.Part.from_bytes(data=p.read_bytes(), mime_type="audio/wav"),
            "This is a candidate background music bed for a calm, premium technology product film with a narrator on "
            "top. In 3 short bullet points: describe its mood, instrumentation and energy; say whether anything would "
            "distract from a narrator (vocals, drums, sudden changes, harshness); rate its suitability 1-10."])
        print(f"== {p.name}\n{(r.text or '').strip()}\n")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("voice", "all"):
        voice()
    if what in ("music", "all"):
        music()
