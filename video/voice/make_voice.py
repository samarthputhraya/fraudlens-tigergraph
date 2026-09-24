"""Narration for the demo film: one directed clip per line of video/script.json, Gemini 2.5 Pro TTS (Charon).

- Cloud Text-to-Speech keeps the direction in a separate `prompt` field, so it is never read aloud; if that API
  is not enabled on the project we fall back to the same voice through Vertex AI.
- The voice sometimes stops mid-syllable. A natural ending decays below -40 dBFS; a take whose last 50 ms is still
  above -35 dBFS lost its final syllable, so it is taken again (up to five takes, the quietest ending wins).
- Clips are cached by a hash of voice + direction + text, trimmed to 100 ms of lead and 300 ms of tail silence,
  pauses between sentences capped at 0.55 s (except lines marked keep_pauses), faded 12 ms at both ends (no clicks),
  and listed with their exact durations in video/public/voice/manifest.json for the edit.

Usage:  python video/voice/make_voice.py [line_id ...]
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import time
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
VIDEO = ROOT / "video"
OUT = VIDEO / "public" / "voice"
CACHE = VIDEO / "voice" / "cache"
load_dotenv(ROOT / ".env")
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
RATE = 24000
TRUNCATED_DB = -35.0
TAKES = 5


def _rms_db(x: np.ndarray) -> float:
    return float(10 * np.log10(np.mean((x.astype(np.float64) / 32768) ** 2) + 1e-12))


def tail_db(pcm: np.ndarray) -> float:
    return _rms_db(pcm[-int(RATE * 0.05):])


def trim(pcm: np.ndarray, lead: float = 0.10, tail: float = 0.30, floor_db: float = -50.0) -> np.ndarray:
    """Cut leading/trailing silence, keeping a little air (a quiet final consonant such as the 't' of "percent" sits
    near -45 dBFS, so the floor is -50 and the tail keeps 300 ms)."""
    win = int(RATE * 0.01)
    n = len(pcm) // win
    loud = [i for i in range(n) if _rms_db(pcm[i * win:(i + 1) * win]) > floor_db]
    if not loud:
        return pcm
    a = max(0, loud[0] * win - int(RATE * lead))
    b = min(len(pcm), (loud[-1] + 1) * win + int(RATE * tail))
    return pcm[a:b]


def tighten(pcm: np.ndarray, longest: float = 0.55, floor_db: float = -45.0, xfade: float = 0.03) -> np.ndarray:
    """Shorten pauses between sentences that run longer than `longest` seconds (the voice sometimes lingers ~0.9 s,
    which reads as a gap on film). The cut is made inside the silence and joined with a 30 ms equal-power crossfade,
    so the room tone on either side of it doesn't jump."""
    win = int(RATE * 0.02)
    n = len(pcm) // win
    quiet = [_rms_db(pcm[i * win:(i + 1) * win]) < floor_db for i in range(n)]
    cuts, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if i > 0 and j < n and (j - i) * win / RATE > longest:
                keep = int(longest * RATE)
                cuts.append((i * win + keep // 2, j * win - keep // 2))
            i = j
        else:
            i += 1
    if not cuts:
        return pcm
    x = pcm.astype(np.float64)
    k = int(RATE * xfade)
    out = x[: cuts[0][0]]
    for c, (a, b) in enumerate(cuts):
        nxt = x[b: cuts[c + 1][0]] if c + 1 < len(cuts) else x[b:]
        t = np.linspace(0, np.pi / 2, k)
        head, tail = out[-k:], nxt[:k]
        out = np.concatenate([out[:-k], head * np.cos(t) + tail * np.sin(t), nxt[k:]])
    return out.astype("<i2")


def fade(pcm: np.ndarray, ms: float = 12.0) -> np.ndarray:
    """A 12 ms fade at both ends, so a clip never starts or stops on a non-zero sample (an audible click)."""
    k = min(len(pcm) // 2, int(RATE * ms / 1000))
    x = pcm.astype(np.float64)
    ramp = np.linspace(0.0, 1.0, k)
    x[:k] *= ramp
    x[-k:] *= ramp[::-1]
    return x.astype("<i2")


def _cloud_tts(text: str, prompt: str, voice: str, model: str) -> bytes:
    import google.auth
    import google.auth.transport.requests
    import requests
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", timeout=180,
                      headers={"Authorization": f"Bearer {creds.token}", "x-goog-user-project": PROJECT},
                      json={"input": {"text": text, "prompt": prompt},
                            "voice": {"languageCode": "en-US", "name": voice, "modelName": model},
                            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": RATE}})
    if r.status_code != 200:
        raise RuntimeError(f"cloud-tts {r.status_code}: {r.text[:200]}")
    wav = base64.b64decode(r.json()["audioContent"])
    return wav[44:] if wav[:4] == b"RIFF" else wav


def _vertex_tts(text: str, prompt: str, voice: str, model: str) -> bytes:
    from google import genai
    from google.genai import types
    client = genai.Client(vertexai=True, project=PROJECT, location="global")
    r = client.models.generate_content(
        model=model, contents=f"{prompt}\nRead this line exactly as written: {text}",
        config=types.GenerateContentConfig(response_modalities=["AUDIO"], speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)))))
    return r.candidates[0].content.parts[0].inline_data.data


BACKEND = {"name": None}


def synth(text: str, prompt: str, voice: str, model: str) -> np.ndarray:
    last = None
    for attempt in range(8):
        try:
            if BACKEND["name"] in (None, "cloud"):
                try:
                    raw = _cloud_tts(text, prompt, voice, model)
                    BACKEND["name"] = "cloud"
                except RuntimeError as e:
                    if BACKEND["name"] == "cloud" or "429" in str(e):
                        raise
                    print(f"  cloud TTS unavailable ({str(e)[:90]}); using Vertex AI", flush=True)
                    BACKEND["name"] = "vertex"
                    raw = _vertex_tts(text, prompt, voice, model)
            else:
                raw = _vertex_tts(text, prompt, voice, model)
            return np.frombuffer(raw, dtype="<i2").copy()
        except Exception as e:  # noqa: BLE001 - quota and transient errors: wait and retry
            last = e
            wait = 35 + attempt * 15 if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e) else 3 * 2 ** attempt
            print(f"  retry in {wait}s: {str(e)[:100]}", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"TTS failed: {last}")


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype("<i2").tobytes())


