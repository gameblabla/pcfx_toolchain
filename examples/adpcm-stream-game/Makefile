NAME := adpcm_stream_game
APPEND := build/theme.adp
LBA_DEFINE := BINARY_LBA_THEME_ADP
ASSET_TARGETS := build/theme.adp build/theme_meta.h
include ../game-example.mk

build/theme.adp build/theme_meta.h &: tools/make_theme.py $(ROOT)/vendor/doompcfx/tools/gen_pcfx_sfx.py
	python3 tools/make_theme.py build/theme.adp build/theme_meta.h

build/main.o: src/main.c build/theme_meta.h $(LBA_HEADER) ../game-demo-common/screen.h ../game-demo-common/wait_frame.h | build
	$(CC) $(CFLAGS) -I$(ROOT)/examples/game-demo-common -c $< -o $@
