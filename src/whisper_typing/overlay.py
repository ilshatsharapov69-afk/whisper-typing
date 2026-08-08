"""Floating audio visualizer overlay for whisper-typing."""

from __future__ import annotations

import contextlib
import logging
import math
import threading
import tkinter as tk
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageTk

if TYPE_CHECKING:
    from whisper_typing.audio_capture import AudioRecorder

# Layout
BAR_COUNT = 20
BOTTOM_MARGIN = 60
TRANSPARENT_COLOR = "#010101"
PROCESSING_SIZE = 48
PROCESSING_ITEM_COUNT = 1
PROCESSING_FRAME_COUNT = 30
PROCESSING_FRAME_MS = 33
PROCESSING_RENDER_SCALE = 4
VISUALIZER_FRAME_MS = 33
VISUALIZER_ANALYSIS_INTERVAL_FRAMES = 2
VISUALIZER_SAMPLE_COUNT = 2048
VISUALIZER_ATTACK = 0.4
VISUALIZER_RELEASE = 0.17
MIN_DRAW_POINTS = 4
MIN_FFT_SAMPLES = 256
MAX_FFT_SAMPLES = 4096
MIN_SPECTRUM_PEAK = 1e-12
MODE_RECORDING = "recording"
MODE_PROCESSING = "processing"


def _mix_rgb(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    ratio: float,
) -> tuple[int, int, int]:
    """Blend two RGB colors."""
    return tuple(
        round(first + (second - first) * ratio)
        for first, second in zip(start, end, strict=True)
    )


def _processing_pil_frames() -> list[Image.Image]:
    """Render a small transparent blue spinner with a gradient tail."""
    scale = PROCESSING_RENDER_SCALE
    size = PROCESSING_SIZE * scale
    center = size / 2
    ring_radius = 15.2 * scale
    ring_width = round(4.0 * scale)
    ring_bounds = (
        center - ring_radius,
        center - ring_radius,
        center + ring_radius,
        center + ring_radius,
    )

    # Build one clean tail and rotate it. There is intentionally no badge,
    # background disc, inner arc, or centre dot: only the spinner is visible.
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    crisp = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    crisp_draw = ImageDraw.Draw(crisp)
    segment_count = 64
    tail_span = 272.0
    segment_step = tail_span / segment_count
    head_phase = -90.0
    for segment in range(segment_count):
        ratio = (segment + 1) / segment_count
        angle = head_phase - tail_span + segment * segment_step
        end = angle + segment_step + 0.8
        color = _mix_rgb((30, 94, 238), (119, 225, 255), ratio)
        alpha = round(10 + 245 * ratio**2.05)
        glow_draw.arc(
            ring_bounds,
            start=angle,
            end=end,
            fill=(*color, round(alpha * 0.58)),
            width=ring_width + round(2.2 * scale),
        )
        crisp_draw.arc(
            ring_bounds,
            start=angle,
            end=end,
            fill=(*color, alpha),
            width=ring_width,
        )
    trail = glow.filter(ImageFilter.GaussianBlur(2.5 * scale))
    trail.alpha_composite(crisp)
    head_x = center + ring_radius * math.cos(math.radians(head_phase))
    head_y = center + ring_radius * math.sin(math.radians(head_phase))
    head_radius = ring_width * 0.54
    trail_draw = ImageDraw.Draw(trail)
    trail_draw.ellipse(
        (
            head_x - head_radius,
            head_y - head_radius,
            head_x + head_radius,
            head_y + head_radius,
        ),
        fill=(215, 247, 255, 255),
    )

    frames: list[Image.Image] = []
    for frame_index in range(PROCESSING_FRAME_COUNT):
        rotation = frame_index * 360.0 / PROCESSING_FRAME_COUNT
        image = trail.rotate(
            -rotation,
            resample=Image.Resampling.BICUBIC,
            center=(center, center),
        )
        frames.append(
            image.resize(
                (PROCESSING_SIZE, PROCESSING_SIZE),
                Image.Resampling.LANCZOS,
            )
        )

    return frames

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


