# Shared build plumbing for the game-focused examples. Each sample keeps its
# own source, assets and README; BUILD may be overridden for multi-mode demos.
ROOT          ?= $(abspath ../..)
BUILD         ?= build
NAME          ?= game
V810_GCC      ?= $(if $(V810GCC),$(V810GCC),$(ROOT)/toolchain/v810-gcc)
LIBPCFX       ?= $(ROOT)/vendor/libpcfx
CDLINK        ?= $(ROOT)/toolchain/bin/pcfx-cdlink-large
PCFXEMU       ?= $(ROOT)/scripts/run-headless.sh
BIOSDIR       ?= $(PCFX_BIOS_DIR)
LBA_DEFINE    ?= BINARY_LBA_NONE_BIN
APPEND        ?=
OBJECTS       ?= $(BUILD)/main.o
ASSET_TARGETS ?=
PREFIX        := v810
CC            := $(V810_GCC)/bin/v810-gcc
AS            := $(V810_GCC)/bin/v810-as
LD            := $(V810_GCC)/bin/v810-ld
OBJCOPY       := $(V810_GCC)/bin/v810-objcopy
CFLAGS        := -I$(LIBPCFX)/include -I$(V810_GCC)/include -I$(BUILD) \
                 -O2 -Wall -std=gnu99 -mv810 -msda=256 \
                 -mno-prolog-function $(EXTRA)
LDFLAGS       := -T$(LIBPCFX)/ldscripts/v810.x \
                 -L$(LIBPCFX) -L$(V810_GCC)/lib \
                 -L$(V810_GCC)/$(PREFIX)/lib \
                 -L$(V810_GCC)/lib/gcc/$(PREFIX)/4.9.4 \
                 $(V810_GCC)/$(PREFIX)/lib/crt0.o
LIBS          := -lpcfx -lc -lsim -lgcc
PROGRAM       := $(BUILD)/$(NAME).program.bin
ELF           := $(BUILD)/$(NAME).elf
DISC_PREFIX   := $(BUILD)/$(NAME)
CDLINK_TXT    := $(BUILD)/cdlink.txt
LBA_HEADER    := $(BUILD)/lbas.h

.PHONY: all assets boot cd run clean
all: cd
assets: $(ASSET_TARGETS)
boot: $(PROGRAM)

$(BUILD):
	mkdir -p $@

$(LBA_HEADER): | $(BUILD)
	printf '#ifndef GAME_LBAS_H\n#define GAME_LBAS_H\n#define $(LBA_DEFINE) 0u\n#endif\n' > $@

$(BUILD)/%.o: src/%.c $(LBA_HEADER) $(ASSET_TARGETS) | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/%.o: src/%.S $(ASSET_TARGETS) | $(BUILD)
	$(AS) -I. -I$(BUILD) $< -o $@

$(ELF): $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map $(BUILD)/$(NAME).map

$(PROGRAM): $(ELF)
	$(OBJCOPY) -O binary $< $@

$(CDLINK_TXT): $(PROGRAM) $(APPEND) ../game-example.mk | $(BUILD)
	{ printf 'binary %s\nlbaheader %s\nname PCFX GAME EXAMPLE\nmaker homebrew\nmakerid HBR\ncountry 1\nversion 256\ndate 20260923\n' '$(notdir $(PROGRAM))' '$(notdir $(LBA_HEADER))'; \
	  if test -n '$(APPEND)'; then printf 'append %s\n' '$(notdir $(APPEND))'; fi; } > $@

cd: $(CDLINK_TXT)
	@test -x "$(CDLINK)" || { echo "missing $(CDLINK); run $(ROOT)/scripts/build-host-tools.sh" >&2; exit 1; }
	@if test -z '$(APPEND)'; then \
	  (cd $(BUILD) && $(CDLINK) cdlink.txt $(notdir $(DISC_PREFIX))); \
	else \
	  for pass in 1 2 3 4; do \
	    cp $(LBA_HEADER) $(BUILD)/lbas.prev 2>/dev/null || true; \
	    $(MAKE) --no-print-directory boot || exit 1; \
	    (cd $(BUILD) && $(CDLINK) cdlink.txt $(notdir $(DISC_PREFIX))) >/dev/null || exit 1; \
	    if cmp -s $(LBA_HEADER) $(BUILD)/lbas.prev; then \
	      echo "disc: $(DISC_PREFIX).cue (LBA converged, pass $$pass)"; exit 0; \
	    fi; \
	  done; echo 'LBA header did not converge' >&2; exit 1; \
	fi

run: cd
	@if test -n '$(BIOSDIR)'; then \
	  $(PCFXEMU) --bios-dir "$(BIOSDIR)" --pcfx --frames 1800 \
	    --screenshot $(BUILD)/$(NAME).png $(CURDIR)/$(DISC_PREFIX).cue; \
	else \
	  $(PCFXEMU) --pcfx --frames 1800 \
	    --screenshot $(BUILD)/$(NAME).png $(CURDIR)/$(DISC_PREFIX).cue; \
	fi

clean:
	rm -rf $(BUILD)
