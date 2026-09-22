This is a PC-FX project that renders a complex textured 3D character (thousands of faces)
into a 256x240 8bpp software raster, with a black outline, presented through KING BG0.

Something regressed in the renderer. The character is still on screen and the program
still runs — but large parts of the model are missing or wrong, and the geometry that
does appear is not what the asset contains. Confusingly, this build also runs *faster*
than the last good one, so at first it looked like an optimization that had worked.

The source asset has not been changed and must not be changed: keep every vertex and
face, keep the 256x240 output, keep the outline, and do not lower any quality setting to
make the picture "look right".

Find what actually broke, fix it, rebuild the disc properly, and verify with a screenshot
that the full character is drawn again. Be careful about how you verify: a faster frame
rate is not evidence of correctness here.