def main(only: list[str]) -> None:
    script = json.loads((VIDEO / "script.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.json"
    manifest = {x["id"]: x for x in json.loads(manifest_path.read_text())["lines"]} if manifest_path.exists() else {}
    for line in script["lines"]:
        if only and line["id"] not in only:
            continue
        say = line.get("say") or line["text"]
        prompt = script["direction"] + (" For this line: " + line["style"] + "." if line.get("style") else "")
        key = hashlib.sha256(json.dumps([script["voice"], script["model"], prompt, say]).encode()).hexdigest()[:20]
        cached = CACHE / f"{key}.wav"
        if cached.exists():
            with wave.open(str(cached)) as w:
                pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").copy()
            takes = 0
        else:
            best, takes = None, 0
            for takes in range(1, TAKES + 1):
                pcm = synth(say, prompt, script["voice"], script["model"])
                db = tail_db(pcm)
                if best is None or db < best[0]:
                    best = (db, pcm)
                if db < TRUNCATED_DB:
                    break
                print(f"  {line['id']}: take {takes} ends at {db:.1f} dBFS (cut syllable), retaking", flush=True)
            pcm = best[1]
            write_wav(cached, pcm)
        clip = trim(pcm)
        if not line.get("keep_pauses"):
            clip = tighten(clip)
        clip = fade(clip)
        out = OUT / f"{line['id']}.wav"
        write_wav(out, clip)
        manifest[line["id"]] = {"id": line["id"], "scene": line["scene"], "text": line["text"], "file": f"voice/{line['id']}.wav",
                                "seconds": round(len(clip) / RATE, 3), "tail_db": round(tail_db(pcm), 1)}
        print(f"{line['id']:7s} {len(clip) / RATE:5.2f}s  takes={takes}  tail={tail_db(pcm):.1f} dBFS  backend={BACKEND['name'] or 'cache'}", flush=True)
        manifest_path.write_text(json.dumps({"voice": script["voice"], "model": script["model"],
                                             "lines": [manifest[x["id"]] for x in script["lines"] if x["id"] in manifest]},
                                            indent=1), encoding="utf-8")
    total = sum(v["seconds"] for v in manifest.values())
    print(f"narration total {total:.1f}s over {len(manifest)} lines")


if __name__ == "__main__":
    main(sys.argv[1:])
