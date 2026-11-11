# Two stages:  make unpack  ->  edit files in work/  ->  make pack   (result: release/UC5300P.bin)
IMAGE   ?= uc5300p-fwtool
FW      ?= stock/UC5300P.bin
OVERLAY ?= ru
ENGINE  ?= auto
VOICE   ?= auto
TEXT    ?= Переход в режим движения.
RUN      = docker run --rm -v $(CURDIR):/w $(IMAGE)
RUNVOICE = docker run --rm -v $(CURDIR):/w $(IMAGE):voice

.PHONY: image image-voice ru ru-novoice voices sample unpack overlay voice pack verify info test release clean

image:
	docker build --target base -t $(IMAGE) .
image-voice:
	docker build --target voice -t $(IMAGE):voice .

# ONE COMMAND: stock firmware -> translated firmware (release/UC5300P.bin)
#   make ru FW=stock/UC5300P.bin ENGINE=rhvoice VOICE=anna
ru: image-voice
	$(RUNVOICE) translate /w/$(FW) /w/release/UC5300P.bin --overlay /w/overlays/$(OVERLAY) --engine $(ENGINE) --voice $(VOICE)
ru-novoice: image
	$(RUN) translate /w/$(FW) /w/release/UC5300P.bin --overlay /w/overlays/$(OVERLAY) --no-voice

# list TTS voices / write a WAV sample per voice to voice-samples/ (listen, then pick ENGINE and VOICE)
voices: image-voice
	$(RUNVOICE) voices
sample: image-voice
	$(RUNVOICE) voices --sample "$(TEXT)" --out /w/voice-samples

# stage 1: stock firmware -> work/ (folders and files you can edit)
unpack: image
	rm -rf work
	$(RUN) unpack /w/$(FW) /w/work

# optional: apply a translation overlay (overlays/<name>) to work/
overlay: image
	$(RUN) overlay /w/overlays/$(OVERLAY) /w/work

# optional: replace voice prompts with a local female TTS voice
voice: image-voice
	$(RUNVOICE) voice /w/overlays/$(OVERLAY) /w/work --engine $(ENGINE) --voice $(VOICE)

# stage 2: work/ -> release/UC5300P.bin  (+ MD5 / CRC / device-code emulation checks)
pack: image
	$(RUN) pack /w/work /w/release/UC5300P.bin --verify --emulate

verify: image
	$(RUN) verify /w/$(FILE) --emulate

info: image
	$(RUN) info /w/$(FW)

test:
	python -m pip install -q -e '.[test,emulate]' && python -m pytest -q

# upload release/ to a GitHub release (needs the GitHub CLI: gh auth login)
release: pack
	gh release create $(TAG) release/UC5300P.bin release/BUILD_INFO.json --title "$(TAG)" --notes-file RELEASE_NOTES.md

clean:
	rm -rf work release
