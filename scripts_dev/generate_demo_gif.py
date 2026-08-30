"""Generate pixel-perfect animated terminal demo GIF for README."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WIDTH = 960
HEIGHT = 560
BG_COLOR = (13, 17, 26)       # Dark sleek slate
HEADER_BG = (22, 29, 44)      # Window header
BORDER_COLOR = (42, 54, 80)   # Border outline
TEXT_COLOR = (241, 245, 249)  # White text
CMD_COLOR = (56, 189, 248)    # Cyan
GREEN_COLOR = (74, 222, 128)  # Android Green
YELLOW_COLOR = (250, 204, 21) # Yellow
PURPLE_COLOR = (192, 132, 252)# Purple
MUTED_COLOR = (148, 163, 184) # Muted slate


def get_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    font_names = ["consola.ttf", "CascadiaCode.ttf", "cour.ttf", "arial.ttf"]
    if bold:
        font_names = ["consolab.ttf", "CascadiaCode-Bold.ttf", "arialbd.ttf"] + font_names
    for name in font_names:
        p = Path("C:/Windows/Fonts") / name
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    return ImageFont.load_default()


font_mono = get_font(15)
font_mono_bold = get_font(15, bold=True)
font_title = get_font(13, bold=True)


def draw_window_frame(draw: ImageDraw.ImageDraw):
    # Background
    draw.rectangle([(0, 0), (WIDTH, HEIGHT)], fill=BG_COLOR)
    # Header bar
    draw.rectangle([(0, 0), (WIDTH, 42)], fill=HEADER_BG)
    draw.line([(0, 42), (WIDTH, 42)], fill=BORDER_COLOR, width=1)
    # Outer border
    draw.rectangle([(0, 0), (WIDTH - 1, HEIGHT - 1)], outline=BORDER_COLOR, width=1)

    # Window dots
    draw.ellipse([(16, 14), (28, 26)], fill=(239, 68, 68))   # Red
    draw.ellipse([(36, 14), (48, 26)], fill=(234, 179, 8))   # Yellow
    draw.ellipse([(56, 14), (68, 26)], fill=(34, 197, 94))   # Green

    # Window title
    title = "Android Agent Harness — Parallel Review & E2E Smoke Pipeline"
    bbox = font_title.getbbox(title)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) // 2, 13), title, fill=MUTED_COLOR, font=font_title)


LINES_SCENE_1 = [
    [("agent@android-workspace:~$ ", MUTED_COLOR), ("python .agents/scripts/review_package.py", CMD_COLOR)],
    [("[HARNESS] ", PURPLE_COLOR), ("Captured review package: review-20260830-180512.diff (6 files)", TEXT_COLOR)],
    [("[HARNESS] ", PURPLE_COLOR), ("Package SHA256: 46007c5bb20d... (Cryptographic Barrier Locked)", YELLOW_COLOR)],
]

LINES_SCENE_2 = LINES_SCENE_1 + [
    [("", TEXT_COLOR)],
    [("[*] ", CMD_COLOR), ("Dispatching 6 Parallel Quality Guardians...", TEXT_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("bug-reviewer-agent          -> BUG_PASS        ", GREEN_COLOR), ("(0 logic bugs, thread-safe)", MUTED_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("convention-reviewer-agent   -> CONVENTION_PASS ", GREEN_COLOR), ("(Clean Arch, KDoc contracts)", MUTED_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("security-reviewer-agent     -> SECURITY_PASS   ", GREEN_COLOR), ("(OWASP Mobile Top 10 safe)", MUTED_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("perf-anr-guardian-agent     -> PERF_PASS       ", GREEN_COLOR), ("(Main-thread I/O free, 0 ANRs)", MUTED_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("regression-impact-reviewer  -> REGRESSION_PASS ", GREEN_COLOR), ("(Zero regressions, API safe)", MUTED_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("test-quality-reviewer-agent -> TEST_PASS       ", GREEN_COLOR), ("(runTest assertions verified)", MUTED_COLOR)],
    [("[SUCCESS] ", GREEN_COLOR), ("6/6 Review Guardians APPROVED. Cryptographic delivery unlocked!", GREEN_COLOR)],
]

LINES_SCENE_3 = LINES_SCENE_2 + [
    [("", TEXT_COLOR)],
    [("agent@android-workspace:~$ ", MUTED_COLOR), ("python .agents/scripts/run_gradle_task.py :app:assembleDebug", CMD_COLOR)],
    [("  > Task :app:compileDebugKotlin", MUTED_COLOR)],
    [("  > Task :app:assembleDebug", MUTED_COLOR)],
    [("  BUILD SUCCESSFUL in 3.2s", GREEN_COLOR)],
]

LINES_SCENE_4 = LINES_SCENE_3 + [
    [("", TEXT_COLOR)],
    [("agent@android-workspace:~$ ", MUTED_COLOR), ("python .agents/scripts/run_e2e_smoke.py --auto-diff", CMD_COLOR)],
    [("[*] ", CMD_COLOR), ("Auto-diff discovered target: .features.events.GroupsAddEventScreenActivity", TEXT_COLOR)],
    [("[*] ", CMD_COLOR), ("Targeted E2E Smoke Flow on Physical Device: NV7XIBKB9P8TJBAU ...", YELLOW_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("Target UI foregrounded & hierarchy dumped (24 interactive nodes)", TEXT_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("Scroll gesture & frame responsiveness verified without UI jank", TEXT_COLOR)],
    [("  [PASS] ", GREEN_COLOR), ("Real-time Logcat forensics: 0 fatal crashes, 0 ANRs, 0 Room errors", TEXT_COLOR)],
    [("[SUCCESS] ", GREEN_COLOR), ("Autonomous Targeted E2E Smoke Test PASSED! (Evidence captured)", GREEN_COLOR)],
]


def render_scene(lines: list) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)
    draw_window_frame(draw)

    y = 56
    line_height = 20

    # If lines exceed screen height, scroll window
    visible_lines = lines[-23:] if len(lines) > 23 else lines

    for line_parts in visible_lines:
        x = 24
        for text, color in line_parts:
            draw.text((x, y), text, fill=color, font=font_mono)
            bbox = font_mono.getbbox(text)
            x += (bbox[2] - bbox[0])
        y += line_height

    return img


def build_gif():
    out_dir = Path("docs/assets")
    out_dir.mkdir(parents=True, exist_ok=True)
    gif_path = out_dir / "demo.gif"

    frames = []
    durations = []

    # Scene 1: Command 1 (review package)
    img1 = render_scene(LINES_SCENE_1)
    frames.append(img1)
    durations.append(1200)

    # Scene 2: 6 Review Guardians running & passing
    img2 = render_scene(LINES_SCENE_2)
    frames.append(img2)
    durations.append(2500)

    # Scene 3: Assemble Debug
    img3 = render_scene(LINES_SCENE_3)
    frames.append(img3)
    durations.append(1400)

    # Scene 4: Targeted E2E Smoke on Physical Device
    img4 = render_scene(LINES_SCENE_4)
    frames.append(img4)
    durations.append(4000)

    # Save animated GIF
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Generated {gif_path} ({gif_path.stat().st_size} bytes)")


if __name__ == "__main__":
    build_gif()
