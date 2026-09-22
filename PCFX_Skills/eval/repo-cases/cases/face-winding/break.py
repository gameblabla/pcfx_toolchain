#!/usr/bin/env python3
"""Break: three faces of the cube get the opposite winding.

The backface test is the sign of the projected triangle area, so a reversed
winding culls a face exactly when it IS facing the camera. Symptom: faces
missing/flickering as the cube turns, which looks like a rasterizer or
depth-sort bug and is neither.

The fix must be verified against the geometric oracle (`make hosttest`), not by
staring at a screenshot: hand-deriving windings on paper is what produced the
wrong table in the first place.

Taught by: pcfx-3d-pipeline S4.2-S4.3, pcfx-3d-from-scratch S6 gate 1.
"""
import sys, pathlib

GOOD = """static const int cube_faces[6][4] = {
    { 4, 7, 6, 5 },   /* +z (front)   */
    { 0, 1, 2, 3 },   /* -z (back)    */
    { 0, 3, 7, 4 },   /* -x (left)    */
    { 1, 5, 6, 2 },   /* +x (right)   */
    { 3, 2, 6, 7 },   /* +y (top)     */
    { 0, 4, 5, 1 },   /* -y (bottom)  */
};"""

BAD = """static const int cube_faces[6][4] = {
    { 5, 6, 7, 4 },   /* +z (front)   */
    { 0, 1, 2, 3 },   /* -z (back)    */
    { 0, 3, 7, 4 },   /* -x (left)    */
    { 2, 6, 5, 1 },   /* +x (right)   */
    { 7, 6, 2, 3 },   /* +y (top)     */
    { 0, 4, 5, 1 },   /* -y (bottom)  */
};"""

p = pathlib.Path(sys.argv[1]) / "src" / "cube3d.c"
s = p.read_text()
assert GOOD in s, "template does not contain the expected face table"
p.write_text(s.replace(GOOD, BAD))
print(f"broke {p}")
