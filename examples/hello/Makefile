# Minimal verified PC-FX bring-up example.

ROOT           := $(abspath ../..)
V810GCC        ?= $(ROOT)/prebuilt/v810-gcc
LIBPCFX        ?= $(ROOT)/vendor/libpcfx
BINCAT         ?= $(ROOT)/prebuilt/bin/bincat
CDLINK         ?= $(ROOT)/prebuilt/bin/pcfx-cdlink
NAME           ?= game
PREFIX         := v810

CC             := $(V810GCC)/bin/v810-gcc
LD             := $(V810GCC)/bin/v810-ld
OBJCOPY        := $(V810GCC)/bin/v810-objcopy
OBJECTS        := src/main.o

CFLAGS         := -I$(LIBPCFX)/include -I$(V810GCC)/include \
                  -O2 -Wall -std=gnu99 -mv810 -msda=256 \
                  -mno-prolog-function $(EXTRA)
LDFLAGS        := -T$(LIBPCFX)/ldscripts/v810.x \
                  -L$(LIBPCFX) -L$(V810GCC)/lib \
                  -L$(V810GCC)/$(PREFIX)/lib \
                  -L$(V810GCC)/lib/gcc/$(PREFIX)/4.9.4 \
                  $(V810GCC)/$(PREFIX)/lib/crt0.o
LIBS           := -lpcfx -lc -lsim -lgcc

.PHONY: all cd huexe run clean

all: $(NAME).bin

src/%.o: src/%.c
	$(CC) $(CFLAGS) -c $< -o $@

$(NAME).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map $(NAME).map

$(NAME).bin: $(NAME).elf
	$(OBJCOPY) -O binary $< $@

cd: $(NAME).bin
	@test -x "$(BINCAT)" || { echo "missing $(BINCAT); run scripts/build-host-tools.sh" >&2; exit 1; }
	@test -x "$(CDLINK)" || { echo "missing $(CDLINK); run scripts/build-host-tools.sh" >&2; exit 1; }
	$(BINCAT) out.bin lbas.h $(NAME).bin
	$(CDLINK) cdlink.txt $(NAME)

huexe: $(NAME).elf
	python3 $(ROOT)/tools/hu_exe.py $(NAME).elf $(NAME).ex --inspect

run: cd
	$(ROOT)/scripts/run-headless.sh --bios-dir "$(BIOSDIR)" --pcfx \
		--frames 1800 --screenshot $(NAME).png $(CURDIR)/$(NAME).cue

clean:
	rm -f $(OBJECTS) $(NAME).elf $(NAME).bin $(NAME).map \
		out.bin lbas.h $(NAME).cue $(NAME).png $(NAME).ex
