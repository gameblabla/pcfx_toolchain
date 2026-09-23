NAME := vdc_scroll_map
OBJECTS := build/main.o build/map_data.o
ASSET_TARGETS := build/map_patterns.bin build/map_cells.bin build/map_meta.h
include ../game-example.mk

build/map_patterns.bin build/map_cells.bin build/map_meta.h &: tools/pack_map.py ../../map_test/scene1_section_1_map.png $(ROOT)/PCFX_Skills/pcfx-yuv-palette/rgb_to_yuv.py
	python3 tools/pack_map.py ../../map_test/scene1_section_1_map.png build/map_patterns.bin build/map_cells.bin build/map_meta.h

build/main.o: ../game-demo-common/wait_frame.h build/map_meta.h
build/map_data.o: build/map_patterns.bin build/map_cells.bin src/map_data.S | build
