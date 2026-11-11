# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-extra \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fwtool ./fwtool
COPY overlays ./overlays
RUN pip install --no-cache-dir . pillow unicorn capstone
WORKDIR /w
ENTRYPOINT ["fwtool"]

# Image with local TTS engines for the voice prompts (RHVoice: all Russian voices, Piper, eSpeak NG)
FROM base AS voice
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg rhvoice rhvoice-russian espeak-ng \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir piper-tts huggingface_hub
ENV HF_HOME=/w/.cache/huggingface
