"""Floating audio visualizer overlay for whisper-typing."""

import math
import random
import threading
import tkinter as tk
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from whisper_typing.audio_capture import AudioRecorder

# Layout
BAR_COUNT = 32
BOTTOM_MARGIN = 60
TRANSPARENT_COLOR = "#010101"

# Available visualizer styles
STYLES = [
    "bars",
    "mirror",
    "wave",
    "circles",
    "blocks",
    "line",
]

# ── Color utilities ──────────────────────────────────────────────────────────

_GRADIENT_GREEN_RED = [
    (0.0, (0, 210, 106)),
    (0.35, (0, 200, 220)),
    (0.6, (245, 194, 17)),
    (0.85, (255, 80, 40)),
    (1.0, (255, 50, 50)),
]

_GRADIENT_CYAN_PURPLE = [
    (0.0, (0, 255, 255)),
    (0.4, (80, 140, 255)),
    (0.7, (160, 80, 255)),
    (1.0, (255, 40, 200)),
]

_GRADIENT_BLUE_WHITE = [
    (0.0, (30, 80, 220)),
    (0.5, (80, 180, 255)),
    (1.0, (220, 240, 255)),
]

_GRADIENT_FIRE = [
    (0.0, (60, 10, 0)),
    (0.3, (200, 60, 0)),
    (0.6, (255, 160, 20)),
    (0.85, (255, 220, 80)),
    (1.0, (255, 255, 180)),
]

_GRADIENT_NEON = [
    (0.0, (0, 255, 100)),
    (0.5, (0, 255, 255)),
    (1.0, (100, 200, 255)),
]

GRADIENTS = {
    "green_red": _GRADIENT_GREEN_RED,
    "cyan_purple": _GRADIENT_CYAN_PURPLE,
    "blue_white": _GRADIENT_BLUE_WHITE,
    "fire": _GRADIENT_FIRE,
    "neon": _GRADIENT_NEON,
}

DEFAULT_GRADIENT = "green_red"


