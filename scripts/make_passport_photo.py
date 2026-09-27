# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["mediapipe==0.10.21", "pillow>=10.1", "numpy"]
# ///
"""Crop a phone photo into a Finnish police e-passport photo.

Requirements (Poliisin passikuvaohje 2020, pages 1 and 3), electronic delivery:
  * exactly 500 x 653 px, JPEG, max 250 kB
  * crown-to-chin (hair excluded) 445-500 px
  * 56-84 px above the crown, 96-124 px below the chin
  * face midline within 21 px of the image midline

Pipeline: EXIF orientation -> colour profile to sRGB -> MediaPipe FaceLandmarker
-> level the eye line -> estimate crown/chin/midline -> re-detect inside the
crop until stable -> Lanczos resize -> JPEG under 250 kB (metadata stripped)
-> re-measure the written file and draw a check image.

The crown is hidden under hair, so it is *estimated* (the guide allows this):
crown = eye_y - CROWN_FACTOR * (chin_y - eye_y). Override with --crown-y /
--chin-y (pixel coordinates in the levelled source, as printed) if the check
image shows a bad estimate.

Usage:
  uv run make_passport_photo.py photo.jpg [--out result.jpg]
Writes <out>.jpg, <out>_check.png (2x, tolerance bands), <out>_chin.png
(4x chin close-up with a ruler in output pixels) and <out>_eyes.png (3x eye and
eyebrow close-up for judging hair over the eyes). The last line printed is
"RESULT: PASS" or "RESULT: FAIL"; exit code 0 = pass, 1 = a check failed,
2 = could not process.
"""

from __future__ import annotations

import argparse
import io
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# MediaPipe's C++ code logs straight to file descriptor 2 and ignores the usual
# env switches. Point fd 2 at /dev/null but keep Python's sys.stderr on a copy of
# the real stream, so our errors and tracebacks still show. PASSPORT_DEBUG=1 keeps
# the native logs.
if not os.environ.get("PASSPORT_DEBUG"):
    sys.stderr.flush()
    sys.stderr = os.fdopen(os.dup(2), "w", buffering=1)
    _devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(_devnull, 2)

import mediapipe as mp
import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps

OUT_W, OUT_H = 500, 653
HEAD_MIN, HEAD_MAX = 445, 500
TOP_MIN, TOP_MAX = 56, 84
BOTTOM_MIN, BOTTOM_MAX = 96, 124
CENTER_TOL = 21
MAX_BYTES = 250 * 1000  # "250 kilotavua" — use the stricter decimal kB

# Middle of every allowed range: head 472, top 70 -> bottom 111 (all in range).
TARGET_HEAD = 472
TARGET_TOP = 70

# Crown distance above the eyes, relative to eyes->chin. Adults ~1.0 (eyes at the
# head's midpoint); children's eyes sit lower, ~1.1. 1.05 keeps the result inside
# every tolerance whichever end is true (head 461-483 px, top margin 59-81 px).
CROWN_FACTOR = 1.05

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)

# MediaPipe face mesh landmark indices
CHIN = 152
FOREHEAD = 10
NOSE_BRIDGE = 168
CHEEK_R, CHEEK_L = 234, 454
EYE_R = (33, 133)
EYE_L = (362, 263)


def fail(msg: str) -> None:
    sys.stdout.flush()
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def model_path() -> Path:
    bundled = Path(__file__).parent / "models" / "face_landmarker.task"
    if bundled.exists():
        return bundled
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cached = cache / "finnish-passport-photo" / "face_landmarker.task"
    if not cached.exists():
        print(f"downloading face landmark model -> {cached}")
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".part")
        urllib.request.urlretrieve(MODEL_URL, tmp)
        tmp.rename(cached)
    return cached


@dataclass
class Face:
    eye_r: tuple[float, float]
    eye_l: tuple[float, float]
    chin_y: float
    forehead_y: float
    mid_x: float

    @property
    def eye_y(self) -> float:
        return (self.eye_r[1] + self.eye_l[1]) / 2

    @property
    def roll_deg(self) -> float:
        dx = self.eye_l[0] - self.eye_r[0]
        dy = self.eye_l[1] - self.eye_r[1]
        return math.degrees(math.atan2(dy, dx))

    def crown_y(self, factor: float = CROWN_FACTOR) -> float:
        return self.eye_y - factor * (self.chin_y - self.eye_y)


