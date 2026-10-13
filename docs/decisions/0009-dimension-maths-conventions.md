# 0009 — Dimension maths: crop orientation, filter chain, upscaling, rounding, corner cases

- Status: accepted; item 4 (the fit box is not turned) superseded by [0020](0020-m2-wave-1-product-decisions.md)
- Date: 2026-10-13
- Steps: C-5, C-7, C-8, C-10, F-7

## Context

05 §C-5 defines the size modes, the pixel aspect modes, rotation, modulus rounding and crop
snapping. It does not say:

- in which orientation a crop is measured when the source has a display matrix (phone video);
- which filter chain the command builder (C-7) makes from a `Geometry`;
- what "upscale" means for an anamorphic source made square;
- how to round when several sizes are possible.

The C-5 "Done when" properties cannot all hold for degenerate inputs. One example is a fit box
smaller than one modulus step. Another is a 64×1 picture with modulus 16.

FFmpeg n9.0.2 behaviour that the maths must match. `tests/dimensions/test_ffmpeg.py` records
each item:

1. `crop` silently rounds x, y, width and height **down** to the chroma grid of its input. It
   does this for every one of the 200 pixel formats that swscale can write in this build (one
   FFmpeg run in the test). It also does this for `crop=iw:ih` on an odd-sized frame:

   ```console
   $ ffmpeg -f lavfi -i color=size=853x481 -vf format=yuv420p,crop=iw:ih -f null - -v verbose
   [Parsed_crop_1] w:853 h:481 sar:1/1 -> w:852 h:480 sar:1/1
   $ ffmpeg -i letterbox.mkv -vf crop=319:135:1:23 …     # → 318x134 from x=0, y=22
   ```

   `crop=…:exact=1` keeps odd values (301x201), but one 4:2:0 chroma sample covers 2x2
   pixels, so the colour cannot follow an odd edge. Reframe does not use it.
2. `scale` changes the SAR so that the display aspect stays the same:
   `720x480 sar:32/27 -> 854x480 sar:1280/1281`. A `setsar` must follow every `scale`.
3. With the default automatic rotation, FFmpeg puts a `transpose` before the user's filters
   (`[transpose] w:720 h:480 dir:2 -> w:480 h:720`). This inverts the SAR (32:27 → 27:32),
   and the output has no display matrix. `-noautorotate` copies the display matrix into the
   output, so a builder that rotates the picture itself turns it twice in the player. For
   4:2:2 the automatic `transpose` converts the frames to 4:4:4 first (`yuv422p → yuv444p`).
4. Matroska keeps the exact SAR (32:27, 27:32, 7:5) for FFV1 and libx264.
5. libx264 needs an even height for 4:2:0 and a height divisible by 4 for interlaced 4:2:0:
   `[libx264] height not divisible by 4 (320x242)` with `-flags +ildct+ilme`.

## Decision

1. **Crop orientation.** A `CropRect` (in `CropSettings.rect` and in `Geometry.crop`) is
   measured on the source picture as FFmpeg decodes it: the display matrix is applied by the
   automatic rotation, and the job's rotate and flip are not applied yet. This is what
   `cropdetect` and the preview frames see with FFmpeg's defaults, so C-10 and F-7 need no
   special flags. For a file without a display matrix it is the stored frame. The chroma grid
   is the stored format's grid. For a 90° or 270° source the steps change places, which is
   safe because the automatic transpose keeps 4:2:0 and makes 4:2:2 into 4:4:4.
   `reframe.dimensions.rotate_crop` maps a crop between orientations.
2. **Filter chain for C-7.** Keep the automatic rotation on, then:
   `crop=cropped_width:cropped_height:left:top` (only if a crop is applied) → transpose for
   `Geometry.filter_rotation` (90 = `transpose=clock`, 180 = `hflip,vflip`,
   270 = `transpose=cclock`) → `hflip` if `Geometry.flip_horizontal` →
   `scale=scaled_width:scaled_height` → `setsar=output_sar`. The flip mirrors the picture
   after the rotation. `Geometry` gets two new fields with defaults for this: `filter_rotation`
   and `flip_horizontal`. `rotation` stays the total (source + job).
3. **Crop snapping.** Every edge snaps down to the grid, so less is cropped
   ("Crop left 141 → 140 for 4:2:0"). On a frame whose size is off the grid, the right or
   bottom edge grows by the remainder when a crop is applied, so that FFmpeg crops exactly
   that. Interlaced sources double the vertical step for every subsampling: 4 for 4:2:0, 2
   for 4:2:2 and 4:4:4. A crop that removes a whole axis, or leaves less than one step, is
   not applied on that axis. An unknown pixel format is taken as 4:2:0
   (`SourceGeometry.chroma_assumed`, a new field with a default).
4. **Output size and upscaling.** The size modes apply to the stored output frame in the
   output orientation (after the rotation). The fit box is not turned for portrait pictures.
   The *natural size* is the display size of the cropped picture: the stretched axis of an
   anamorphic picture is expanded, so DVD 16:9 is 853.3 × 480. It is then stored with the
   output pixel aspect. Output that is one pixel or more larger than the natural size on an
   axis is an upscale. So DVD 16:9 → 854 × 480 square pixels is not an upscale, and DVD 4:3
   (SAR 8:9) → 720 × 540 is not one either. An exact width or height above the natural size
   with upscaling off keeps the natural size, with a note.
5. **Modulus rounding.** Width and height are multiples of the modulus and of the source's
   chroma step on that axis (the lcm). This gives height 4 for interlaced 4:2:0 (what x264
   needs, item 5 above) and width 4 for 4:1:1. Sizes are tried by their distance to
   the target on the long axis, with the two nearest short-axis values for each. The first
   size whose display aspect error is < 0.5 %, or < 1 px from an exact-aspect size, wins.
   When no size meets that, the smallest error wins. This can give a smaller picture than
   plain rounding: 1080p at modulus 16 gives 1904 × 1072 (0.09 %), not 1920 × 1072 (0.75 %).
6. **Corner cases.** A fit box or a natural size smaller than one modulus step gives exactly
   one step on that axis. That is outside the box, or `upscaled = True`. When nothing inside
   the limits meets the aspect tolerance, the closest size is used. Each case adds a note.
   Automatic and conservative crop without a detected `rect` apply no crop and add a note.
   C-8 turns these notes into issues.

## Consequences

- C-7 keeps FFmpeg's automatic rotation and needs no extra input flags. If a hardware
  pipeline ever needs `-noautorotate`, it must remove the display matrix from the output
  (`-display_rotation:v:0 0` on the input) and map the crop with `rotate_crop`.
- C-8 can find the cases from the settings and the `Geometry`. Examples: an invalid crop
  (the crop differs from the requested rect on an axis), crop detection not run yet,
  `upscaled`, output outside the fit box.
- At modulus 8 or 16 the output can be a few steps smaller than the box. Modulus 2 (the
  default) almost never moves more than one step.
- Revisit: should "Fit within 1080p" turn the box for portrait sources (1080 × 1920)? Should
  an upper size limit come from the encoder (C-6 / C-8)? `compute_geometry` does what it is
  asked, even 8192 × 67108864.

## Plan changes

- `docs/plan/05-core.md` §C-5: `source_geometry` in the interface, a conventions bullet, and
  the corner cases in "Done when".
- `docs/plan/03-features.md` §Dimensions: the flip mirrors after the rotation (Orientation);
  upscaling is measured against the display size (Output size).