def _lerp_gradient(ratio: float, gradient: list[tuple[float, tuple[int, int, int]]]) -> str:
    """Interpolate gradient color by ratio 0..1."""
    ratio = max(0.0, min(1.0, ratio))
    for i in range(len(gradient) - 1):
        t0, c0 = gradient[i]
        t1, c1 = gradient[i + 1]
        if ratio <= t1:
            t = (ratio - t0) / (t1 - t0) if t1 > t0 else 0
            r = int(c0[0] + (c1[0] - c0[0]) * t)
            g = int(c0[1] + (c1[1] - c0[1]) * t)
            b = int(c0[2] + (c1[2] - c0[2]) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    c = gradient[-1][1]
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def _dim_color(hex_color: str, factor: float = 0.3) -> str:
    """Dim a hex color."""
    r = int(int(hex_color[1:3], 16) * factor)
    g = int(int(hex_color[3:5], 16) * factor)
    b = int(int(hex_color[5:7], 16) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Overlay ──────────────────────────────────────────────────────────────────


class AudioOverlay:
    """Floating overlay showing audio level visualization."""

    def __init__(self) -> None:
        """Initialize the AudioOverlay."""
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._visible = False
        self._recorder: "AudioRecorder | None" = None
        self._bar_heights: list[float] = [0.0] * BAR_COUNT
        self._style: str = "bars"
        self._gradient_name: str = DEFAULT_GRADIENT
        self._gradient: list[tuple[float, tuple[int, int, int]]] = _GRADIENT_GREEN_RED
        self._canvas_items: list[Any] = []
        self._extra_items: list[Any] = []
        self._frame_count: int = 0
        # For dots style — peak trackers
        self._dot_peaks: list[float] = [0.0] * BAR_COUNT
        self._dot_velocities: list[float] = [0.0] * BAR_COUNT
        # Window size (depends on style)
        self._win_w: int = 0
        self._win_h: int = 0

    def set_style(self, style: str) -> None:
        """Change visualizer style at runtime."""
        if style in STYLES:
            self._style = style
            if self._root:
                self._root.after(0, self._rebuild_canvas)

    def set_gradient(self, name: str) -> None:
        """Change color gradient at runtime."""
        if name in GRADIENTS:
            self._gradient_name = name
            self._gradient = GRADIENTS[name]

    def _get_dimensions(self) -> tuple[int, int]:
        """Return (width, height) for the current style."""
        bar_w, bar_gap, pad = 4, 2, 6
        default_w = BAR_COUNT * (bar_w + bar_gap) - bar_gap + pad * 2  # ~198
        if self._style == "circles":
            return (140, 140)
        if self._style == "mirror":
            return (default_w, 120)
        return (default_w, 67)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the overlay in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_tk, daemon=True)
        self._thread.start()

    def _run_tk(self) -> None:
        """Run the tkinter main loop."""
        self._root = tk.Tk()
        self._root.title("Whisper Overlay")
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.configure(bg=TRANSPARENT_COLOR)
        self._root.attributes("-transparentcolor", TRANSPARENT_COLOR)

        self._rebuild_canvas()

        self._root.withdraw()
        self._visible = False
        self._update_loop()
        self._root.mainloop()

    def _rebuild_canvas(self) -> None:
        """Rebuild the canvas for the current style."""
        if not self._root:
            return

        w, h = self._get_dimensions()
        self._win_w, self._win_h = w, h

        # Reposition window
        screen_w = self._root.winfo_screenwidth()
        screen_h = self._root.winfo_screenheight()
        x = (screen_w - w) // 2
        y = screen_h - h - BOTTOM_MARGIN
        self._root.geometry(f"{w}x{h}+{x}+{y}")

        # Recreate canvas
        if self._canvas:
            self._canvas.destroy()
        self._canvas = tk.Canvas(
            self._root, width=w, height=h,
            bg=TRANSPARENT_COLOR, highlightthickness=0,
        )
        self._canvas.pack()

        self._canvas_items = []
        self._extra_items = []
        self._frame_count = 0

        # Pre-create canvas items for each style
        if self._style == "bars":
            self._init_bars()
        elif self._style == "mirror":
            self._init_mirror()
        elif self._style == "wave":
            self._init_wave()
        elif self._style == "circles":
            self._init_circles()
        elif self._style == "blocks":
            self._init_blocks()
        elif self._style == "line":
            self._init_line()

    # ── Update loop ──────────────────────────────────────────────────────

    def _update_loop(self) -> None:
        if not self._running or not self._root:
            return
        if self._visible:
            if self._recorder:
                self._sample_audio()
            else:
                for i in range(BAR_COUNT):
                    self._bar_heights[i] *= 0.85
            self._draw()
            self._frame_count += 1
        self._root.after(33, self._update_loop)

    def _sample_audio(self) -> None:
        """Sample audio data into bar heights."""
        if not self._recorder:
            return
        audio = self._recorder.get_current_data()
        if audio is not None and len(audio) > 0:
            chunk_size = min(len(audio), 4800)
            chunk = audio[-chunk_size:]
            segments = np.array_split(chunk, BAR_COUNT)
            for i, seg in enumerate(segments):
                rms = float(np.sqrt(np.mean(seg**2)))
                level = min(rms * 5.0, 1.0)
                if level > self._bar_heights[i]:
                    self._bar_heights[i] = self._bar_heights[i] * 0.2 + level * 0.8
                else:
                    self._bar_heights[i] = self._bar_heights[i] * 0.6 + level * 0.4
        else:
            for i in range(BAR_COUNT):
                self._bar_heights[i] *= 0.85

    def _draw(self) -> None:
        """Dispatch to style-specific draw method."""
        if self._style == "bars":
            self._draw_bars()
        elif self._style == "mirror":
            self._draw_mirror()
        elif self._style == "wave":
            self._draw_wave()
        elif self._style == "circles":
            self._draw_circles()
        elif self._style == "blocks":
            self._draw_blocks()
        elif self._style == "line":
            self._draw_line()

    # ── Style: BARS (classic equalizer) ──────────────────────────────────

    def _init_bars(self) -> None:
        bar_w, bar_gap, pad = 4, 2, 6
        max_h = self._win_h - pad * 2
        c = self._canvas
        bottom = self._win_h - pad
        # Glow + bar + cap per bar
        for i in range(BAR_COUNT):
            bx = pad + i * (bar_w + bar_gap)
            glow = c.create_rectangle(bx - 2, bottom, bx + bar_w + 2, bottom,
                                      fill=TRANSPARENT_COLOR, outline="")
            bar = c.create_rectangle(bx, bottom, bx + bar_w, bottom,
                                     fill=TRANSPARENT_COLOR, outline="")
            cap = c.create_oval(bx - 1, bottom - 2, bx + bar_w + 1, bottom + 2,
                                fill=TRANSPARENT_COLOR, outline="")
            self._canvas_items.append((glow, bar, cap))

    def _draw_bars(self) -> None:
        c = self._canvas
        if not c:
            return
        pad = 6
        bar_w, bar_gap = 4, 2
        max_h = self._win_h - pad * 2
        bottom = self._win_h - pad
        for i in range(BAR_COUNT):
            h = max(2, self._bar_heights[i] * max_h)
            bx = pad + i * (bar_w + bar_gap)
            top = bottom - h
            ratio = h / max_h
            color = _lerp_gradient(ratio, self._gradient)
            glow_c = _dim_color(color, 0.18)
            glow, bar, cap = self._canvas_items[i]
            c.coords(glow, bx - 2, bottom - h - 4, bx + bar_w + 2, bottom)
            c.itemconfig(glow, fill=glow_c)
            c.coords(bar, bx, top, bx + bar_w, bottom)
            c.itemconfig(bar, fill=color)
            cr = bar_w // 2 + 1
            cx = bx + bar_w // 2
            c.coords(cap, cx - cr, top - 1, cx + cr, top + cr)
            c.itemconfig(cap, fill=color)

    # ── Style: MIRROR (symmetric bars from center) ───────────────────────

    def _init_mirror(self) -> None:
        bar_w, bar_gap, pad = 4, 2, 6
        c = self._canvas
        mid_y = self._win_h // 2
        for i in range(BAR_COUNT):
            bx = pad + i * (bar_w + bar_gap)
            top_bar = c.create_rectangle(bx, mid_y, bx + bar_w, mid_y,
                                         fill=TRANSPARENT_COLOR, outline="")
            bot_bar = c.create_rectangle(bx, mid_y, bx + bar_w, mid_y,
                                         fill=TRANSPARENT_COLOR, outline="")
            glow = c.create_rectangle(bx - 1, mid_y, bx + bar_w + 1, mid_y,
                                      fill=TRANSPARENT_COLOR, outline="")
            self._canvas_items.append((top_bar, bot_bar, glow))

    def _draw_mirror(self) -> None:
        c = self._canvas
        if not c:
            return
        pad = 6
        bar_w, bar_gap = 4, 2
        mid_y = self._win_h // 2
        half_h = mid_y - pad
        for i in range(BAR_COUNT):
            h = max(1, self._bar_heights[i] * half_h)
            bx = pad + i * (bar_w + bar_gap)
            ratio = h / half_h
            color = _lerp_gradient(ratio, self._gradient)
            glow_c = _dim_color(color, 0.15)
            top_bar, bot_bar, glow = self._canvas_items[i]
            c.coords(top_bar, bx, mid_y - h, bx + bar_w, mid_y - 1)
            c.itemconfig(top_bar, fill=color)
            c.coords(bot_bar, bx, mid_y + 1, bx + bar_w, mid_y + h)
            c.itemconfig(bot_bar, fill=color)
            c.coords(glow, bx - 1, mid_y - h - 2, bx + bar_w + 1, mid_y + h + 2)
            c.itemconfig(glow, fill=glow_c)

    # ── Style: WAVE (smooth waveform) ────────────────────────────────────

    def _init_wave(self) -> None:
        c = self._canvas
        # Main wave line + glow line
        glow = c.create_line(0, 0, 0, 0, fill="#004444", width=6, smooth=True)
        line = c.create_line(0, 0, 0, 0, fill="#00ddaa", width=2, smooth=True)
        self._canvas_items = [glow, line]

    def _draw_wave(self) -> None:
        c = self._canvas
        if not c:
            return
        pad = 6
        mid_y = self._win_h // 2
        max_amp = mid_y - pad
        n = BAR_COUNT
        # Build smooth points
        points: list[float] = []
        for i in range(n):
            x = pad + (self._win_w - pad * 2) * i / (n - 1)
            amp = self._bar_heights[i] * max_amp
            # Add sine wobble for organic feel
            wobble = math.sin(self._frame_count * 0.1 + i * 0.5) * amp * 0.15
            y = mid_y - amp - wobble
            points.extend([x, y])
        if len(points) < 4:
            return
        color = _lerp_gradient(max(self._bar_heights) if self._bar_heights else 0, self._gradient)
        glow_c = _dim_color(color, 0.25)
        c.coords(self._canvas_items[0], *points)
        c.itemconfig(self._canvas_items[0], fill=glow_c)
        c.coords(self._canvas_items[1], *points)
        c.itemconfig(self._canvas_items[1], fill=color)

    # ── Style: CIRCLES (pulsing concentric rings) ────────────────────────

    def _init_circles(self) -> None:
        c = self._canvas
        cx, cy = self._win_w // 2, self._win_h // 2
        # 5 concentric rings + center dot
        for _ in range(5):
            ring = c.create_oval(cx, cy, cx, cy, fill="", outline="#00dd88", width=2)
            self._canvas_items.append(ring)
        dot = c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="#00ffaa", outline="")
        self._extra_items = [dot]

    def _draw_circles(self) -> None:
        c = self._canvas
        if not c:
            return
        cx, cy = self._win_w // 2, self._win_h // 2
        avg = sum(self._bar_heights) / max(len(self._bar_heights), 1)
        max_r = min(cx, cy) - 4
        n_rings = len(self._canvas_items)
        for i, ring in enumerate(self._canvas_items):
            phase = (self._frame_count * 0.05 + i * 0.8) % (math.pi * 2)
            pulse = 0.5 + 0.5 * math.sin(phase)
            base_r = max_r * (i + 1) / n_rings
            r = base_r * (0.3 + avg * 0.7) * (0.85 + pulse * 0.15)
            r = max(3, r)
            ratio = r / max_r
            color = _lerp_gradient(ratio, self._gradient)
            alpha_factor = max(0.2, 1.0 - i * 0.15)
            dim = _dim_color(color, alpha_factor) if i > 0 else color
            c.coords(ring, cx - r, cy - r, cx + r, cy + r)
            c.itemconfig(ring, outline=dim, width=max(1, 3 - i * 0.4))
        # Center dot pulses
        dot_r = 3 + avg * 8
        dot_color = _lerp_gradient(min(avg * 2, 1.0), self._gradient)
        c.coords(self._extra_items[0], cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r)
        c.itemconfig(self._extra_items[0], fill=dot_color)

    # ── Style: BLOCKS (LED matrix) ───────────────────────────────────────

    def _init_blocks(self) -> None:
        c = self._canvas
        cols = 16
        rows = 8
        pad = 4
        bw = (self._win_w - pad * 2) / cols
        bh = (self._win_h - pad * 2) / rows
        for row in range(rows):
            for col in range(cols):
                x1 = pad + col * bw + 1
                y1 = pad + row * bh + 1
                x2 = pad + (col + 1) * bw - 1
                y2 = pad + (row + 1) * bh - 1
                block = c.create_rectangle(x1, y1, x2, y2,
                                           fill=TRANSPARENT_COLOR, outline="")
                self._canvas_items.append(block)

    def _draw_blocks(self) -> None:
        c = self._canvas
        if not c:
            return
        cols = 16
        rows = 8
        idx = 0
        for row in range(rows):
            for col in range(cols):
                bar_idx = col * BAR_COUNT // cols
                level = self._bar_heights[bar_idx] if bar_idx < len(self._bar_heights) else 0
                filled_rows = int(level * rows)
                row_from_bottom = rows - 1 - row
                if row_from_bottom < filled_rows:
                    ratio = row_from_bottom / rows
                    color = _lerp_gradient(ratio, self._gradient)
                else:
                    color = TRANSPARENT_COLOR
                c.itemconfig(self._canvas_items[idx], fill=color)
                idx += 1

    # ── Style: LINE (minimal thin line) ──────────────────────────────────

    def _init_line(self) -> None:
        c = self._canvas
        # Single smooth line
        line = c.create_line(0, 0, 0, 0, fill="#00ffaa", width=2, smooth=True,
                             capstyle=tk.ROUND, joinstyle=tk.ROUND)
        # Dots at peaks
        dots: list[int] = []
        for _ in range(BAR_COUNT):
            d = c.create_oval(0, 0, 0, 0, fill="#ffffff", outline="")
            dots.append(d)
        self._canvas_items = [line]
        self._extra_items = dots
        self._dot_peaks = [0.0] * BAR_COUNT

    def _draw_line(self) -> None:
        c = self._canvas
        if not c:
            return
        pad = 6
        bottom = self._win_h - pad
        max_h = self._win_h - pad * 2
        n = BAR_COUNT
        points: list[float] = []
        for i in range(n):
            x = pad + (self._win_w - pad * 2) * i / (n - 1)
            h = self._bar_heights[i] * max_h
            y = bottom - h
            points.extend([x, y])
            # Peak dot — gravity fall
            if h > self._dot_peaks[i]:
                self._dot_peaks[i] = h
                self._dot_velocities[i] = 0
            else:
                self._dot_velocities[i] += 0.4  # gravity
                self._dot_peaks[i] -= self._dot_velocities[i]
                if self._dot_peaks[i] < 0:
                    self._dot_peaks[i] = 0
            peak_y = bottom - self._dot_peaks[i]
            dr = 2
            c.coords(self._extra_items[i], x - dr, peak_y - dr, x + dr, peak_y + dr)
            ratio = self._dot_peaks[i] / max_h if max_h > 0 else 0
            dc = _lerp_gradient(ratio, self._gradient)
            c.itemconfig(self._extra_items[i], fill=dc if self._dot_peaks[i] > 1 else TRANSPARENT_COLOR)

        if len(points) >= 4:
            avg_level = sum(self._bar_heights) / n if n else 0
            color = _lerp_gradient(min(avg_level * 2, 1.0), self._gradient)
            c.coords(self._canvas_items[0], *points)
            c.itemconfig(self._canvas_items[0], fill=color)

    # ── Public API ───────────────────────────────────────────────────────

    def show(self, recorder: "AudioRecorder") -> None:
        """Show the overlay and start visualizing audio."""
        self._recorder = recorder
        self._bar_heights = [0.0] * BAR_COUNT
        self._dot_peaks = [0.0] * BAR_COUNT
        self._dot_velocities = [0.0] * BAR_COUNT
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
