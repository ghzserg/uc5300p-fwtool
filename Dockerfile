# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-extra \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fwtool ./fwtool
COPY overlays ./overlays
COPY tools ./tools
RUN pip install --no-cache-dir . pillow unicorn capstone
WORKDIR /w
ENTRYPOINT ["fwtool"]

# Optional image with a local female Russian TTS (Piper) for `make voice`
FROM base AS voice
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir piper-tts huggingface_hub
ENV HF_HOME=/w/.cache/huggingface
ENTRYPOINT ["python", "/app/tools/gen_voice.py"]
