---
name: finnish-passport-photo
description: Turn an ordinary phone photo into a Finnish police e-passport photo (passikuva) that meets the poliisi.fi specification. The output is exactly 500×653 px, a JPEG of at most 250 kB, with the head sized and centred to the pixel rules. A bundled script crops, levels, resizes and verifies the result, then Claude reviews the photo against the full police guide (hair over eyes, background, lighting, expression). Use this whenever someone wants a passport photo, ID card photo, residence permit photo or "passikuva" for Finland, wants to resize or crop a selfie or phone picture for poliisi.fi / the Finnish police photo service, or asks whether a photo meets the Finnish passport photo requirements. Use it even if they only say "make this a passport photo" and the country is implied to be Finland.
---

# Finnish passport photo

This skill turns a phone photo into an electronic passport photo that follows *Poliisin
passikuvaohje* (Finnish Police passport photo guide, 2020). There are two halves:

1. **Geometry**, which a script handles deterministically: size, file limits, head size,
   margins, centring and levelling. These rules are strict pixel ranges, and eyeballing them
   fails, so always use the script.
2. **Photo quality**, which you judge by looking: hair over the eyes, background, lighting,
   expression and so on. No script can fix these; the only fix is retaking the photo. Your
   job is to tell the person honestly whether the photo is likely to be accepted.

The full requirements are summarised in `references/requirements.md`. Read it when you need
to explain a rule or judge an unusual case (glasses, headwear, babies, medical exceptions).

## Requirements

- [`uv`](https://docs.astral.sh/uv/). The script declares its own dependencies (MediaPipe
  0.10.21, Pillow, NumPy) inline, so `uv run` installs them in an isolated environment. No
  manual `pip install` is needed.
- Internet access on the first run. The ~4 MB MediaPipe face-landmark model downloads to
  `~/.cache/finnish-passport-photo/`.
- A 64-bit Intel/AMD or Apple Silicon computer: macOS 11+, Windows 10/11 x64, or Linux
  x86_64 with glibc ≥ 2.28. **ARM Linux and ARM Windows are not supported**, because
  MediaPipe has no build for them. On Linux, the system libraries `libgl1` and
  `libglib2.0-0` are also needed. About 1 GB of disk space is used for packages. See the
  README for the full table and per-OS install steps. If the person's setup fails, the
  README's troubleshooting table covers the common errors.
- MediaPipe is pinned to 0.10.21 on purpose: version 1.0.x crashes on macOS while
  initialising Metal, even with the CPU delegate. Don't "upgrade" the pin.

## Workflow

### 1. Look at the source photo first

View the photo. Phone photos are large, so view a downscaled copy and keep helper files
like this in a scratch or temp directory, not next to the person's photos or in the output
folder. For example:

```bash
uv run -q --with pillow python3 -c "import sys; from PIL import Image, ImageOps; \
im = ImageOps.exif_transpose(Image.open(sys.argv[1])); im.thumbnail((1000, 1000)); \
im.convert('RGB').save(sys.argv[2])" <photo> <scratch>/preview.jpg
```

Check early for problems that make processing pointless: several people, the head cut off,
or a very busy background right behind the head. Mention these before spending effort on
the rest.

### 2. Run the script

```bash
uv run <skill-dir>/scripts/make_passport_photo.py <photo> [--out <result.jpg>]
```

By default it writes four files next to the input. `--out` sets the exact deliverable
path, and the check images are named after it. For example, `--out result/anna.jpg` writes
`result/anna.jpg`, `result/anna_check.png`, `result/anna_chin.png` and `result/anna_eyes.png`.
Without `--out`, the name is `<photo>_500x653`:

| File | What it is |
|---|---|
| `<name>_500x653.jpg` | The finished passport photo. This is the deliverable. |
| `<name>_500x653_check.png` | The whole photo at **2× scale** with an explanation panel on the right: green allowed zones, red measured crown/chin/midline, blue dashed hair top, and each measurement with OK/FAIL. Values in the panel are in output pixels. |
| `<name>_500x653_chin.png` | A **4× close-up of the chin** with a ruler labelled in *output* pixels, and the measured chin as a red line. |
| `<name>_500x653_eyes.png` | A **3× close-up of the eyes, eyebrows and fringe**, used to judge whether hair covers the eyes. |

The **last line of output is `RESULT: PASS` or `RESULT: FAIL`**; read that line rather
than relying on the exit code through a pipe. Native MediaPipe logging is silenced
(set `PASSPORT_DEBUG=1` to see it). `uv run -q` also hides uv's own install chatter.

What it does and why:
- **Applies the EXIF rotation and converts the colour profile to sRGB.** iPhones shoot in
  Display P3, and passing that through unconverted shifts the colours.
- **Levels the eye line** (rotation only). The guide requires a straight head, and rotating
  does not change appearance, so it is allowed.
