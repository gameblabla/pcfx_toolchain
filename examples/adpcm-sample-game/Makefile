NAME := adpcm_sample_game
APPEND := build/coin.adp
LBA_DEFINE := BINARY_LBA_COIN_ADP
ASSET_TARGETS := build/coin.adp build/sfx_meta.h
include ../game-example.mk

build/coin.adp build/sfx_meta.h &: tools/make_sfx.py $(ROOT)/vendor/doompcfx/tools/gen_pcfx_sfx.py
	python3 tools/make_sfx.py build/coin.adp build/sfx_meta.h

build/main.o: src/main.c build/sfx_meta.h $(LBA_HEADER) ../game-demo-common/screen.h ../game-demo-common/wait_frame.h | build
	$(CC) $(CFLAGS) -I$(ROOT)/examples/game-demo-common -c $< -o $@
