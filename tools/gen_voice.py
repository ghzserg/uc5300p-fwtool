#!/usr/bin/env python3
"""Generate spoken prompts for an overlay with a local TTS (Piper) and put them into the work tree.

    python tools/gen_voice.py overlays/ru work            # downloads the Piper voice on first use

Output files are MP3, 44.1 kHz, mono, 128 kbit/s - the format of the stock prompts.
Only names listed in overlays/<name>/voice.json are replaced ({"file stem": "text to say"}).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("overlay")
    ap.add_argument("work")
    ap.add_argument("--volume", default="vol2", help="work/volumes/<volume> holding the *.mp3 prompts")
    ap.add_argument("--model", help="path to a Piper .onnx voice (default: ru_RU-irina-medium, downloaded)")
    args = ap.parse_args()
    from piper import PiperVoice
    model = args.model
    if not model:
        from huggingface_hub import hf_hub_download
        base = "ru/ru_RU/irina/medium/ru_RU-irina-medium"
        model = hf_hub_download("rhasspy/piper-voices", base + ".onnx")
        hf_hub_download("rhasspy/piper-voices", base + ".onnx.json")
    voice = PiperVoice.load(model)
    texts = json.load(open(os.path.join(args.overlay, "voice.json"), encoding="utf-8"))
    out = os.path.join(args.work, "volumes", args.volume, "files")
    if not os.path.isdir(out):
        sys.exit(f"{out} not found - run `fwtool unpack` first")
    for stem, text in texts.items():
        target = os.path.join(out, stem + ".mp3")
        if not os.path.exists(target):
            print(f"skip {stem}: no such file in the stock volume")
            continue
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "t.wav")
            with wave.open(wav, "wb") as w:
                voice.synthesize_wav(text, w)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af",
                            "silenceremove=start_periods=1:start_threshold=-50dB,loudnorm=I=-14:TP=-1.5:LRA=7",
                            "-ar", "44100", "-ac", "1", "-codec:a", "libmp3lame", "-b:a", "128k", target],
                           check=True)
        print("ok", stem)


if __name__ == "__main__":
    main()