def focal_35mm(path: Path) -> float | None:
    """35 mm-equivalent focal length from EXIF, if the camera recorded it."""
    try:
        f = Image.open(path).getexif().get_ifd(0x8769).get(0xA405)
        return float(f) if f else None
    except Exception:
        return None


def capture_date(path: Path) -> None:
    """The guide accepts photos at most 6 months old."""
    try:
        exif = Image.open(path).getexif()
        raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
    except Exception:
        raw = None
    if raw:
        print(f"taken: {str(raw)[:10].replace(':', '-')}  (valid for 6 months from this date)")
    else:
        print("taken: unknown (no EXIF date) — ask when the photo was taken; max age is 6 months")


def distance_hint(path: Path, head_px: float, img_h: int, img_w: int) -> None:
    """Rough camera distance: a 35 mm frame is 36 mm on its long side and a
    crown-to-chin head is ~0.21-0.23 m. Close wide-angle shots enlarge the nose
    (guide pic 9); portrait photographers shoot from ~1.5 m or more."""
    f = focal_35mm(path)
    if not f:
        return
    dist = f * 0.22 / (head_px / max(img_h, img_w) * 36)
    print(f"camera distance ~{dist:.1f} m (EXIF {f:.0f} mm equiv.)")
    if dist < 1.0:
        print("WARNING: shot from closer than ~1 m with a phone lens — central facial features "
              "may look enlarged (optical distortion); a retake from ~1.5 m with 2x zoom is safer")


def load_srgb(path: Path) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(path))
    icc = img.info.get("icc_profile")
    if icc:  # phones shoot Display P3; convert so colours stay natural in sRGB
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst = ImageCms.createProfile("sRGB")
        img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
    return img.convert("RGB")


def detect(img: Image.Image, detector, region: tuple[float, ...] | None = None) -> Face:
    """Landmarks in `img` pixel coordinates. With `region`, detect inside that
    crop only: the landmark model is more accurate when the face fills the
    frame the way it will in the final photo."""
    ox, oy = 0.0, 0.0
    if region is not None:
        ox, oy = region[0], region[1]
        img = img.crop(tuple(round(v) for v in region))
    # Detect on a downscaled copy for speed; landmarks are normalized anyway.
    small = img.copy()
    small.thumbnail((1600, 1600))
    result = detector.detect(
        mp.Image(image_format=mp.ImageFormat.SRGB, data=np.asarray(small))
    )
    if not result.face_landmarks:
        fail("no face found")
    if len(result.face_landmarks) > 1:
        fail("more than one face found — the guide forbids other people in the photo")
    lm = result.face_landmarks[0]
    w, h = img.size

    def pt(i: int) -> tuple[float, float]:
        return ox + lm[i].x * w, oy + lm[i].y * h

    def mid(a: int, b: int) -> tuple[float, float]:
        (ax, ay), (bx, by) = pt(a), pt(b)
        return (ax + bx) / 2, (ay + by) / 2

    cheek_mid_x = (pt(CHEEK_R)[0] + pt(CHEEK_L)[0]) / 2
    return Face(
        eye_r=mid(*EYE_R),
        eye_l=mid(*EYE_L),
        chin_y=pt(CHIN)[1],
        forehead_y=pt(FOREHEAD)[1],
        mid_x=(cheek_mid_x + pt(NOSE_BRIDGE)[0] + pt(CHIN)[0]) / 3,
    )


def encode_jpeg(img: Image.Image) -> tuple[bytes, int]:
    # Highest quality that fits: heavy compression causes artefacts the guide rejects.
    for q in range(95, 59, -5):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, subsampling=0, optimize=True)
        if buf.tell() <= MAX_BYTES:
            return buf.getvalue(), q
    fail("could not get the JPEG under 250 kB without heavy compression")


HEAD_CM = 22.0  # typical crown-to-chin head height, child ~21 cm, adult ~23 cm


