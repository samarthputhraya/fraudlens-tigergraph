"""Music bed for the demo film: Google Lyria 2 on Vertex AI (royalty-free, generated on our own GCP project).

Lyria returns 30-second instrumental clips (48 kHz stereo WAV). We ask for a calm, modern underscore, generate a
few seeds, and later chain the chosen ones with crossfades into a bed that runs under the whole film.

Usage:  python video/music/make_music.py [n_variants]
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import google.auth
import google.auth.transport.requests
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "video" / "music" / "clips"
load_dotenv(ROOT / ".env")
PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = "us-central1"

PROMPT = ("Minimal modern cinematic underscore for a technology product film about fraud investigation. "
          "Soft warm synth pads, a gentle pulsing arpeggio, subtle low bass, slow evolving texture, "
          "calm and intelligent, quietly confident, hopeful. Around 90 BPM. Instrumental. Clean mix that "
          "sits under a narrator.")
NEGATIVE = "vocals, singing, heavy drums, drops, distortion, busy melody, aggressive, dark horror, EDM"


def main(n: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    url = (f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}"
           f"/publishers/google/models/lyria-002:predict")
    for seed in range(1, n + 1):
        r = requests.post(url, timeout=300, headers={"Authorization": f"Bearer {creds.token}"},
                          json={"instances": [{"prompt": PROMPT, "negative_prompt": NEGATIVE, "seed": seed}],
                                "parameters": {}})
        if r.status_code != 200:
            print(f"seed {seed}: HTTP {r.status_code} {r.text[:300]}")
            continue
        preds = r.json().get("predictions", [])
        for i, p in enumerate(preds):
            b64 = p.get("bytesBase64Encoded") or p.get("audioContent")
            path = OUT / f"bed_seed{seed}_{i}.wav"
            path.write_bytes(base64.b64decode(b64))
            print("wrote", path.name, path.stat().st_size // 1024, "KB")
    (OUT / "prompt.json").write_text(json.dumps({"prompt": PROMPT, "negative": NEGATIVE, "model": "lyria-002"}, indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
