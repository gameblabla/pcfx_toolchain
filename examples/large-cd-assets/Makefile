# Large-game CD asset example. The boot binary is kept separate from an external
# append file so the asset does not consume the BIOS-loaded RAM image.

ROOT           := $(abspath ../..)
V810_GCC       ?= $(if $(V810GCC),$(V810GCC),$(ROOT)/toolchain/v810-gcc)
V810GCC        ?= $(V810_GCC)
LIBPCFX        ?= $(ROOT)/vendor/libpcfx
CDLINK         ?= $(ROOT)/toolchain/bin/pcfx-cdlink-large
NAME           ?= large_assets
PREFIX         := v810
PYTHON         ?= python3

CC             := $(V810_GCC)/bin/v810-gcc
LD             := $(V810_GCC)/bin/v810-ld
OBJCOPY        := $(V810_GCC)/bin/v810-objcopy
OBJECTS        := build/main.o
BOOT_BIN       := build/$(NAME)_boot.bin
CD_PREFIX      := build/$(NAME)_disc
ASSET          := assets/large_blob.dat
CDLINK_TXT     := build/cdlink.txt
LBA_HEADER     := build/lbas.h

CFLAGS         := -I$(LIBPCFX)/include -I$(V810_GCC)/include \
                  -O2 -Wall -std=gnu99 -mv810 -msda=256 \
                  -mno-prolog-function $(EXTRA)
LDFLAGS        := -T$(LIBPCFX)/ldscripts/v810.x \
                  -L$(LIBPCFX) -L$(V810_GCC)/lib \
                  -L$(V810_GCC)/$(PREFIX)/lib \
                  -L$(V810_GCC)/lib/gcc/$(PREFIX)/4.9.4 \
                  $(V810_GCC)/$(PREFIX)/lib/crt0.o
LIBS           := -lpcfx -lc -lsim -lgcc

.PHONY: all asset cd inspect run clean

all: $(BOOT_BIN)

build/%.o: src/%.c
	@mkdir -p build
	$(CC) $(CFLAGS) -c $< -o $@

build/$(NAME).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map build/$(NAME).map

$(BOOT_BIN): build/$(NAME).elf
	$(OBJCOPY) -O binary $< $@

asset: $(ASSET)

$(ASSET):
	$(PYTHON) $(ROOT)/tools/pcfx_large_game.py make-fixture $@ --bytes 393216

$(CDLINK_TXT): $(BOOT_BIN) $(ASSET)
	@mkdir -p build
	$(PYTHON) $(ROOT)/tools/pcfx_large_game.py write-cdlink \
		--boot $(BOOT_BIN) --asset $(ASSET) --output $@ \
		--lba-header $(LBA_HEADER) --name "PC-FX Large Asset Example"

$(CD_PREFIX).bin $(CD_PREFIX).cue: $(CDLINK_TXT)
	@test -x "$(CDLINK)" || { echo "missing $(CDLINK); run ../../scripts/build-host-tools.sh" >&2; exit 1; }
	$(CDLINK) $(CDLINK_TXT) $(CD_PREFIX)

cd: $(CD_PREFIX).cue

inspect: $(LBA_HEADER)
	$(PYTHON) $(ROOT)/tools/pcfx_large_game.py inspect-lbas $(LBA_HEADER)

run: cd
	$(ROOT)/scripts/run-headless.sh --bios-dir "$(BIOSDIR)" --pcfx \
		--frames 1800 --screenshot build/$(NAME).png $(CURDIR)/$(CD_PREFIX).cue

clean:
	rm -rf build assets/large_blob.dat
