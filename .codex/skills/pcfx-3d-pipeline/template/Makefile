# cube3d - rotating flat-shaded cube, software 3D on PC-FX.
#
#   export PCFX_TOOLKIT_ROOT=..       # toolkit root, relative to this project
#   export V810_GCC=$PCFX_TOOLKIT_ROOT/toolchain/v810-gcc
#   export PATH=$V810_GCC/bin:$PATH
#   make            -> cube3d.bin
#   make cd         -> bootable disc (cube3d.cue)
#   make run        -> build the disc and screenshot it (1800 frames)
#   make prof       -> build with profiling and dump the V810 profile
#   make hosttest   -> build and run the host geometry oracle
#   make clean
#
# PCFX_TOOLKIT_ROOT points at this bundle. The automatic candidates cover a project
# copied under the toolkit root and the original template location; override it for
# a project copied elsewhere.

PCFX_TOOLKIT_ROOT ?= $(or $(foreach d,. .. ../.. ../../..,$(if $(wildcard $(d)/vendor/libpcfx/ldscripts/v810.x),$(d))),.)
V810_GCC      ?= $(if $(V810GCC),$(V810GCC),$(PCFX_TOOLKIT_ROOT)/toolchain/v810-gcc)
V810GCC       ?= $(V810_GCC)
LIBPCFX       ?= $(PCFX_TOOLKIT_ROOT)/vendor/libpcfx
PCFXEMU       ?= $(PCFX_TOOLKIT_ROOT)/toolchain/bin/pcfx-headless
PCFXEMU_PROF  ?= $(PCFX_TOOLKIT_ROOT)/toolchain/bin/pcfx-headless-prof
BINCAT        ?= $(PCFX_TOOLKIT_ROOT)/toolchain/bin/bincat
CDLINK        ?= $(PCFX_TOOLKIT_ROOT)/toolchain/bin/pcfx-cdlink
BIOSDIR       ?= $(PCFX_BIOS_DIR)

PREFIX         = v810
CC             = $(PREFIX)-gcc
AS             = $(PREFIX)-as
LD             = $(PREFIX)-ld
OBJCOPY        = $(PREFIX)-objcopy
NAME           = cube3d
OBJECTS        = src/cube3d.o

CFLAGS         = -I$(V810_GCC)/include/ -I$(V810_GCC)/$(PREFIX)/include/ \
                 -O2 -Wall -std=gnu99 -mv810 -msda=256 -mno-prolog-function \
                 $(EXTRA)

LDFLAGS        = -T$(LIBPCFX)/ldscripts/v810.x \
                 -L$(V810_GCC)/lib/ -L$(V810_GCC)/$(PREFIX)/lib/ \
                 -L$(V810_GCC)/lib/gcc/$(PREFIX)/4.9.4/ \
                 $(V810_GCC)/$(PREFIX)/lib/crt0.o

LIBS           = -lpcfx -lc -lsim -lgcc

.PHONY: all cd run prof hosttest clean

all: $(NAME).bin

src/sin_table.h: tools/gen_sin.py
	python3 tools/gen_sin.py > $@

%.o: %.c src/sin_table.h
	$(CC) $(CFLAGS) $< -c -o $@
%.o: %.S
	$(AS) $(ASFLAGS) $< -o $@

$(NAME).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map $(NAME).map

$(NAME).bin: $(NAME).elf
	$(OBJCOPY) -O binary $< $@

cd: $(NAME).bin
	$(BINCAT) out.bin lbas.h $(NAME).bin
	$(CDLINK) cdlink.txt $(NAME)

run: cd
	$(PCFXEMU) --bios-dir $(BIOSDIR) --pcfx --frames 1800 \
	    --screenshot shot.png $(NAME).cue

prof: cd
	$(PCFXEMU_PROF) --bios-dir $(BIOSDIR) --pcfx --frames 1800 \
	    $(NAME).cue 2>&1 | sed -n '/V810 PROFILE/,/^####################/p'

hosttest: src/sin_table.h
	gcc -O2 -w -I$(V810_GCC)/$(PREFIX)/include/ -I$(LIBPCFX)/include \
	    -o hosttest hosttest.c
	./hosttest

clean:
	rm -f $(OBJECTS) $(NAME).elf $(NAME).bin $(NAME).map \
	      out.bin lbas.h $(NAME).cue shot.png src/sin_table.h hosttest