def _lerp_gradient(
    ratio: float,
    gradient: list[tuple[float, tuple[int, int, int]]],
) -> str:
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
        self._recorder: AudioRecorder | None = None
        self._bar_heights: list[float] = [0.0] * BAR_COUNT
        self._target_bar_heights: list[float] = [0.0] * BAR_COUNT
        self._style: str = "bars"
        self._gradient_name: str = DEFAULT_GRADIENT
        self._gradient: list[tuple[float, tuple[int, int, int]]] = _GRADIENT_GREEN_RED
        self._canvas_items: list[Any] = []
        self._extra_items: list[Any] = []
        self._frame_count: int = 0
        self._processing: bool = False
        self._pending_mode: str | None = None
        self._last_render_error: str | None = None
        self._processing_frames: list[ImageTk.PhotoImage] = []
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
        if self._processing:
            return (PROCESSING_SIZE, PROCESSING_SIZE)
        bar_w, bar_gap, pad = 4, 2, 6
        default_w = BAR_COUNT * (bar_w + bar_gap) - bar_gap + pad * 2
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
        self._root.overrideredirect(True)  # noqa: FBT003
        self._root.attributes("-topmost", True)  # noqa: FBT003
        self._root.configure(bg=TRANSPARENT_COLOR)
        self._root.attributes("-transparentcolor", TRANSPARENT_COLOR)

        self._prepare_processing_frames()
        self._rebuild_canvas()

        pending = self._pending_mode
        if pending is None:
            self._root.withdraw()
            self._visible = False
        else:
            self._switch_mode(pending)
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

        # Pre-create canvas items for the current mode/style.
        if self._processing:
            self._init_processing()
        elif self._style == "bars":
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
        try:
            if self._visible:
                if self._processing:
                    self._draw_processing()
                elif self._recorder:
                    if self._frame_count % VISUALIZER_ANALYSIS_INTERVAL_FRAMES == 0:
                        self._sample_audio()
                    self._animate_levels()
                    self._draw()
                else:
                    for i in range(BAR_COUNT):
                        self._bar_heights[i] *= 0.85
                    self._draw()
                self._frame_count += 1
            self._last_render_error = None
        except Exception as exc:
            # A Tk callback exception used to kill the only animation loop.
            # Log a changed failure once, rebuild, and keep scheduling frames.
            message = f"{type(exc).__name__}: {exc}"
            if message != self._last_render_error:
                logging.getLogger("whisper_typing").exception(
                    "Overlay render recovered: %s",
                    message,
                )
                self._last_render_error = message
            with contextlib.suppress(Exception):
                self._rebuild_canvas()
        finally:
            if self._running and self._root:
                frame_ms = (
                    PROCESSING_FRAME_MS if self._processing else VISUALIZER_FRAME_MS
                )
                self._root.after(frame_ms, self._update_loop)

    def _prepare_processing_frames(self) -> None:
        """Create Tk images once so showing the spinner is instantaneous."""
        if self._processing_frames or not self._root:
            return
        self._processing_frames = [
            ImageTk.PhotoImage(frame, master=self._root)
            for frame in _processing_pil_frames()
        ]

    def _init_processing(self) -> None:
        """Create the anti-aliased processing animation canvas item."""
        c = self._canvas
        if not c:
            return
        self._prepare_processing_frames()
        if not self._processing_frames:
            return
        spinner = c.create_image(
            self._win_w / 2,
            self._win_h / 2,
            image=self._processing_frames[0],
        )
        self._canvas_items = [spinner]

    def _draw_processing(self) -> None:
        """Advance the lightweight pre-rendered blue spinner."""
        c = self._canvas
        if (
            not c
            or len(self._canvas_items) < PROCESSING_ITEM_COUNT
            or not self._processing_frames
        ):
            return
        frame = self._processing_frames[
            self._frame_count % len(self._processing_frames)
        ]
        c.itemconfig(
            self._canvas_items[0],
            image=frame,
        )

    def _sample_audio(self) -> None:
        """Sample audio into target levels at a deliberately low cadence."""
        if not self._recorder:
            return
        audio = self._recorder.get_recent_data(max_samples=VISUALIZER_SAMPLE_COUNT)
        if audio is not None and len(audio) > 0:
            self._target_bar_heights = self._spectrum_levels(
                audio,
                self._recorder.sample_rate,
            )
        else:
            self._target_bar_heights = [0.0] * BAR_COUNT

    def _animate_levels(self) -> None:
        """Cheaply interpolate bars between the less frequent FFT samples."""
        for i, target in enumerate(self._target_bar_heights):
            current = self._bar_heights[i]
            blend = VISUALIZER_ATTACK if target > current else VISUALIZER_RELEASE
            self._bar_heights[i] += (target - current) * blend

    @staticmethod
    def _spectrum_levels(audio: np.ndarray, sample_rate: int) -> list[float]:
        """Convert recent microphone audio into responsive frequency bars."""
        sample_count = min(len(audio), MAX_FFT_SAMPLES)
        if sample_count < MIN_FFT_SAMPLES:
            return [0.0] * BAR_COUNT

        samples = np.asarray(audio[-sample_count:], dtype=np.float64)
        samples -= float(np.mean(samples))
        rms = float(np.sqrt(np.mean(samples**2)))
        dbfs = 20.0 * math.log10(rms + 1e-9)
        overall = float(np.clip((dbfs + 55.0) / 30.0, 0.0, 1.0))
        if overall <= 0:
            return [0.0] * BAR_COUNT

        spectrum = np.abs(np.fft.rfft(samples * np.hanning(sample_count)))
        max_frequency = min(sample_rate / 2 * 0.95, 7600.0)
        edges = np.geomspace(70.0, max_frequency, BAR_COUNT + 1)
        edge_bins = np.clip(
            np.ceil(edges * sample_count / sample_rate).astype(np.intp),
            0,
            len(spectrum),
        )
        energies = np.zeros(BAR_COUNT, dtype=np.float64)
        for index in range(BAR_COUNT):
            band = spectrum[edge_bins[index] : edge_bins[index + 1]]
            if band.size:
                energies[index] = float(np.sqrt(np.mean(band**2)))

        peak = float(np.max(energies))
        if peak <= MIN_SPECTRUM_PEAK:
            return [0.0] * BAR_COUNT
        shape = np.sqrt(np.clip(energies / peak, 0.0, 1.0))
        levels = overall * (0.18 + 0.82 * shape)
        return [float(level) for level in levels]

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
        c = self._canvas
        bottom = self._win_h - pad
        # One item per band keeps the decorative overlay very inexpensive.
        for i in range(BAR_COUNT):
            bx = pad + i * (bar_w + bar_gap)
            bar = c.create_rectangle(bx, bottom, bx + bar_w, bottom,
                                     fill=TRANSPARENT_COLOR, outline="")
            self._canvas_items.append(bar)

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
            bar = self._canvas_items[i]
            c.coords(bar, bx, top, bx + bar_w, bottom)
            c.itemconfig(bar, fill=color)

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
        if len(points) < MIN_DRAW_POINTS:
            return
        color = _lerp_gradient(
            max(self._bar_heights) if self._bar_heights else 0,
            self._gradient,
        )
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
                level = (
                    self._bar_heights[bar_idx]
                    if bar_idx < len(self._bar_heights)
                    else 0
                )
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
                self._dot_peaks[i] = max(self._dot_peaks[i], 0)
            peak_y = bottom - self._dot_peaks[i]
            dr = 2
            c.coords(self._extra_items[i], x - dr, peak_y - dr, x + dr, peak_y + dr)
            ratio = self._dot_peaks[i] / max_h if max_h > 0 else 0
            dc = _lerp_gradient(ratio, self._gradient)
            c.itemconfig(
                self._extra_items[i],
                fill=dc if self._dot_peaks[i] > 1 else TRANSPARENT_COLOR,
            )

        if len(points) >= MIN_DRAW_POINTS:
            avg_level = sum(self._bar_heights) / n if n else 0
            color = _lerp_gradient(min(avg_level * 2, 1.0), self._gradient)
            c.coords(self._canvas_items[0], *points)
            c.itemconfig(self._canvas_items[0], fill=color)

    # ── Public API ───────────────────────────────────────────────────────

    def show(self, recorder: AudioRecorder) -> None:
        """Show the overlay and start visualizing audio."""
        self._recorder = recorder
        self._pending_mode = MODE_RECORDING
        self._bar_heights = [0.0] * BAR_COUNT
        self._target_bar_heights = [0.0] * BAR_COUNT
        self._dot_peaks = [0.0] * BAR_COUNT
        self._dot_velocities = [0.0] * BAR_COUNT
        if self._root:
            self._root.after(0, self._switch_mode, MODE_RECORDING)

    def _switch_mode(self, mode: str) -> None:
        """Atomically switch canvas and mode inside the Tk event thread."""
        self._processing = mode == MODE_PROCESSING
        self._pending_mode = mode
        self._rebuild_canvas()
        self._do_show()

    def _do_show(self) -> None:
        if self._root:
            self._root.deiconify()
            self._visible = True

    def show_processing(self) -> None:
        """Replace the recording visualizer with a blue loading spinner."""
        self._recorder = None
        self._pending_mode = MODE_PROCESSING
        if self._root:
            self._root.after(0, self._switch_mode, MODE_PROCESSING)

    def hide(self) -> None:
        """Hide the overlay."""
        self._recorder = None
        self._pending_mode = None
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
            with contextlib.suppress(Exception):
                self._root.after(0, self._root.destroy)
