NAME := bios_save_game
include ../game-example.mk

build/main.o: src/main.c ../game-demo-common/screen.h ../game-demo-common/wait_frame.h | build
	$(CC) $(CFLAGS) -I$(ROOT)/examples/game-demo-common -c $< -o $@
