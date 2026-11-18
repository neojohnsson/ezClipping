"""OBS replay -> 1080x1920 vertical clip in one ffmpeg pass."""

import functools
import subprocess
import sys
import time
from pathlib import Path

from ezclipping.hud import Box, box_for_res

FFMPEG = "ffmpeg"
ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv", "libx264")
ENCODER_ARGS = {"h264_nvenc": ["-preset", "p5"], "libx264": ["-preset", "veryfast"]}
NO_WINDOW = subprocess.CREATE_NO_WINDOW


# Outline of the health-bar card inside its box (fractions), clockwise. Angled ends, flat top/bottom.
CARD = [(0.043, 0.073), (0.914, 0.073), (0.996, 0.81), (0.969, 0.948), (0.094, 0.948), (0.008, 0.25)]


def card_mask_expr() -> str:
    """geq expression: 255 inside the convex CARD outline, 0 outside."""
    edges = zip(CARD, CARD[1:] + CARD[:1])
    tests = [f"gte({x2 - x1:.4f}*(Y/H-{y1})-({y2 - y1:.4f})*(X/W-{x1}),0)" for (x1, y1), (x2, y2) in edges]
    return "255*" + "*".join(tests)


def filter_graph(box: Box) -> str:
    """Blurred cover background + center half of the frame + enlarged, card-shaped health bar."""
    x, y, w, h = box
    return (
        "[0:v]fps=60,format=yuv420p,split=3[a][b][c];"  # GPU decode gives nv12: odd crops break its chroma
        "[a]crop=ih*9/16:ih,scale=270:480,boxblur=4:2,scale=1080:1920[bg];"
        "[b]crop=iw/2:ih,scale=1080:-2[mid];"
        f"[c]crop=iw*{w}:ih*{h}:iw*{x}:ih*{y},scale=756:-2,split[hb][hbref];"
        # mask is drawn once (1 frame, 2x size for smooth edges), then looped and fitted to the bar
        f"nullsrc=s=1512x284,format=gray,geq=lum='{card_mask_expr()}',trim=end_frame=1,"
        "loop=loop=-1:size=1[m0];"
        "[m0][hbref]scale=rw:rh[m];"
        "[hb][m]alphamerge[card];"
        "[bg][mid]overlay=0:(H-h)/2[v];"
        "[v][card]overlay=(W-w)/2:H*0.72-h/2:shortest=1,format=yuv420p[out]"
    )


@functools.cache
def detect_encoder(candidates: tuple[str, ...] = ENCODERS) -> str:
    """First H.264 encoder that actually works on this PC (GPU ones first)."""
    for enc in candidates:
        test = [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1", "-frames:v", "1",
                "-c:v", enc, "-f", "null", "-"]
        if subprocess.run(test, check=False, capture_output=True, creationflags=NO_WINDOW).returncode == 0:
            return enc
    raise RuntimeError("No working H.264 encoder found")


def output_path(src: Path) -> Path:
    return src.parent / "vertical" / f"{src.stem}_vertical.mp4"


def render(src: str | Path, box: Box) -> Path:
    """Render src to <src folder>/vertical/<name>_vertical.mp4 at idle priority. Never touches src."""
    src = Path(src)
    dst = output_path(src)
    dst.parent.mkdir(exist_ok=True)
    part = dst.with_suffix(".part.mp4")
    enc = detect_encoder()
    cmd = [
        FFMPEG, "-v", "error", "-y", "-hwaccel", "d3d11va", "-i", str(src),
        "-filter_complex", filter_graph(box), "-map", "[out]", "-map", "0:a:0?",
        "-c:v", enc, *ENCODER_ARGS.get(enc, []), "-b:v", "20M", "-maxrate", "30M", "-bufsize", "40M",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(part),
    ]
    done = subprocess.run(cmd, check=False, capture_output=True, text=True,
                          creationflags=NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS)
    if done.returncode:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed: {done.stderr.strip()[-800:]}")
    part.replace(dst)
    return dst


if __name__ == "__main__":
    # python -m ezclipping.render <replay> [in-game WxH, default 2200x1440]
    res = sys.argv[2] if len(sys.argv) > 2 else "2200x1440"
    gw, gh = map(int, res.lower().split("x"))
    start = time.perf_counter()
    print(render(sys.argv[1], box_for_res(gw, gh)), f"{time.perf_counter() - start:.1f}s")
