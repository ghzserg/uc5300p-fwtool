"""Pluggable text-to-speech engines for the voice prompts.

Engines: rhvoice (all installed Russian voices are discovered), piper (neural, downloaded on demand),
espeak (robotic, always available as a fallback) and cmd (any command line you provide).
"""
import glob
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import wave

MP3_FILTER = "silenceremove=start_periods=1:start_threshold=-50dB,loudnorm=I=-14:TP=-1.5:LRA=7"


class TtsError(Exception):
    pass


class Voice:
    def __init__(self, engine, name, gender="", note=""):
        self.engine, self.name, self.gender, self.note = engine, name, gender, note

    def __str__(self):
        return f"{self.engine}:{self.name}"


def _run(cmd, **kw):
    try:
        return subprocess.run(cmd, check=True, capture_output=True, **kw)
    except FileNotFoundError:
        raise TtsError(f"{cmd[0]} not found")
    except subprocess.CalledProcessError as ex:
        raise TtsError(f"{cmd[0]} failed: {ex.stderr.decode('utf-8', 'replace').strip()[:300]}")


# --------------------------------------------------------------------------- RHVoice
class RHVoice:
    name = "rhvoice"
    binary = "RHVoice-test"

    def dirs(self):
        extra = [d for d in os.environ.get("FWTOOL_RHVOICE_DIRS", "").split(os.pathsep) if d]
        return extra + ["/usr/share/RHVoice/voices", "/usr/local/share/RHVoice/voices",
                        os.path.expanduser("~/.local/share/RHVoice/voices")]

    def voices(self):
        out, seen = [], set()
        for d in self.dirs():
            for info in sorted(glob.glob(os.path.join(d, "*", "voice.info"))):
                kv = dict(l.strip().split("=", 1) for l in open(info, encoding="utf-8") if "=" in l)
                if kv.get("language", "").lower() != "russian":
                    continue
                key = os.path.basename(os.path.dirname(info))
                if key not in seen:
                    seen.add(key)
                    out.append(Voice(self.name, key, kv.get("gender", ""), kv.get("name", key)))
        return out

    def available(self):
        return shutil.which(self.binary) is not None and bool(self.voices())

    def synth(self, text, voice, wav):
        _run([self.binary, "-p", voice, "-o", wav], input=text.encode("utf-8"))


# --------------------------------------------------------------------------- Piper
PIPER_RU = {"irina": "female", "denis": "male", "dmitri": "male", "ruslan": "male"}


class Piper:
    name = "piper"

    def voices(self):
        out = [Voice(self.name, n, g, "ru_RU medium") for n, g in PIPER_RU.items()]
        d = os.environ.get("FWTOOL_PIPER_DIR")
        if d:
            out += [Voice(self.name, p, "", "local model") for p in sorted(glob.glob(os.path.join(d, "*.onnx")))]
        return out

    def available(self):
        try:
            import piper  # noqa: F401
            return True
        except ImportError:
            return False

    def _model(self, voice):
        if voice.endswith(".onnx") and os.path.exists(voice):
            return voice
        if voice not in PIPER_RU:
            raise TtsError(f"unknown piper voice {voice!r} (known: {', '.join(PIPER_RU)} or a path to .onnx)")
        from huggingface_hub import hf_hub_download
        base = f"ru/ru_RU/{voice}/medium/ru_RU-{voice}-medium"
        hf_hub_download("rhasspy/piper-voices", base + ".onnx.json")
        return hf_hub_download("rhasspy/piper-voices", base + ".onnx")

    def synth(self, text, voice, wav):
        from piper import PiperVoice
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = self._cache = {}
        if voice not in cache:
            cache[voice] = PiperVoice.load(self._model(voice))
        with wave.open(wav, "wb") as w:
            cache[voice].synthesize_wav(text, w)


# --------------------------------------------------------------------------- eSpeak NG
class ESpeak:
    name = "espeak"
    VARIANTS = {"ru": "", "ru+f2": "female", "ru+f3": "female", "ru+f4": "female", "ru+m3": "male", "ru+m5": "male"}

    def voices(self):
        return [Voice(self.name, n, g, "robotic") for n, g in self.VARIANTS.items()]

    def available(self):
        return shutil.which("espeak-ng") is not None

    def synth(self, text, voice, wav):
        _run(["espeak-ng", "-v", voice, "-s", "150", "-w", wav, text])


