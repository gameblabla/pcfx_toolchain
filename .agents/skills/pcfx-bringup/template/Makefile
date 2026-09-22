# PC-FX project template Makefile (self-contained; does not use example.mk).
#
#   export PCFX_TOOLKIT_ROOT=..       # toolkit root, relative to this project
#   export V810GCC=$PCFX_TOOLKIT_ROOT/prebuilt/v810-gcc
#   export PATH=$V810GCC/bin:$PATH
#   make            -> game.elf / game.bin
#   make cd         -> game.cue + game.bin (bootable disc image)
#   make run        -> build the disc and screenshot it in the emulator
#   make clean
#
# PCFX_TOOLKIT_ROOT points at this bundle. The automatic candidates cover a project
# copied under the toolkit root and the original template location; override it for
# a project copied elsewhere.

PCFX_TOOLKIT_ROOT ?= $(or $(foreach d,. .. ../.. ../../..,$(if $(wildcard $(d)/vendor/libpcfx/ldscripts/v810.x),$(d))),.)
V810GCC       ?= $(PCFX_TOOLKIT_ROOT)/prebuilt/v810-gcc
LIBPCFX       ?= $(PCFX_TOOLKIT_ROOT)/vendor/libpcfx
PCFXEMU       ?= $(PCFX_TOOLKIT_ROOT)/prebuilt/bin/pcfx-headless
BINCAT        ?= $(PCFX_TOOLKIT_ROOT)/prebuilt/bin/bincat
CDLINK        ?= $(PCFX_TOOLKIT_ROOT)/prebuilt/bin/pcfx-cdlink
BIOSDIR       ?= $(PCFX_BIOS_DIR)

PREFIX         = v810
CC             = $(PREFIX)-gcc
AS             = $(PREFIX)-as
LD             = $(PREFIX)-ld
OBJCOPY        = $(PREFIX)-objcopy
NAME           = game
OBJECTS        = src/main.o

# -mv810      : target the V810 core
# -msda=256   : small-data area; globals under 256B get gp-relative access
# -mno-prolog-function : no __save/__load trampolines (faster calls, bigger code)
CFLAGS         = -I$(V810GCC)/include/ -I$(V810GCC)/$(PREFIX)/include/ \
                 -O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function \
                 $(EXTRA)

LDFLAGS        = -T$(LIBPCFX)/ldscripts/v810.x \
                 -L$(V810GCC)/lib/ -L$(V810GCC)/$(PREFIX)/lib/ \
                 -L$(V810GCC)/lib/gcc/$(PREFIX)/4.9.4/ \
                 $(V810GCC)/$(PREFIX)/lib/crt0.o

LIBS           = -lpcfx -lc -lsim -lgcc

.PHONY: all cd run clean

all: $(NAME).bin

%.o: %.c
	$(CC) $(CFLAGS) $< -c -o $@
%.o: %.S
	$(AS) $(ASFLAGS) $< -o $@

$(NAME).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map $(NAME).map

$(NAME).bin: $(NAME).elf
	$(OBJCOPY) -O binary $< $@

# bincat concatenates the program (+ any extra data files) into out.bin and
# emits lbas.h with each file's disc LBA. pcfx-cdlink then wraps out.bin in a
# bootable PC-FX disc described by cdlink.txt.
cd: $(NAME).bin
	$(BINCAT) out.bin lbas.h $(NAME).bin $(ADD_FILES)
	$(CDLINK) cdlink.txt $(NAME)

# ~1200 frames of BIOS boot animation before your code draws anything.
run: cd
	$(PCFXEMU) --bios-dir $(BIOSDIR) --pcfx --frames 1800 \
	    --screenshot shot.png $(NAME).cue

clean:
	rm -f $(OBJECTS) $(NAME).elf $(NAME).bin $(NAME).map \
	      out.bin lbas.h $(NAME).cue shot.png
