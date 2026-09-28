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

## Requirements

### Computer

Any ordinary laptop or desktop from roughly the last ten years will do. No GPU is needed:
everything runs on the CPU and one photo takes a few seconds.

| Operating system | Status |
|---|---|
| macOS 11+ on Apple Silicon (M1–M4) | ✅ tested (macOS 26, M4 Pro) |
| macOS 11+ on Intel | should work (official MediaPipe build exists), not tested |
| Linux x86_64 with glibc ≥ 2.28 (Ubuntu 20.04+, Debian 10+, Fedora 29+) | ✅ tested (Debian 12, clean install), needs two system libraries, see below |
| Windows 10/11 on x64 (Intel/AMD) | should work (official MediaPipe build exists), not tested |
| Linux on ARM: Raspberry Pi, ARM servers, Docker `linux/arm64` on a Mac | ❌ no MediaPipe build, fails at install |
| Windows on ARM (Snapdragon / Surface Pro X laptops) | ❌ no MediaPipe build |
| Alpine Linux (musl), ChromeOS on ARM | ❌ |
| Phone, tablet, claude.ai in a browser | ❌ needs a real computer with a terminal |

| Resource | Needed |
|---|---|
| Disk | ~1 GB: ~690 MB of Python packages (MediaPipe pulls in OpenCV, JAX, SciPy and matplotlib) + ~60 MB Python 3.12 + 4 MB face model |
| Memory | ~400 MB free while running |
| Network | Only for the first run (downloads packages and the model, a few hundred MB). After that it works offline |
| Python | Nothing to install: uv downloads its own Python 3.12 if needed. System Python is not used |

### Software

| What | Why | Needed for |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Runs the script and installs its dependencies in an isolated environment | always |
| [git](https://git-scm.com/) | Downloads this repository (or download the ZIP from GitHub instead) | installation |
| [Claude Code](https://claude.com/claude-code) + a Claude subscription or API account | Runs the skill: Claude checks the check images and reviews photo quality | only for the skill; the script works on its own |
| Linux only: `libgl1` and `libglib2.0-0` | Native libraries MediaPipe/OpenCV load. Desktop Linux usually has them; servers and containers don't | Linux |

### Privacy

The script runs entirely on your computer and does not upload the photo anywhere. **When you
use it as a Claude skill, Claude looks at the photo and the check images**, so they are sent
to Anthropic as part of the conversation, like any image you share with Claude. If you don't
want to send the photo to Anthropic or any similar LLM provider, you have two options:

- **Use a local LLM.** Run a vision-capable model on your own computer, for example with
  Ollama or LM Studio, in an agent tool that can read `SKILL.md` and run shell commands. The
  photo then never leaves your machine. The script does not need an LLM at all; the model
  only follows the workflow and does the visual review. Smaller local models see less
  reliably, so look at the check images yourself too, especially for hair over the eyes.
- **Run the script directly** and look at the check images yourself.

### Token usage

The script on its own uses no tokens: it runs locally and never calls Claude.

As a Claude skill, one photo typically takes **about 85,000–135,000 input tokens and
2,000–3,000 output tokens**. Most of the input is Claude Code's own context (system prompt,
tool definitions and this skill's instructions), resent on each step and mostly read from
the prompt cache. The photos themselves are a small part, about 500–2,000 tokens each. The
upper end was measured in a session with a large personal `CLAUDE.md`; a clean setup lands
nearer the lower end. Processing several photos or asking follow-up questions adds to this.

## Installation

### 1. Install uv and git

**macOS** (in Terminal):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
xcode-select --install          # provides git; skip if `git --version` already works
```

**Windows** (in PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install --id Git.Git -e
```

**Linux** (Debian/Ubuntu; use your distribution's package manager elsewhere):

```bash
sudo apt install curl git libgl1 libglib2.0-0
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new terminal window afterwards so `uv` is on the PATH, then check it with `uv --version`.

### 2a. As a Claude Code skill

Install Claude Code if you don't have it yet
([instructions](https://code.claude.com/docs/en/setup)), then put this repository
in Claude's skill folder:

```bash
# macOS / Linux
git clone https://github.com/villelaitila/finnish-passport-photo ~/.claude/skills/finnish-passport-photo
```

```powershell
# Windows
git clone https://github.com/villelaitila/finnish-passport-photo "$env:USERPROFILE\.claude\skills\finnish-passport-photo"
```

No git? Use **Code → Download ZIP** on GitHub and extract it so that `SKILL.md` ends up at
`~/.claude/skills/finnish-passport-photo/SKILL.md`.

Start `claude` in any folder and ask something like
*"make a Finnish passport photo from ~/Downloads/IMG_1234.jpg"* or
*"tee tästä passikuva poliisille: kuva.jpg"*. To update later, run `git pull` in that folder.

### 2b. The script on its own

Clone the repository anywhere and run:

```bash
uv run scripts/make_passport_photo.py photo.jpg [--out result.jpg]
```

The first run takes a minute or two while uv downloads Python, the packages and the face
model. Later runs take a few seconds. To check your setup, run it on any clear front-facing
photo: the last line should be `RESULT: PASS`.

### Troubleshooting

| Message | Fix |
|---|---|
| `uv: command not found` | Open a new terminal after installing uv, or follow the PATH hint uv printed |
| `mediapipe==0.10.21 has no wheels with a matching platform tag` | Your computer is ARM Linux or ARM Windows, which is not supported (see the table above) |
| `libGL.so.1: cannot open shared object file` | Linux: `sudo apt install libgl1 libglib2.0-0` |
| `ERROR: no face found` / `more than one face` | Use a photo with exactly one clearly visible, front-facing face |
| `ERROR: crop box … falls outside the photo` | The head is too close to the edge of the picture; retake with more space around it |

MediaPipe is pinned to 0.10.21 on purpose: 1.0.x crashes on macOS during start-up.

## Usage details

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