# --------------------------------------------------------------------------- any command
class Cmd:
    """--tts-cmd 'my-tts --out {out} --text {text}'  ({text} and {out} are shell-quoted)."""
    name = "cmd"
    template = ""

    def voices(self):
        return [Voice(self.name, "custom", "", "from --tts-cmd")]

    def available(self):
        return bool(self.template)

    def synth(self, text, voice, wav):
        cmd = self.template.replace("{text}", shlex.quote(text)).replace("{out}", shlex.quote(wav))
        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True)
        except subprocess.CalledProcessError as ex:
            raise TtsError(f"tts command failed: {ex.stderr.decode('utf-8', 'replace').strip()[:300]}")


ENGINES = {e.name: e for e in (RHVoice(), Piper(), ESpeak(), Cmd())}
AUTO_ORDER = [("rhvoice", "tatiana"), ("piper", "irina"), ("espeak", "ru+f2")]


def resolve(engine="auto", voice="auto", tts_cmd=None):
    """Return (engine object, voice name)."""
    if tts_cmd:
        ENGINES["cmd"].template = tts_cmd
        engine, voice = "cmd", "custom"
    if engine == "auto":
        for e, v in AUTO_ORDER:
            if ENGINES[e].available():
                return ENGINES[e], (v if voice == "auto" else voice)
        raise TtsError("no TTS engine available: install RHVoice (rhvoice-russian), piper-tts or espeak-ng")
    if engine not in ENGINES:
        raise TtsError(f"unknown engine {engine!r}; choose from: auto, {', '.join(ENGINES)}")
    eng = ENGINES[engine]
    if not eng.available():
        raise TtsError(f"engine {engine} is not available on this system")
    if voice == "auto":
        known = [v.name for v in eng.voices()]
        voice = dict(AUTO_ORDER).get(engine) if dict(AUTO_ORDER).get(engine) in known else known[0]
    return eng, voice


def list_voices(engine=None):
    out = []
    for name, eng in ENGINES.items():
        if engine and name != engine:
            continue
        for v in eng.voices():
            out.append((v, eng.available()))
    return out


def to_mp3(wav, mp3):
    """44.1 kHz mono 128 kbit/s - the format of the stock prompts - with silence trim and loudness norm."""
    _run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af", MP3_FILTER, "-ar", "44100", "-ac", "1",
          "-codec:a", "libmp3lame", "-b:a", "128k", mp3])


def render_overlay(overlay_dir, work, engine="auto", voice="auto", tts_cmd=None, volume="vol2", log=print):
    eng, voice = resolve(engine, voice, tts_cmd)
    with open(os.path.join(overlay_dir, "voice.json"), encoding="utf-8") as fh:
        texts = json.load(fh)
    out = os.path.join(work, "volumes", volume, "files")
    if not os.path.isdir(out):
        raise TtsError(f"{out} not found - run `fwtool unpack` first")
    log(f"voice: {eng.name}:{voice}, {len(texts)} prompts")
    done = 0
    with tempfile.TemporaryDirectory() as td:
        for stem, text in texts.items():
            target = os.path.join(out, stem + ".mp3")
            if not os.path.exists(target):
                log(f"  skip {stem}: no such file in the stock volume")
                continue
            wav = os.path.join(td, "t.wav")
            eng.synth(text, voice, wav)
            to_mp3(wav, target)
            done += 1
    log(f"voice: {done} prompts replaced")
    return done


def samples(text, outdir, engine=None, voice=None, log=print):
    """Write one WAV per available voice so you can listen and choose."""
    os.makedirs(outdir, exist_ok=True)
    n = 0
    for v, ok in list_voices(engine):
        if not ok or (voice and v.name != voice):
            continue
        fn = os.path.join(outdir, f"{v.engine}_{os.path.basename(v.name).replace('+', '_')}.wav")
        try:
            ENGINES[v.engine].synth(text, v.name, fn)
            log(f"  {v}  ->  {fn}")
            n += 1
        except TtsError as ex:
            log(f"  {v}  FAILED: {ex}")
    return n
