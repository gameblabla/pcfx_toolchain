MODE ?= 4bpp
VALID_MODES := 4bpp 8bpp hicolor 16m
ifeq ($(filter $(MODE),$(VALID_MODES)),)
$(error MODE must be one of: $(VALID_MODES))
endif
BUILD := build/$(MODE)
NAME := king_still_$(MODE)
OBJECTS := $(BUILD)/main.o
ASSET_TARGETS := $(BUILD)/still.bin $(BUILD)/still_meta.h
APPEND := $(BUILD)/still.bin
LBA_DEFINE := BINARY_LBA_STILL_BIN
include ../game-example.mk

$(BUILD)/still.bin $(BUILD)/still_meta.h &: tools/pack_still.py ../../examples/image-cd-viewer/assets/source.png $(ROOT)/PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py
	python3 tools/pack_still.py $(MODE) ../../examples/image-cd-viewer/assets/source.png $(BUILD)/still.bin $(BUILD)/still_meta.h

$(BUILD)/main.o: src/main.c $(BUILD)/still_meta.h $(LBA_HEADER) ../game-demo-common/wait_frame.h | $(BUILD)
	$(CC) $(CFLAGS) -I$(BUILD) -c $< -o $@
