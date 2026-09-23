# Static RAINBOW image viewer. Fit the source offline, encode it, append it
# to the disc, and load the stream into KRAM during startup.

ROOT           := $(abspath ../..)
V810_GCC       ?= $(if $(V810GCC),$(V810GCC),$(ROOT)/toolchain/v810-gcc)
V810GCC        ?= $(V810_GCC)
LIBPCFX        ?= $(ROOT)/vendor/libpcfx
CDLINK         ?= $(ROOT)/toolchain/bin/pcfx-cdlink-large
PYTHON         ?= python3
NAME           ?= image_cd_viewer
PREFIX         := v810
IMAGE          ?= assets/source.png
FIT            ?= contain
SCALE          ?= auto
# eris_cd_read_kram is hardware-confirmed for one arm of 16 KiB.
MAX_BYTES      ?= 16384

CC             := $(V810_GCC)/bin/v810-gcc
LD             := $(V810_GCC)/bin/v810-ld
OBJCOPY        := $(V810_GCC)/bin/v810-objcopy
CFLAGS         := -I$(LIBPCFX)/include -I$(V810_GCC)/include -Ibuild \
                  -O2 -Wall -std=gnu99 -mv810 -msda=256 \
                  -mno-prolog-function $(EXTRA)
LDFLAGS        := -T$(LIBPCFX)/ldscripts/v810.x \
                  -L$(LIBPCFX) -L$(V810_GCC)/lib \
                  -L$(V810_GCC)/$(PREFIX)/lib \
                  -L$(V810_GCC)/lib/gcc/$(PREFIX)/4.9.4 \
                  $(V810_GCC)/$(PREFIX)/lib/crt0.o
LIBS           := -lpcfx -lc -lsim -lgcc

.PHONY: all image boot cd run validate clean FORCE
all: cd

# Re-encode when the image or any encode setting changes, not on every make.
ENCODE_ARGS    := $(IMAGE) $(FIT) $(SCALE) $(MAX_BYTES)
build/encode.args: FORCE
	@mkdir -p build
	@echo '$(ENCODE_ARGS)' | cmp -s - $@ || echo '$(ENCODE_ARGS)' > $@

build/fitted.png: $(IMAGE) build/encode.args tools/prepare_image.py
	$(PYTHON) tools/prepare_image.py $(IMAGE) $@ --fit $(FIT)

build/rainbow_still.h: build/still.bin
build/still.bin: build/fitted.png build/encode.args \
		$(ROOT)/tools/rainbow/rainbow.py \
		$(ROOT)/tools/rainbow/rainbow_codec.py \
		$(ROOT)/tools/rainbow/rainbow_decode.py \
		$(ROOT)/tools/rainbow/pcfv.py
	$(PYTHON) $(ROOT)/tools/rainbow/rainbow.py image build/fitted.png build/still.bin \
	  --fit strict --scale $(SCALE) --max-bytes $(MAX_BYTES) \
	  --header build/rainbow_still.h --preview build/still_host.png \
	  --report build/still.json

image: build/still.bin

build/lbas.h:
	@mkdir -p build
	echo '#define BINARY_LBA_BUILD_STILL_BIN 0u' > $@

build/main.o: src/main.c build/lbas.h build/rainbow_still.h
	$(CC) $(CFLAGS) -c $< -o $@

build/$(NAME).elf: build/main.o
	$(LD) $(LDFLAGS) $^ $(LIBS) -o $@ -Map build/$(NAME).map

build/$(NAME).program.bin: build/$(NAME).elf
	$(OBJCOPY) -O binary $< $@

boot: build/$(NAME).program.bin

build/cdlink.txt:
	@mkdir -p build
	printf 'binary build/$(NAME).program.bin\nlbaheader build/lbas.h\nname IMAGE CD VIEWER\nmaker homebrew\nmakerid HBR\ncountry 1\nversion 256\ndate 20260923\nappend build/still.bin\n' > $@

# The boot program embeds the asset LBA, and the asset LBA depends on the boot
# size: rebuild until the generated header stops changing.
cd: build/still.bin build/cdlink.txt
	@test -x "$(CDLINK)" || { echo "missing $(CDLINK); run ../../scripts/build-host-tools.sh" >&2; exit 1; }
	@for pass in 1 2 3 4; do \
	  cp build/lbas.h build/lbas.prev 2>/dev/null || true; \
	  $(MAKE) --no-print-directory boot || exit 1; \
	  $(CDLINK) build/cdlink.txt $(NAME) >/dev/null || exit 1; \
	  if cmp -s build/lbas.h build/lbas.prev; then echo "disc: $(NAME).cue (LBA converged, pass $$pass)"; exit 0; fi; \
	done; echo "LBA header did not converge" >&2; exit 1

run: cd
	$(ROOT)/scripts/run-headless.sh --bios-dir "$(PCFX_BIOS_DIR)" --pcfx \
		--frames 1800 --screenshot build/$(NAME).png $(CURDIR)/$(NAME).cue

validate: cd
	$(PYTHON) $(ROOT)/tools/rainbow/validate_still.py --cue $(NAME).cue \
	  --image build/still_host.png --fit strict --frames 1800,1860 --pan 0 \
	  --out build/validate

clean:
	rm -rf build $(NAME).bin $(NAME).cue
