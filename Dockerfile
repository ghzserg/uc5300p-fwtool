# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-extra xfonts-terminus \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fwtool ./fwtool
COPY overlays ./overlays
RUN pip install --no-cache-dir . pillow unicorn capstone
WORKDIR /w
ENTRYPOINT ["fwtool"]

# Image with local TTS engines for the voice prompts (RHVoice: all Russian voices, Piper, eSpeak NG).
# Ubuntu, not Debian: RHVoice is packaged only there (noble/multiverse).
FROM ubuntu:24.04 AS voice
RUN sed -i 's/^Components: .*/Components: main restricted universe multiverse/' /etc/apt/sources.list.d/ubuntu.sources || true
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ffmpeg rhvoice rhvoice-russian espeak-ng \
    fonts-dejavu-extra xfonts-terminus \
 && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fwtool ./fwtool
COPY overlays ./overlays
RUN pip install --no-cache-dir . pillow unicorn capstone piper-tts huggingface_hub
ENV HF_HOME=/w/.cache/huggingface
WORKDIR /w
ENTRYPOINT ["fwtool"]
