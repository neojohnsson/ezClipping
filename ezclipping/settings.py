"""Settings window: clip button, in-game resolution, OBS connection, options. Native Windows look (ttk)."""

import re
import subprocess
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ezclipping import hotkey, obs, render
from ezclipping.hud import Box, box_for_res, valid_res, visible

RESOLUTIONS = {
    "1920 x 1080  (16:9)": (1920, 1080),
    "2560 x 1440  (16:9)": (2560, 1440),
    "3840 x 2160  (16:9)": (3840, 2160),
    "1728 x 1080  (16:10, stretched)": (1728, 1080),
    "1680 x 1050  (16:10)": (1680, 1050),
    "1440 x 1080  (4:3, stretched)": (1440, 1080),
    "1280 x 960  (4:3, stretched)": (1280, 960),
}
CUSTOM = "Custom"
WIDTH = 400  # px, text wraps here
HINT, ERROR, OK, ACCENT = "#55555f", "#b3261e", "#1e7e34", "#ff4655"


def parse_res(text: str) -> tuple[int, int] | None:
    """'2200x1440', '2200 x 1440' or Apex launch options '-w 2200 -h 1440' -> (2200, 1440); None if not valid."""
    m = (re.fullmatch(r"\s*(\d{3,4})\s*[xX*]\s*(\d{3,4})\s*", text)
         or re.fullmatch(r"\s*-w\s+(\d{3,4})\s+-h\s+(\d{3,4})\s*", text))
    if not m:
        return None
    w, h = int(m[1]), int(m[2])
    return (w, h) if valid_res(w, h) else None


def drag_to_box(x0: float, y0: float, x1: float, y1: float, width: int, height: int) -> Box | None:
    """A mouse drag (any direction) on a width x height picture -> box as fractions; None if too small."""
    left, right = sorted(min(max(v, 0), width) for v in (x0, x1))
    top, bottom = sorted(min(max(v, 0), height) for v in (y0, y1))
    if right - left < 0.03 * width or bottom - top < 0.01 * height:
        return None
    return (left / width, top / height, (right - left) / width, (bottom - top) / height)


