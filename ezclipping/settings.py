"""Settings window: clip button, in-game resolution, OBS connection, options. Native Windows look (ttk)."""

import re
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from ezclipping import hotkey, obs

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
HINT, ERROR, OK = "#55555f", "#b3261e", "#1e7e34"


def parse_res(text: str) -> tuple[int, int] | None:
    """'2200x1440', '2200 x 1440' or Apex launch options '-w 2200 -h 1440' -> (2200, 1440); None if not valid."""
    m = (re.fullmatch(r"\s*(\d{3,4})\s*[xX*]\s*(\d{3,4})\s*", text)
         or re.fullmatch(r"\s*-w\s+(\d{3,4})\s+-h\s+(\d{3,4})\s*", text))
    if not m:
        return None
    w, h = int(m[1]), int(m[2])
    return (w, h) if 640 <= w <= 7680 and 480 <= h <= 4320 and w >= h else None


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
        choice = self.res_var.get()
        res = parse_res(self.custom_var.get()) if choice == CUSTOM else RESOLUTIONS[choice]
        if res is None:
            self.res_error.configure(text="Type it like 2200 x 1440 or -w 2200 -h 1440.")
            self.res_error.pack(anchor="w", pady=(4, 0), after=self.custom)
            return
        new = {"clip_key": self.clip_key, "game_res": list(res), "beep": self.beep_var.get(),
               "auto_replay_buffer": self.rb_var.get(), "start_with_windows": self.startup_var.get()}
        if self.auto_var.get():
            new |= {"host": "localhost", "port": None, "password": None}
        else:
            port = self.port_var.get().strip()
            if not (port.isdigit() and 1 <= int(port) <= 65535):
                self.obs_error.configure(text="Port is a number from 1 to 65535 (OBS's default is 4455).")
                self.obs_error.pack(anchor="w", pady=(4, 0), after=self.status)
                return
            new |= {"host": self.host_var.get().strip() or "localhost", "port": int(port),
                    "password": self.password_var.get()}
        self.app.apply_settings(new)
        self.close()

    def close(self) -> None:
        self.stop_capturing()
        self.root.destroy()


def show(app, icon: Image.Image) -> None:
    """Open the settings window and block until it closes. Run it on its own thread: Tk stays on that thread."""
    Settings(app, icon).root.mainloop()
