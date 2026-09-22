This PC-FX project (`cube3d`) draws a spinning grey cube. It builds, boots and clearly
renders — but the cube looks wrong: some sides of it are missing, and which ones are
missing changes as it rotates. From some angles you can see straight "through" the cube.

Things I already ruled out: the triangle filler draws correctly when given hard-coded
screen coordinates, the page flip alternates properly, and the projection puts every
vertex on screen.

Find the cause and fix it. Then prove the fix is right rather than assuming it: the
project has a host-side check you can build and run, and it must report PASS. Do not
weaken or delete that check, and do not disable backface culling.
