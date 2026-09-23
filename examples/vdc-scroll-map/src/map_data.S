.section .rodata
.align 2
.global _map_tile_patterns
_map_tile_patterns:
.incbin "build/map_patterns.bin"
.global _map_cell_ids
_map_cell_ids:
.incbin "build/map_cells.bin"
