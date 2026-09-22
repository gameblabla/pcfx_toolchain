# Vendored pcfx-cdlink (host tool).
#
# The /opt system build and the old checked-in binary support neither the
# `append`/`lbaheader` directives this project's CD assets need, nor the
# `cddaheader`/`cddadir` directives the CD-DA soundtrack needs, so the source
# lives here and is built as part of the normal `make cd`.

OBJECTS = pcfx-cdlink.o
TARGETS = pcfx-cdlink
ifeq ($(OS),Windows_NT)
LIBS   += -lws2_32
endif
CFLAGS  += -O2
LDFLAGS += -s
CC       = gcc

.PHONY: all clean

all: $(TARGETS)

%.o: %.c
	$(CC) $(CFLAGS) -c -o $@ $<

pcfx-cdlink: pcfx-cdlink.o
	$(CC) $(LDFLAGS) pcfx-cdlink.o -o $@ $(LIBS)

pcfx-cdlink.o: pcfx-cdlink.c boot.h

clean:
	$(RM) $(OBJECTS) $(TARGETS)