class Settings:
    def __init__(self, app, icon: Image.Image):
        self.app, cfg = app, app.cfg
        self.clip_key = cfg["clip_key"]
        self.capturing = self.waiting_for_release = False

        root = self.root = tk.Tk()
        root.title("ezClipping settings")
        root.resizable(False, False)
        self.icon = ImageTk.PhotoImage(icon)  # keep a reference or Tk drops it
        root.iconphoto(True, self.icon)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Value.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Hint.TLabel", foreground=HINT)
        style.configure("Error.TLabel", foreground=ERROR)
        body = self.body = ttk.Frame(root, padding=(20, 8, 20, 20))
        body.pack(fill="both")

        # Clip button
        self.heading("Clip button")
        row = ttk.Frame(body)
        row.pack(fill="x")
        self.key_var = tk.StringVar(value=hotkey.key_name(self.clip_key))
        ttk.Label(row, textvariable=self.key_var, style="Value.TLabel").pack(side="left")
        self.change = ttk.Button(row, text="Change", command=self.start_capture)
        self.change.pack(side="right")
        self.hint("Saves the OBS replay. Works while Apex is in focus and adds no input lag. "
                  "Left and right mouse can't be used.")

        # In-game resolution
        self.heading("In-game resolution")
        res = tuple(cfg["game_res"])
        preset = next((label for label, r in RESOLUTIONS.items() if r == res), CUSTOM)
        self.res_var = tk.StringVar(value=preset)
        combo = ttk.Combobox(body, textvariable=self.res_var, values=[*RESOLUTIONS, CUSTOM], state="readonly")
        combo.pack(fill="x")
        combo.bind("<<ComboboxSelected>>", lambda e: self.show_custom())
        self.custom_var = tk.StringVar(value=f"{res[0]} x {res[1]}")
        self.custom = ttk.Entry(body, textvariable=self.custom_var)
        self.res_error = ttk.Label(body, style="Error.TLabel", wraplength=WIDTH)
        self.res_hint = self.hint("What Apex runs at, stretched too: type 2200 x 1440 or -w 2200 -h 1440. "
                                  "It tells ezClipping where your health bar is.")
        self.show_custom()
        self.box: Box | None = tuple(cfg["box"]) if cfg["box"] else None
        self.box_row = ttk.Frame(body)
        self.box_row.pack(fill="x", pady=(8, 0))
        self.box_var = tk.StringVar()
        ttk.Label(self.box_row, textvariable=self.box_var).pack(side="left")
        self.reset = ttk.Button(self.box_row, text="Reset", command=self.reset_box)
        self.reset.pack(side="right")
        ttk.Button(self.box_row, text="Preview", command=self.preview).pack(side="right", padx=(0, 6))
        ttk.Button(self.box_row, text="Calibrate", command=self.calibrate).pack(side="right", padx=(0, 6))
        self.box_msg = ttk.Label(body, wraplength=WIDTH, justify="left")
        self.update_box_label()

        # OBS
        self.heading("OBS")
        ws = obs.websocket_settings()
        self.auto_var = tk.BooleanVar(value=cfg["port"] is None and cfg["password"] is None)
        ttk.Checkbutton(body, text="Use OBS's own WebSocket settings (recommended)", variable=self.auto_var,
                        command=self.toggle_auto).pack(anchor="w")
        grid = ttk.Frame(body)
        grid.pack(fill="x", pady=(6, 0))
        grid.columnconfigure(1, weight=1)
        self.host_var = tk.StringVar(value=cfg["host"])
        self.port_var = tk.StringVar(value=str(cfg["port"] or ws.get("port", 4455)))
        self.password_var = tk.StringVar(value=ws.get("password", "") if cfg["password"] is None else cfg["password"])
        self.fields = []
        for r, (label, var, secret) in enumerate([("Host", self.host_var, False), ("Port", self.port_var, False),
                                                  ("Password", self.password_var, True)]):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w", padx=(0, 10), pady=2)
            entry = ttk.Entry(grid, textvariable=var, show="•" if secret else "")
            entry.grid(row=r, column=1, sticky="ew", pady=2)
            self.fields.append(entry)
        self.obs_error = ttk.Label(body, style="Error.TLabel", wraplength=WIDTH)
        self.status = ttk.Label(body, wraplength=WIDTH, justify="left")
        self.status.pack(anchor="w", pady=(6, 0))
        self.toggle_auto()

        # Options
        self.heading("Options")
        self.beep_var = tk.BooleanVar(value=cfg["beep"])
        self.rb_var = tk.BooleanVar(value=cfg["auto_replay_buffer"])
        self.startup_var = tk.BooleanVar(value=cfg["start_with_windows"])
        for text, var in [("Beep when the clip button saves a replay", self.beep_var),
                          ("Start OBS's replay buffer automatically", self.rb_var),
                          ("Start ezClipping with Windows", self.startup_var)]:
            ttk.Checkbutton(body, text=text, variable=var).pack(anchor="w", pady=1)

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="Save", command=self.save, default="active").pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=(0, 8))
        root.bind("<Return>", lambda e: None if self.capturing else self.save())
        root.bind("<Escape>", lambda e: None if self.capturing else self.close())
        root.protocol("WM_DELETE_WINDOW", self.close)
        body.update_idletasks()
        body.configure(width=WIDTH + 40)

        self.refresh()
        root.lift()
        root.focus_force()

    def heading(self, text: str) -> None:
        ttk.Label(self.body, text=text, style="Heading.TLabel").pack(anchor="w", pady=(14, 4))

    def hint(self, text: str) -> ttk.Label:
        label = ttk.Label(self.body, text=text, style="Hint.TLabel", wraplength=WIDTH, justify="left")
        label.pack(anchor="w", pady=(4, 0))
        return label

    def show_custom(self) -> None:
        if self.res_var.get() == CUSTOM:
            self.custom.pack(fill="x", pady=(6, 0), before=self.res_hint)
            self.custom.focus_set()
        else:
            self.custom.pack_forget()
            self.res_error.pack_forget()

    def pending_res(self) -> tuple[int, int] | None:
        choice = self.res_var.get()
        return parse_res(self.custom_var.get()) if choice == CUSTOM else RESOLUTIONS[choice]

    def current_box(self) -> Box:
        return self.box or box_for_res(*(self.pending_res() or self.app.cfg["game_res"]))

    def update_box_label(self) -> None:
        self.box_var.set("Health bar: calibrated by you" if self.box else "Health bar: from your resolution")
        self.reset.state(["!disabled"] if self.box else ["disabled"])

    def reset_box(self) -> None:
        self.box = None
        self.update_box_label()
        self.message("Back to the position for your resolution.", HINT)

    def message(self, text: str, color: str) -> None:
        self.box_msg.configure(text=text, foreground=color)
        self.box_msg.pack(anchor="w", pady=(4, 0), after=self.box_row)

    def screenshot(self, width: int) -> Image.Image | None:
        conn = self.app.conn
        if not conn:
            self.message("Open OBS first: the picture comes from what OBS shows.", ERROR)
            return None
        try:
            return conn.screenshot(width).convert("RGB")
        except obs.CONNECT_ERRORS as e:
            self.message(f"Couldn't get a picture from OBS: {e}", ERROR)
            return None

    def calibrate(self) -> None:
        shot = self.screenshot(1600)
        if shot:
            Calibrate(self, shot)

    def preview(self) -> None:
        shot = self.screenshot(1920)
        if not shot:
            return
        self.message("Making the preview...", HINT)
        self.root.update_idletasks()
        try:
            frame = render.preview(shot, self.current_box())
        except (subprocess.CalledProcessError, OSError) as e:
            self.message(f"Couldn't make the preview: {e}", ERROR)
            return
        self.box_msg.pack_forget()
        top = tk.Toplevel(self.root)
        top.title("Preview")
        top.resizable(False, False)
        top.transient(self.root)
        height = min(800, top.winfo_screenheight() - 160)
        top.photo = ImageTk.PhotoImage(frame.resize((round(height * 9 / 16), height), Image.LANCZOS))
        pad = ttk.Frame(top, padding=16)
        pad.pack()
        ttk.Label(pad, image=top.photo).pack()
        ttk.Label(pad, text="How your clips will look, made from what OBS shows right now.", style="Hint.TLabel",
                  wraplength=round(height * 9 / 16)).pack(anchor="w", pady=(8, 0))
        ttk.Button(pad, text="Close", command=top.destroy).pack(anchor="e", pady=(10, 0))
        top.bind("<Escape>", lambda e: top.destroy())

    def toggle_auto(self) -> None:
        auto = self.auto_var.get()
        if auto:  # show what OBS uses, read-only
            ws = obs.websocket_settings()
            self.host_var.set("localhost")
            self.port_var.set(str(ws.get("port", 4455)))
            self.password_var.set(ws.get("password", ""))
        for entry in self.fields:
            entry.state(["disabled"] if auto else ["!disabled"])

    def refresh(self) -> None:
        """Every 0.2 s: OBS status, raise-window requests from the tray, app quitting."""
        if self.app.stop.is_set():
            self.root.destroy()
            return
        if self.app.raise_settings.is_set():
            self.app.raise_settings.clear()
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        if self.app.conn:
            text, color = "Connected to OBS.", OK
        elif obs.websocket_settings().get("enabled") is False:
            text, color = ("Not connected. In OBS, open Tools > WebSocket Server Settings "
                           "and tick Enable WebSocket server."), ERROR
        else:
            text, color = "Not connected. Open OBS and ezClipping connects by itself.", HINT
        self.status.configure(text=text, foreground=color)
        self.root.after(200, self.refresh)

    def start_capture(self) -> None:
        self.capturing = self.app.capturing = True  # app ignores the clip button meanwhile
        self.waiting_for_release = True  # ignore whatever is still held (the click on Change, Enter)
        self.key_var.set("Press a key or mouse button (Esc cancels)")
        self.change.state(["disabled"])
        self.root.after(20, self.poll_capture)

    def poll_capture(self) -> None:
        down = [vk for vk in hotkey.CAPTURABLE if hotkey.key_state(vk) & 0x8000]
        if self.waiting_for_release:
            self.waiting_for_release = bool(down) or bool(hotkey.key_state(hotkey.VK_ESCAPE) & 0x8000)
        elif hotkey.key_state(hotkey.VK_ESCAPE) & 0x8000:
            return self.end_capture(None)
        elif down:
            return self.end_capture(down[0])
        self.root.after(20, self.poll_capture)

    def end_capture(self, vk: int | None) -> None:
        if vk:
            self.clip_key = vk
        self.key_var.set(hotkey.key_name(self.clip_key))
        self.change.state(["!disabled"])
        self.root.after(300, self.stop_capturing)  # let go of the key before it can save a replay

    def stop_capturing(self) -> None:
        self.capturing = self.app.capturing = False

    def save(self) -> None:
        res = self.pending_res()
        if res is None:
            self.res_error.configure(text="Type it like 2200 x 1440 or -w 2200 -h 1440.")
            self.res_error.pack(anchor="w", pady=(4, 0), after=self.custom)
            return
        new = {"clip_key": self.clip_key, "game_res": list(res), "box": list(self.box) if self.box else None,
               "beep": self.beep_var.get(),
               "auto_replay_buffer": self.rb_var.get(), "start_with_windows": self.startup_var.get()}
        if self.auto_var.get():
            new |= {"host": "localhost", "port": None, "password": None}
        else:
            port, host = self.port_var.get().strip(), self.host_var.get().strip() or "localhost"
            problem = None
            if not (port.isdigit() and 1 <= int(port) <= 65535):
                problem = "Port is a number from 1 to 65535 (OBS's default is 4455)."
            elif not obs.valid_host(host):
                problem = "Host is just a name or IP, like localhost. The port goes in Port."
            if problem:
                self.obs_error.configure(text=problem)
                self.obs_error.pack(anchor="w", pady=(4, 0), after=self.status)
                return
            new |= {"host": host, "port": int(port), "password": self.password_var.get()}
        self.app.apply_settings(new)
        self.close()

    def close(self) -> None:
        self.stop_capturing()
        self.root.destroy()


