import os
import shutil
import sys

import pytest

from fwtool import tts


def _fake_rhvoice(tmp_path):
    for name, lang, gender in (("tatiana", "Russian", "female"), ("pavel", "Russian", "male"),
                               ("alan", "English", "male")):
        d = tmp_path / name
        d.mkdir()
        (d / "voice.info").write_text(f"name={name.title()}\nlanguage={lang}\ngender={gender}\n")


def test_rhvoice_discovers_only_russian_voices(tmp_path, monkeypatch):
    _fake_rhvoice(tmp_path)
    monkeypatch.setenv("FWTOOL_RHVOICE_DIRS", str(tmp_path))
    names = {(v.name, v.gender) for v in tts.ENGINES["rhvoice"].voices() if v.name in ("tatiana", "pavel", "alan")}
    assert names == {("tatiana", "female"), ("pavel", "male")}


def test_auto_prefers_rhvoice_tatiana_then_piper(monkeypatch):
    avail = {"rhvoice": True, "piper": True, "espeak": True}
    for n, v in avail.items():
        monkeypatch.setattr(tts.ENGINES[n], "available", lambda v=v: v, raising=False)
    monkeypatch.setattr(tts.ENGINES["rhvoice"], "voices", lambda: [tts.Voice("rhvoice", "tatiana")])
    eng, voice = tts.resolve("auto", "auto")
    assert (eng.name, voice) == ("rhvoice", "tatiana")
    monkeypatch.setattr(tts.ENGINES["rhvoice"], "available", lambda: False)
    assert tts.resolve("auto", "auto")[0].name == "piper"
    with pytest.raises(tts.TtsError):
        tts.resolve("rhvoice", "tatiana")
    with pytest.raises(tts.TtsError):
        tts.resolve("nope", "x")


def test_custom_command_engine_and_overlay_rendering(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    # a "TTS" that writes one second of silence
    gen = tmp_path / "gen.py"
    gen.write_text("import sys, wave\nw = wave.open(sys.argv[1], 'wb')\nw.setnchannels(1); w.setsampwidth(2)\n"
                   "w.setframerate(22050); w.writeframes(b'\\x10\\x00' * 22050); w.close()\n")
    cmd = f"{sys.executable} {gen} {{out}} {{text}}"
    ov = tmp_path / "ov"
    ov.mkdir()
    (ov / "voice.json").write_text('{"hello": "Привет", "missing": "Нет"}', encoding="utf-8")
    files = tmp_path / "work" / "volumes" / "vol2" / "files"
    files.mkdir(parents=True)
    (files / "hello.mp3").write_bytes(b"old")
    done = tts.render_overlay(str(ov), str(tmp_path / "work"), tts_cmd=cmd, log=lambda *_: None)
    assert done == 1                                   # `missing` is not in the volume -> skipped
    assert (files / "hello.mp3").read_bytes() != b"old"
    tts.ENGINES["cmd"].template = ""


def test_samples_skip_unavailable_engines(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tts.ENGINES["espeak"], "available", lambda: True)
    monkeypatch.setattr(tts.ENGINES["espeak"], "synth", lambda text, voice, wav: calls.append(voice) or open(wav, "wb").close())
    for n in ("rhvoice", "piper", "cmd"):
        monkeypatch.setattr(tts.ENGINES[n], "available", lambda: False)
    assert tts.samples("тест", str(tmp_path), log=lambda *_: None) == len(tts.ENGINES["espeak"].VARIANTS)
    assert "ru+f2" in calls


def test_auto_engine_finds_voice_by_name(monkeypatch):
    for n in ("rhvoice", "piper", "espeak"):
        monkeypatch.setattr(tts.ENGINES[n], "available", lambda: True)
    monkeypatch.setattr(tts.ENGINES["rhvoice"], "voices", lambda: [tts.Voice("rhvoice", "anna")])
    assert tts.resolve("auto", "anna")[0].name == "rhvoice"
    assert tts.resolve("auto", "denis")[0].name == "piper"          # only Piper has denis
    with pytest.raises(tts.TtsError):
        tts.resolve("auto", "nobody")