- **Finds the chin (landmark 152), the eyes and the face midline**, then **estimates the
  crown** as `eye_y − 1.05 × (chin_y − eye_y)`. The crown is under the hair, and the guide
  explicitly allows estimating it. The factor 1.05 sits between adults (~1.0, eyes at the
  head's midpoint) and children (~1.1), so the result stays in tolerance either way.
- **Targets the middle of every allowed range**: head 472 px, 70 px above the crown, 111 px
  below the chin. This leaves margin for landmark error.
- **Repeats detection inside the crop box** until it is stable. Detection on the full phone
  photo can be off by ~8 output px at the chin; on a face-filling crop it is accurate.
- **Estimates the camera distance** from the EXIF 35 mm-equivalent focal length and the
  head size, and warns if it is under ~1 m. Phone main cameras (~26 mm) used at arm's length
  enlarge the nose and the centre of the face, which the guide rejects (its pic 9). Treat the
  number as a rough ±30 % estimate: it assumes an average head height of about 22 cm.
- **Saves the highest JPEG quality under 250 kB and strips all metadata.** Phone photos
  carry GPS coordinates, which don't belong in a document photo.
- **Re-opens the written file and measures it again**, printing an OK/FAIL line per rule.
  Exit code 0 means everything passed, 1 means a check failed, and 2 means the photo could
  not be processed; the error message explains why.

### 3. Verify with your own eyes, not just the numbers

Open both check images:

- **`_chin.png`**: confirm that the **red line sits on the lower edge of the chin**, where
  the jaw meets the neck. Always use this close-up rather than the overview to judge the
  chin. At overview scale, the chin shadow looks like the chin and a collar looks like a
  jawline; both mistakes are easy to make.
- **`_check.png`**: green bands show where the red lines are allowed to be. Confirm that:
  - the **red crown line is plausibly where the skull ends under the hair**. The blue dashed
    line marks the detected top of the hair. The script also prints how much hair lies
    between the two (`hair top y=…, ~X cm of hair above the estimated crown`) and warns
    outside 0.3–3 cm. Straight hair lying flat is usually ~0.5–1.5 cm thick.

**Explain the hair versus crown distinction to the person.** People naturally read "top of
the head" as the top of the hair, and they see the hair sticking out above the green band.
That is correct and expected: the guide measures from the crown of the skull and explicitly
excludes hair and beard. The blue dashed line exists to make this visible. Point at it rather
than letting the person think the photo is misaligned.

The crown check in the script is **not independent**, because it re-applies the same
estimate. Say so if the person asks how certain the result is. If an estimate is clearly
wrong, rerun with `--crown-y` / `--chin-y`, using coordinates in the levelled source as
printed in the script's `crown y=… chin y=…` line.

### 4. Review photo quality against the guide

Look at the final 500×653 output and go through the items the script cannot check:

- **Hair and the face**: the guide says hair must not cover the face and pays special
  attention to the eyes. Grade it like this:
  - Hair over an eye, or reaching the eyelids: **likely rejected**. Retake.
  - Fringe covering the eyebrows while the eyes are clearly free: **a real risk**, but not
    certain rejection. Recommend a retake with the fringe combed aside if that is easy.
  - Forehead and eyebrows visible: fine.

  Judge this from `_eyes.png`. At 500×653, light eyebrows and thin strands are hard to see.

  This is the most common problem with children's photos.
- **Background**: plain, light and neutral, with no shadows, objects or other people in the
  crop. A white wall is acceptable; light grey is ideal.
- **Lighting**: even across the face, with no hard shadows, blown-out forehead, or colour cast.
- **Expression**: neutral, mouth closed, eyes open and looking straight at the camera.
- **Pose**: face and shoulders square to the camera.
- **Glasses**: no reflections, and the frames are nowhere near the eyes.
- **Sharpness**: no blur. If the script warned about upscaling, the source was too low-resolution.
- **Distortion**: if the script warned about the distance, look at whether the nose looks
  large relative to the face. Mention it as a risk even when it looks acceptable, because a
  retake from further away is the easy fix.
- **Contrast**: the clothes and hair stand out from the background. The card engraving may be
  greyscale, so a white shirt against a white wall is a problem.

Never "fix" these by editing pixels (brightening the face, painting the background, removing
hair strands). The guide forbids any edit that changes appearance. The only honest fix is a
new photo.

### 5. Report

Open the result for the person if there's a desktop (`open <file>` on macOS,
`xdg-open` on Linux, `start` on Windows). Otherwise just give the path. Then give:

1. The output path.
2. A table of the script's measurements (rule | allowed | result).
3. Your quality review: what is fine, and any risk, with a concrete retake tip
   (e.g. "comb the fringe to the side", "stand ~1 m from the wall to avoid shadows",
   "shoot from ~1.5 m with 2× zoom").
4. Answer in the language the person wrote in. For Finnish speakers, "passikuva" is the
   usual word, and the check names in the table can be translated.
5. A reminder that the photo is valid for 6 months from when it was taken. The script
   prints the capture date (`taken:` line) from EXIF; if it's unknown, ask the person.

When comparing several candidate photos, run the script on each one and recommend the photo
with the fewest quality risks. The geometry usually passes for all of them, so quality is
the deciding factor.

## When the script fails

- **"crop box falls outside the photo"**: the head is too close to the image edge (usually
  the top). Ask for a retake with more space around the head. Don't pad with a fake
  background, because the guide requires a real, even background.
- **"no face found" / "more than one face"**: self-explanatory. Only the subject may be in
  the photo; a parent holding a small child must not be visible.
- **Upscaling warning**: the face was too small in the source. Retake closer, or with the 2× lens.
- **A FAIL on crown/chin/margins**: first check visually whether the landmarks are wrong
  (see step 3), then override manually. If they are right and the photo still fails, the
  subject's proportions are unusual, so report it rather than forcing it.

## Scope

This covers the **electronic** photo delivered through a photo service (500×653 px). Paper
photos use the millimetre values in `references/requirements.md` (36×47 mm, head 32–36 mm),
and this script does not produce print layouts. The Finnish police guide is written for
Finnish documents; other countries have different specifications, so don't reuse these
numbers for them.
