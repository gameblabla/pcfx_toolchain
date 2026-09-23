NAME := vdc_animated_256color
OBJECTS := build/main.o build/sprite_data.o
ASSET_TARGETS := build/sprite256_vdc0.bin build/sprite256_vdc1.bin build/sprite256_meta.h
include ../game-example.mk

build/sprite256_vdc0.bin build/sprite256_vdc1.bin build/sprite256_meta.h &: tools/pack_sprite.py ../../main_character_yuri_spritesheet_24x34_shaded_outlined.png $(ROOT)/PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py
	python3 tools/pack_sprite.py ../../main_character_yuri_spritesheet_24x34_shaded_outlined.png build/sprite256_vdc0.bin build/sprite256_vdc1.bin build/sprite256_meta.h

build/main.o: ../game-demo-common/wait_frame.h build/sprite256_meta.h
build/sprite_data.o: build/sprite256_vdc0.bin build/sprite256_vdc1.bin src/sprite_data.S | build
