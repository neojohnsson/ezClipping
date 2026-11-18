"""OBS replay -> 1080x1920 vertical clip in one ffmpeg pass."""

import ctypes
import functools
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from PIL import Image

from ezclipping.hud import Box, box_for_res

# the packaged exe carries its own ffmpeg (PyInstaller unpacks it to sys._MEIPASS); in dev, use the one on PATH
FFMPEG = str(Path(sys._MEIPASS) / "ffmpeg.exe") if getattr(sys, "frozen", False) else "ffmpeg"
ENCODERS = ("h264_nvenc", "h264_amf", "h264_qsv", "libx264")
ENCODER_ARGS = {"h264_nvenc": ["-preset", "p5"], "libx264": ["-preset", "veryfast"]}
NO_WINDOW = subprocess.CREATE_NO_WINDOW
PROCESS_TERMINATE, PROCESS_SET_QUOTA, PROCESS_SUSPEND_RESUME = 0x0001, 0x0100, 0x0800
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 0x2000, 9

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # own instances: don't touch ctypes.windll's
_ntdll = ctypes.WinDLL("ntdll")
_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_bool, ctypes.c_uint32]
_kernel32.CreateJobObjectW.restype = ctypes.c_void_p
_kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
_kernel32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
_kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
_ntdll.NtSuspendProcess.argtypes = _ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


@functools.cache
def _kill_on_exit_job() -> int:
    """A Windows job object that kills every ffmpeg in it when ezClipping exits, even on a hard kill."""
    job = _kernel32.CreateJobObjectW(None, None)
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    _kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                      ctypes.sizeof(info))
    return job


def _open(pid: int, access: int) -> int:
    handle = _kernel32.OpenProcess(access, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


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


@dataclass
class Job:
    src: Path
    proc: subprocess.Popen
    part: Path  # ffmpeg writes here, renamed to dst only when it succeeds
    dst: Path
    errors: IO[bytes]  # ffmpeg's stderr (a file, so a chatty ffmpeg can't block on a full pipe)


def start(src: str | Path, box: Box) -> Job:
    """Start rendering src to <src folder>/vertical/<name>_vertical.mp4 at idle priority. Never touches src."""
    src = Path(src)
    dst = output_path(src)
    dst.parent.mkdir(exist_ok=True)
    part = dst.with_suffix(".part.mp4")
    enc = detect_encoder()
    cmd = [
        FFMPEG, "-v", "error", "-nostdin", "-y", "-hwaccel", "d3d11va", "-i", str(src),
        "-filter_complex", filter_graph(box), "-map", "[out]", "-map", "0:a:0?",
        "-c:v", enc, *ENCODER_ARGS.get(enc, []), "-b:v", "20M", "-maxrate", "30M", "-bufsize", "40M",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-f", "mp4", str(part),
    ]
    errors = tempfile.TemporaryFile()  # noqa: SIM115 - lives as long as the job, closed in finish()/cancel()
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors,
                            creationflags=NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS)
    try:
        handle = _open(proc.pid, PROCESS_SET_QUOTA | PROCESS_TERMINATE)
        _kernel32.AssignProcessToJobObject(_kill_on_exit_job(), handle)
        _kernel32.CloseHandle(handle)
    except OSError:
        pass  # ffmpeg already exited (bad input): finish() reports it
    return Job(src, proc, part, dst, errors)


def finish(job: Job) -> Path:
    """Wait for the render, then move the .part file to its final name. RuntimeError if ffmpeg failed."""
    code = job.proc.wait()
    job.errors.seek(0)
    stderr = job.errors.read().decode(errors="replace").strip()
    job.errors.close()
    if code:
        job.part.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg exited {code}: {stderr[-800:]}")
    job.part.replace(job.dst)
    return job.dst


def cancel(job: Job) -> None:
    """Stop a running (or paused) render and delete its half-written file."""
    job.proc.kill()
    job.proc.wait()
    job.errors.close()
    job.part.unlink(missing_ok=True)


def _nt(call: str, job: Job) -> None:
    handle = _open(job.proc.pid, PROCESS_SUSPEND_RESUME)
    try:
        getattr(_ntdll, call)(handle)
    finally:
        _kernel32.CloseHandle(handle)


def suspend(job: Job) -> None:
    """Freeze ffmpeg in place: 0% CPU/GPU until resume(), nothing lost."""
    _nt("NtSuspendProcess", job)


def resume(job: Job) -> None:
    _nt("NtResumeProcess", job)


def render(src: str | Path, box: Box) -> Path:
    return finish(start(src, box))


def preview(frame: Image.Image, box: Box) -> Image.Image:
    """One 1080x1920 frame of the vertical layout made from a screenshot, with the same filter graph."""
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "frame.png", Path(tmp) / "preview.png"
        frame.convert("RGB").save(src)
        subprocess.run([FFMPEG, "-v", "error", "-i", str(src), "-filter_complex", filter_graph(box),
                        "-map", "[out]", "-frames:v", "1", str(out)],
                       check=True, capture_output=True, creationflags=NO_WINDOW)
        with Image.open(out) as img:
            return img.copy()


if __name__ == "__main__":
    # python -m ezclipping.render <replay> [in-game WxH, default 2200x1440]
    res = sys.argv[2] if len(sys.argv) > 2 else "2200x1440"
    gw, gh = map(int, res.lower().split("x"))
    start = time.perf_counter()
    print(render(sys.argv[1], box_for_res(gw, gh)), f"{time.perf_counter() - start:.1f}s")
