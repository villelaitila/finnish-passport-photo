# finnish-passport-photo

A [Claude Code](https://claude.com/claude-code) skill (and standalone script) that turns an
ordinary phone photo into an electronic **Finnish police passport photo** (*passikuva*),
following the Finnish Police passport photo guide (*Poliisin passikuvaohje*, 2020).

- Exactly **500 × 653 px** JPEG of **≤ 250 kB**, with all metadata removed (including GPS).
- Head sized and positioned to the pixel rules: crown to chin 445–500 px, 56–84 px above
  the crown, 96–124 px below the chin, face midline within 21 px of the centre.
- The eye line is levelled and Display P3 is converted to sRGB. Nothing else is changed: the
  guide forbids edits that alter appearance.
- The written file is measured again, and three check images are produced:
  - an annotated overview (allowed zones, measured crown/chin, detected hair top)
  - a chin close-up with a pixel ruler
  - an eye-area close-up for judging whether hair covers the eyes
- Warns when the photo was shot too close (phone wide-angle distortion) and prints the
  capture date. The photo may be at most 6 months old.

As a skill, Claude runs the script, checks the check images, and reviews the photo against
the rest of the guide: hair over the eyes, background, lighting, expression and glasses.

## Install as a Claude Code skill

```bash
git clone https://github.com/villelaitila/finnish-passport-photo ~/.claude/skills/finnish-passport-photo
```

Then ask Claude something like *"make a Finnish passport photo from ~/Downloads/IMG_1234.jpg"*
or *"tee tästä passikuva poliisille: kuva.jpg"*.

## Use the script directly

Requires [uv](https://docs.astral.sh/uv/). Dependencies (MediaPipe, Pillow, NumPy) are
declared inline and installed automatically. The face-landmark model (~4 MB) downloads to
`~/.cache/finnish-passport-photo/` on the first run.

```bash
uv run scripts/make_passport_photo.py photo.jpg [--out result.jpg]
```

The script writes `<name>_500x653.jpg` plus `_check.png`, `_chin.png` and `_eyes.png`. The
last output line is `RESULT: PASS` or `RESULT: FAIL`. Run with `--help` to see the manual
overrides (`--crown-y`, `--chin-y`, `--crown-factor`).

### About the crown

The guide measures head size **from the crown of the skull to the chin. Hair is not
counted**, so the crown has to be estimated. The script places it at
`eye_y − 1.05 × (chin_y − eye_y)`, which works for both adults and children. It also checks
that the estimate is plausible against the detected top of the hair. In the check image, the
hair (blue dashed line) often reaches above the green crown zone. That is expected.

## Tips for taking the photo

- Stand about 1.5 m away and use the 2× lens, with the camera at eye height. Shots from arm's
  length enlarge the nose.
- Use a plain, light background, ideally light grey, with the subject about 1 m in front of
  it so there are no shadows.
- Use even, soft light, such as a window in front of the subject. Avoid direct sun and flash.
- Keep hair off the face and away from the eyes. Take glasses off if they reflect.
- Neutral expression, mouth closed, looking straight into the camera.

## Disclaimer

This is an unofficial helper and is not affiliated with the Finnish Police. It checks the
measurable rules, but the police make the final decision on acceptance.

According to the guide, electronic photos normally reach the police through a photo
service: the studio uploads the photo and gives you a photo ID code (*kuvatunnus*) for the
application. Check [poliisi.fi](https://poliisi.fi/) for the current ways to submit a photo
you took yourself.

## License

MIT, see [LICENSE](LICENSE).