def hair_top(out: Image.Image, mid_x: float) -> int | None:
    """First row (output px) where hair starts, scanning down a band around the
    face midline and comparing against the background colour in the top corners.
    None if hair touches the top edge or nothing stands out from the background."""
    a = np.asarray(out.convert("RGB")).astype(int)
    bg = np.median(np.concatenate([a[:15, :15].reshape(-1, 3), a[:15, -15:].reshape(-1, 3)]), axis=0)
    x0, x1 = max(0, int(mid_x) - 60), min(OUT_W, int(mid_x) + 60)
    for y in range(OUT_H // 2):
        diff = np.abs(a[y, x0:x1] - bg).max(axis=1)
        if (diff > 35).mean() >= 0.25:  # a quarter of the band: ignores stray flyaways
            return None if y == 0 else y
    return None


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType
        return ImageFont.load_default()


def check_image(out: Image.Image, crown: float, chin: float, mid_x: float,
                hair: int | None) -> Image.Image:
    """Annotated 2x copy in the style of the police diagram: allowed bands in green,
    measured crown/chin/midline in red, detected hair top in blue, and a side
    panel that explains each line and gives its measured value."""
    s, panel = 2, 620
    W, H = OUT_W * s, OUT_H * s
    img = Image.new("RGB", (W + panel, H), "white")
    img.paste(out.resize((W, H), Image.LANCZOS), (0, 0))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    green, green_txt = (0, 170, 0, 70), (0, 120, 0, 255)
    red, blue, grey = (230, 0, 0, 255), (0, 90, 230, 255), (60, 60, 60, 255)
    f_big, f, f_small = font(26), font(21), font(17)

    # Allowed zones (bands span photo and panel so the labels line up).
    d.rectangle([0, TOP_MIN * s, W + panel, TOP_MAX * s], fill=green)
    d.rectangle([0, (OUT_H - BOTTOM_MAX) * s, W + panel, (OUT_H - BOTTOM_MIN) * s], fill=green)
    cx = OUT_W / 2
    d.rectangle([(cx - CENTER_TOL) * s, 0, (cx + CENTER_TOL) * s, H], fill=(0, 170, 0, 35))

    # Hair top: dashed blue, hair is not part of the head measurement.
    if hair is not None:
        for x in range(0, W, 24):
            d.line([x, hair * s, x + 12, hair * s], fill=blue, width=3)
        d.line([W, hair * s, W + 20, hair * s], fill=blue, width=3)
    # Measured lines.
    for y in (crown, chin):
        d.line([0, y * s, W + 20, y * s], fill=red, width=3)
    d.line([mid_x * s, crown * s, mid_x * s, chin * s], fill=red, width=3)
    # Head-height bracket in the panel.
    bx = W + 40
    d.line([bx, crown * s, bx, chin * s], fill=red, width=3)
    for y in (crown, chin):
        d.line([bx - 10, y * s, bx + 10, y * s], fill=red, width=3)

    head = chin - crown
    below = OUT_H - chin
    ok = lambda c: "OK" if c else "FAIL"
    tx = W + 62

    def label(y: float, lines: list[tuple[str, tuple, ImageFont.ImageFont]]) -> None:
        yy = y
        for text, col, fnt in lines:
            d.text((tx, yy), text, fill=col, font=fnt)
            yy += fnt.size + 6 if hasattr(fnt, "size") else 20

    label(6, [("Passport photo check (2x)", grey, f_big)])
    if hair is not None:
        hair_cm = (crown - hair) / (head / HEAD_CM)
        label(max(hair * s - 58, 44), [
            (f"hair top  y={hair}", blue, f),
            (f"hair above crown ~{hair_cm:.1f} cm (not counted)", blue, f_small),
        ])
    label(TOP_MAX * s + 6, [
        (f"CROWN (top of skull, estimated)  y={crown:.0f}", red, f),
        (f"must be in green band 56-84: {ok(TOP_MIN <= crown <= TOP_MAX)}", green_txt, f_small),
    ])
    label((crown + chin) / 2 * s - 40, [
        (f"head crown->chin {head:.0f} px", red, f),
        (f"allowed 445-500: {ok(HEAD_MIN <= head <= HEAD_MAX)}", green_txt, f_small),
        (f"midline offset {mid_x - cx:+.1f} px (max 21): {ok(abs(mid_x - cx) <= CENTER_TOL)}",
         green_txt, f_small),
    ])
    label((OUT_H - BOTTOM_MAX) * s - 64, [
        (f"CHIN tip  y={chin:.0f}", red, f),
        (f"space below {below:.0f} px, allowed 96-124: {ok(BOTTOM_MIN <= below <= BOTTOM_MAX)}",
         green_txt, f_small),
    ])
    label(H - 150, [
        ("green = allowed zone for the red line", green_txt, f_small),
        ("red = measured crown / chin / face midline", red, f_small),
        ("blue dashed = top of hair (hair and beard", blue, f_small),
        ("  are excluded by the police guide)", blue, f_small),
    ])
    base = img.convert("RGBA")
    return Image.alpha_composite(base, layer).convert("RGB")


def eyes_zoom(out: Image.Image, eye_y: float) -> Image.Image:
    """3x close-up of eyes, eyebrows and fringe: is any hair over the eyes?"""
    s = 3
    y0, y1 = max(0, int(eye_y) - 80), min(OUT_H, int(eye_y) + 35)
    return out.crop((60, y0, 440, y1)).resize((380 * s, (y1 - y0) * s), Image.LANCZOS)


def chin_zoom(out: Image.Image, chin: float) -> Image.Image:
    """4x close-up around the measured chin, ruler labelled in OUTPUT pixels, so
    you can check the red line against the real jaw/neck edge."""
    s = 4
    y0, y1 = max(0, int(chin) - 90), min(OUT_H, int(chin) + 60)
    x0, x1 = 130, 370
    img = out.crop((x0, y0, x1, y1)).resize(((x1 - x0) * s, (y1 - y0) * s), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    for y in range((y0 // 10 + 1) * 10, y1, 10):
        col = (255, 0, 0) if y % 50 == 0 else (0, 110, 255)
        d.line([0, (y - y0) * s, 40, (y - y0) * s], fill=col, width=2)
        d.text((44, (y - y0) * s - 6), str(y), fill=col)
    d.line([0, (chin - y0) * s, img.width, (chin - y0) * s], fill=(255, 0, 0), width=3)
    return img


def to_out(y: float, top: float, scale: float) -> float:
    return (y - top) * scale


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", type=Path)
    ap.add_argument("--out", type=Path, help="output JPEG (default: <photo>_500x653.jpg next to the input)")
    ap.add_argument("--crown-y", type=float, help="manual crown y in the levelled source")
    ap.add_argument("--chin-y", type=float, help="manual chin y in the levelled source")
    ap.add_argument("--crown-factor", type=float, default=CROWN_FACTOR)
    args = ap.parse_args()
    if not args.photo.exists():
        fail(f"{args.photo} does not exist")

    opts = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path()), delegate=mp.tasks.BaseOptions.Delegate.CPU
        ),
        num_faces=2,
    )
    detector = mp.tasks.vision.FaceLandmarker.create_from_options(opts)

    img = load_srgb(args.photo)
    print(f"source: {img.size[0]}x{img.size[1]}")
    capture_date(args.photo)

    face = detect(img, detector)
    if abs(face.roll_deg) > 0.3:
        print(f"levelling head roll {face.roll_deg:+.2f}°")
        eye_c = ((face.eye_r[0] + face.eye_l[0]) / 2, face.eye_y)
        img = img.rotate(face.roll_deg, resample=Image.BICUBIC, center=eye_c, fillcolor="white")
        face = detect(img, detector)

    # Pass 1 on the whole photo, then re-detect inside the resulting crop box
    # until the box stops moving.
    for _ in range(3):
        chin = args.chin_y if args.chin_y is not None else face.chin_y
        crown = args.crown_y if args.crown_y is not None else face.crown_y(args.crown_factor)
        head = chin - crown
        print(f"eyes y={face.eye_y:.0f}  forehead(lm10) y={face.forehead_y:.0f}  "
              f"crown y={crown:.0f}  chin y={chin:.0f}  head={head:.0f}px  mid x={face.mid_x:.0f}")
        scale = TARGET_HEAD / head
        left = face.mid_x - (OUT_W / 2) / scale
        top = crown - TARGET_TOP / scale
        box = (left, top, left + OUT_W / scale, top + OUT_H / scale)
        face = detect(img, detector, region=box)

    w, h = img.size
    if box[0] < 0 or box[1] < 0 or box[2] > w or box[3] > h:
        fail(f"crop box {tuple(round(v) for v in box)} falls outside the {w}x{h} photo — "
             "the person is too close to the frame edge; retake with more space around the head")
    print(f"crop box (source px): {tuple(round(v) for v in box)}  scale={scale:.4f}")
    distance_hint(args.photo, head, h, w)
    if scale > 1:
        print("WARNING: the head is smaller than 472 px in the source, so the photo is "
              "being upscaled and may look blurry; retake closer or zoomed in")

    out = img.resize((OUT_W, OUT_H), Image.LANCZOS, box=box)
    data, quality = encode_jpeg(out)
    out_path = args.out or args.photo.with_name(f"{args.photo.stem}_500x653.jpg")
    out_path.write_bytes(data)

    # --- verify the file actually written, independently of the crop math ---
    final = Image.open(out_path)
    final.load()
    measured = detect(final.convert("RGB"), detector)
    m_chin = measured.chin_y if args.chin_y is None else to_out(chin, top, scale)
    m_crown = measured.crown_y(args.crown_factor) if args.crown_y is None else to_out(crown, top, scale)
    m_head = m_chin - m_crown
    checks = [
        ("size exactly 500x653", final.size == (OUT_W, OUT_H), f"{final.size[0]}x{final.size[1]}"),
        ("format JPEG", final.format == "JPEG", final.format),
        ("file <= 250 kB", len(data) <= MAX_BYTES, f"{len(data) / 1000:.1f} kB (q={quality})"),
        ("no EXIF/GPS", "exif" not in final.info, "stripped" if "exif" not in final.info else "present"),
        ("crown->chin 445-500", HEAD_MIN <= m_head <= HEAD_MAX, f"{m_head:.0f}px"),
        ("above crown 56-84", TOP_MIN <= m_crown <= TOP_MAX, f"{m_crown:.0f}px"),
        ("below chin 96-124", BOTTOM_MIN <= OUT_H - m_chin <= BOTTOM_MAX, f"{OUT_H - m_chin:.0f}px"),
        ("midline offset <= 21", abs(measured.mid_x - OUT_W / 2) <= CENTER_TOL,
         f"{measured.mid_x - OUT_W / 2:+.1f}px"),
        ("head level", abs(measured.roll_deg) <= 2, f"{measured.roll_deg:+.2f}°"),
    ]
    print(f"\nwrote {out_path}")
    for name, ok, val in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name:<22} {val}")

    # Sanity check of the crown estimate against the visible hair: the skull top
    # must lie below the hair top, by roughly 0.3-3 cm of hair.
    hair = hair_top(final, measured.mid_x)
    if hair is None:
        print("  note: hair top not found (hair touches the top edge or blends into the background)")
    else:
        hair_cm = (m_crown - hair) / (m_head / HEAD_CM)
        plausible = 0.3 <= hair_cm <= 3.0
        print(f"  {'note' if plausible else 'WARN'} hair top y={hair}, ~{hair_cm:.1f} cm of hair above the "
              f"estimated crown ({'plausible' if plausible else 'implausible — check the crown line, maybe use --crown-y'})")

    check_path = out_path.with_name(f"{out_path.stem}_check.png")
    check_image(final.convert("RGB"), m_crown, m_chin, measured.mid_x, hair).save(check_path)
    chin_path = out_path.with_name(f"{out_path.stem}_chin.png")
    chin_zoom(final.convert("RGB"), m_chin).save(chin_path)
    eyes_path = out_path.with_name(f"{out_path.stem}_eyes.png")
    eyes_zoom(final.convert("RGB"), measured.eye_y).save(eyes_path)
    print(f"check image: {check_path}  (2x, annotated: green = allowed zones, red = crown/chin, blue = hair top)")
    print(f"chin close-up: {chin_path}  (4x; ruler in output px, red = measured chin y={m_chin:.0f})")
    print(f"eyes close-up: {eyes_path}  (3x; check that no hair covers the eyes)")
    passed = all(ok for _, ok, _ in checks)
    print(f"RESULT: {'PASS' if passed else 'FAIL'}")
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
