This PC-FX project (`cube3d`) is supposed to draw a spinning grey cube on a black
background. It builds and boots, but the screen is completely black — nothing is ever
drawn.

What I have already checked myself:

- The KRAM path works: a static checkerboard written once shows up on screen.
- The triangle filler works: a triangle with hard-coded screen coordinates draws.
- The page flip works: the CG-base register alternates between 0x00 and 0x1e.
- The build succeeds and the disc is rebuilt from source.

So each piece works in isolation, but the real renderer draws nothing.

Find the actual cause, fix it in the source, rebuild, and verify with a screenshot that
the cube is visible. Do not change the resolution, the geometry or the palette.