class Calibrate:
    """Drag a box over the health bar on a fresh OBS screenshot."""

    def __init__(self, settings: Settings, shot: Image.Image):
        self.settings, self.shot, self.box, self.rect, self.start = settings, shot, None, None, (0, 0)
        top = self.top = tk.Toplevel(settings.root)
        top.title("Calibrate health bar")
        top.resizable(False, False)
        top.transient(settings.root)
        top.grab_set()
        scale = min(1.0, (top.winfo_screenwidth() - 80) / shot.width, (top.winfo_screenheight() - 240) / shot.height)
        self.w, self.h = round(shot.width * scale), round(shot.height * scale)
        self.photo = ImageTk.PhotoImage(shot.resize((self.w, self.h), Image.LANCZOS))

        pad = ttk.Frame(top, padding=16)
        pad.pack()
        ttk.Label(pad, text="Drag a box around your health bar: portrait, name and both bars. It has to be on "
                            "screen, so be alive in a match or the Firing Range.", wraplength=self.w).pack(anchor="w")
        canvas = self.canvas = tk.Canvas(pad, width=self.w, height=self.h, highlightthickness=0, cursor="crosshair")
        canvas.pack(pady=(10, 0))
        canvas.create_image(0, 0, image=self.photo, anchor="nw")
        x, y, w, h = settings.current_box()  # where it is now, dashed
        canvas.create_rectangle(x * self.w, y * self.h, (x + w) * self.w, (y + h) * self.h, outline="#d0d4dc",
                                dash=(4, 3))
        canvas.bind("<ButtonPress-1>", self.press)
        canvas.bind("<B1-Motion>", self.drag)
        canvas.bind("<ButtonRelease-1>", self.release)
        self.msg = ttk.Label(pad, text="The dashed box is where ezClipping looks now.", style="Hint.TLabel",
                             wraplength=self.w)
        self.msg.pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(pad)
        buttons.pack(fill="x", pady=(10, 0))
        self.use = ttk.Button(buttons, text="Use this box", command=self.done, state="disabled")
        self.use.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=top.destroy).pack(side="right", padx=(0, 8))
        top.bind("<Escape>", lambda e: top.destroy())

    def press(self, e) -> None:
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline=ACCENT, width=2)

    def drag(self, e) -> None:
        self.canvas.coords(self.rect, *self.start, e.x, e.y)

    def release(self, e) -> None:
        self.box = drag_to_box(*self.start, e.x, e.y, self.w, self.h)
        if not self.box:
            self.msg.configure(text="Drag a bigger box around the whole health bar.", foreground=ERROR)
            self.use.state(["disabled"])
            return
        small = self.shot.resize((640, round(640 * self.shot.height / self.shot.width)))  # what the gate checks
        if visible(small, self.box):
            self.msg.configure(text="Found your HP bar in this box.", foreground=OK)
        else:
            self.msg.configure(text="No HP bar found in this box. If you're alive in a match, redraw it around "
                                    "the whole card. The check that pauses rendering during matches uses it.",
                               foreground=ERROR)
        self.use.state(["!disabled"])

    def done(self) -> None:
        self.settings.box = self.box
        self.settings.update_box_label()
        self.settings.message("Calibrated. Hit Preview to see the result, Save to keep it.", OK)
        self.top.destroy()


def show(app, icon: Image.Image) -> None:
    """Open the settings window and block until it closes. Run it on its own thread: Tk stays on that thread."""
    Settings(app, icon).root.mainloop()
