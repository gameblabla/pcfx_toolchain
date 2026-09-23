NAME := vdc_animated_16color
OBJECTS := build/main.o build/sprite_data.o
ASSET_TARGETS := build/sprite16_patterns.bin build/sprite16_meta.h
include ../game-example.mk

build/sprite16_patterns.bin build/sprite16_meta.h &: tools/pack_sprite.py ../../main_character_yuri_spritesheet_24x34_shaded_outlined.png $(ROOT)/PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py
	python3 tools/pack_sprite.py ../../main_character_yuri_spritesheet_24x34_shaded_outlined.png build/sprite16_patterns.bin build/sprite16_meta.h

build/main.o: ../game-demo-common/wait_frame.h build/sprite16_meta.h
build/sprite_data.o: build/sprite16_patterns.bin src/sprite_data.S | build
