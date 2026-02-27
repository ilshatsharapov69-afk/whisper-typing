"""Floating audio visualizer overlay for whisper-typing."""

import threading
import tkinter as tk
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from whisper_typing.audio_capture import AudioRecorder

# Overlay dimensions
BAR_COUNT = 32
BAR_WIDTH = 4
BAR_GAP = 2
BAR_MAX_HEIGHT = 55
WINDOW_PADDING = 6
WINDOW_WIDTH = BAR_COUNT * (BAR_WIDTH + BAR_GAP) - BAR_GAP + WINDOW_PADDING * 2
WINDOW_HEIGHT = BAR_MAX_HEIGHT + WINDOW_PADDING * 2
BOTTOM_MARGIN = 60

# Transparent background key color (will be made invisible)
TRANSPARENT_COLOR = "#010101"

# Gradient stops: green -> cyan -> yellow -> red
_GRADIENT = [
    (0.0, (0, 210, 106)),    # green
    (0.35, (0, 200, 220)),   # cyan
    (0.6, (245, 194, 17)),   # yellow
    (0.85, (255, 80, 40)),   # orange-red
    (1.0, (255, 50, 50)),    # red
]


def _lerp_color(ratio: float) -> str:
    """Interpolate gradient color by ratio 0..1."""
    ratio = max(0.0, min(1.0, ratio))
    for i in range(len(_GRADIENT) - 1):
        t0, c0 = _GRADIENT[i]
        t1, c1 = _GRADIENT[i + 1]
        if ratio <= t1:
            t = (ratio - t0) / (t1 - t0) if t1 > t0 else 0
            r = int(c0[0] + (c1[0] - c0[0]) * t)
            g = int(c0[1] + (c1[1] - c0[1]) * t)
            b = int(c0[2] + (c1[2] - c0[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{_GRADIENT[-1][1][0]:02x}{_GRADIENT[-1][1][1]:02x}{_GRADIENT[-1][1][2]:02x}"


def _dim_color(hex_color: str, factor: float = 0.3) -> str:
    """Dim a hex color for glow effect."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    r = int(r * factor)
    g = int(g * factor)
    b = int(b * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


class AudioOverlay:
    """Floating overlay showing audio level visualization — bars only, no background."""

    def __init__(self) -> None:
        """Initialize the AudioOverlay."""
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._visible = False
        self._recorder: "AudioRecorder | None" = None
        self._bar_heights: list[float] = [0.0] * BAR_COUNT

    def start(self) -> None:
        """Start the overlay in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()

    def _run_tk(self) -> None:
        """Run the tkinter main loop in a background thread."""
        self._root = tk.Tk()
        self._root.title("Whisper Overlay")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=TRANSPARENT_COLOR)
        # Make the background color fully transparent — only bars are visible
        self._root.attributes("-transparentcolor", TRANSPARENT_COLOR)

        # Position: bottom center of screen
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - WINDOW_WIDTH) // 2
        y = screen_h - WINDOW_HEIGHT - BOTTOM_MARGIN
        self._root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

        self._canvas = tk.Canvas(
            self._root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=TRANSPARENT_COLOR,
            highlightthickness=0,
        )
        self._canvas.pack()

        # Glow bars (wider, dimmer — drawn behind main bars)
        self._glow_items: list[int] = []
        for i in range(BAR_COUNT):
            bx = WINDOW_PADDING + i * (BAR_WIDTH + BAR_GAP)
            glow_pad = 2
            item = self._canvas.create_rectangle(
                bx - glow_pad,
                WINDOW_HEIGHT - WINDOW_PADDING,
                bx + BAR_WIDTH + glow_pad,
                WINDOW_HEIGHT - WINDOW_PADDING,
                fill=TRANSPARENT_COLOR,
                outline="",
            )
            self._glow_items.append(item)

        # Main bars
        self._bar_items: list[int] = []
        for i in range(BAR_COUNT):
            bx = WINDOW_PADDING + i * (BAR_WIDTH + BAR_GAP)
            item = self._canvas.create_rectangle(
                bx,
                WINDOW_HEIGHT - WINDOW_PADDING,
                bx + BAR_WIDTH,
                WINDOW_HEIGHT - WINDOW_PADDING,
                fill=TRANSPARENT_COLOR,
                outline="",
            )
            self._bar_items.append(item)

        # Bar caps (rounded top — small ovals)
        self._cap_items: list[int] = []
        for i in range(BAR_COUNT):
            bx = WINDOW_PADDING + i * (BAR_WIDTH + BAR_GAP)
            cap = self._canvas.create_oval(
                bx - 1,
                WINDOW_HEIGHT - WINDOW_PADDING - 2,
                bx + BAR_WIDTH + 1,
                WINDOW_HEIGHT - WINDOW_PADDING + 2,
                fill=TRANSPARENT_COLOR,
                outline="",
            )
            self._cap_items.append(cap)

        # Start hidden
        self._root.withdraw()
        self._visible = False

        self._update_loop()
        self._root.mainloop()

    def _update_loop(self) -> None:
        """Periodically update bar heights from audio data."""
        if not self._running or not self._root:
            return

        if self._visible:
            if self._recorder:
                self._update_bars()
            else:
                # Decay bars when in processing mode
                for i in range(BAR_COUNT):
                    self._bar_heights[i] *= 0.85
                self._draw_bars()

        self._root.after(33, self._update_loop)  # ~30 FPS

    def _update_bars(self) -> None:
        """Update equalizer bars based on current audio level."""
        if not self._canvas or not self._recorder:
            return

        audio = self._recorder.get_current_data()
        if audio is not None and len(audio) > 0:
            chunk_size = min(len(audio), 4800)
            chunk = audio[-chunk_size:]

            segments = np.array_split(chunk, BAR_COUNT)
            for i, seg in enumerate(segments):
                rms = float(np.sqrt(np.mean(seg**2)))
                level = min(rms * 5.0, 1.0)
                # Smooth transition (faster attack, slower decay)
                if level > self._bar_heights[i]:
                    self._bar_heights[i] = self._bar_heights[i] * 0.2 + level * 0.8
                else:
                    self._bar_heights[i] = self._bar_heights[i] * 0.6 + level * 0.4
        else:
            for i in range(BAR_COUNT):
                self._bar_heights[i] *= 0.85

        self._draw_bars()

    def _draw_bars(self) -> None:
        """Render bars, glow, and caps on canvas."""
        if not self._canvas:
            return

        bottom_y = WINDOW_HEIGHT - WINDOW_PADDING
        for i in range(BAR_COUNT):
            h = max(2, self._bar_heights[i] * BAR_MAX_HEIGHT)
            bx = WINDOW_PADDING + i * (BAR_WIDTH + BAR_GAP)
            top_y = bottom_y - h
            ratio = h / BAR_MAX_HEIGHT
            color = _lerp_color(ratio)
            glow_color = _dim_color(color, 0.18)

            # Glow (wider, behind)
            glow_pad = 2
            glow_h = h + 4
            self._canvas.coords(
                self._glow_items[i],
                bx - glow_pad, bottom_y - glow_h,
                bx + BAR_WIDTH + glow_pad, bottom_y,
            )
            self._canvas.itemconfig(self._glow_items[i], fill=glow_color)

            # Main bar
            self._canvas.coords(self._bar_items[i], bx, top_y, bx + BAR_WIDTH, bottom_y)
            self._canvas.itemconfig(self._bar_items[i], fill=color)

            # Cap (rounded top)
            cap_r = BAR_WIDTH // 2 + 1
            cx = bx + BAR_WIDTH // 2
            self._canvas.coords(
                self._cap_items[i],
                cx - cap_r, top_y - 1,
                cx + cap_r, top_y + cap_r,
            )
            self._canvas.itemconfig(self._cap_items[i], fill=color)

    def show(self, recorder: "AudioRecorder") -> None:
        """Show the overlay and start visualizing audio."""
        self._recorder = recorder
        self._bar_heights = [0.0] * BAR_COUNT
        if self._root:
            self._root.after(0, self._do_show)

    def _do_show(self) -> None:
        if self._root:
            self._root.deiconify()
            self._visible = True

    def show_processing(self) -> None:
        """Switch overlay to processing state (bars decay)."""
        self._recorder = None
        if self._root:
            self._root.after(0, self._do_show)

    def hide(self) -> None:
        """Hide the overlay."""
        self._recorder = None
        if self._root:
            self._root.after(0, self._do_hide)

    def _do_hide(self) -> None:
        if self._root:
            self._root.withdraw()
            self._visible = False

    def stop(self) -> None:
        """Stop the overlay and destroy the window."""
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.destroy)
            except Exception:  # noqa: BLE001
                pass
