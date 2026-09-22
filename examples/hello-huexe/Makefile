# The same bring-up program emitted as a HuEXE001 PC-FXGA executable.

ROOT           := $(abspath ../..)
V810GCC        ?= $(ROOT)/prebuilt/v810-gcc
LIBPCFX        ?= $(ROOT)/vendor/libpcfx
NAME           ?= hello_huexe
PREFIX         := v810

CC             := $(V810GCC)/bin/v810-gcc
LD             := $(V810GCC)/bin/v810-ld
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

.PHONY: all huexe run clean

all: huexe

src/%.o: src/%.c
	$(CC) $(CFLAGS) -c $< -o $@

$(NAME).elf: $(OBJECTS)
	$(LD) $(LDFLAGS) $(OBJECTS) $(LIBS) -o $@ -Map $(NAME).map

huexe: $(NAME).elf
	python3 $(ROOT)/tools/hu_exe.py $(NAME).elf $(NAME).ex --inspect

run: huexe
	$(ROOT)/scripts/run-headless.sh --bios-dir "$(BIOSDIR)" --pcfxga \
		--auto-run --frames 1800 --screenshot $(NAME).png $(CURDIR)/$(NAME).ex

clean:
	rm -f $(OBJECTS) $(NAME).elf $(NAME).map $(NAME).ex $(NAME).png
