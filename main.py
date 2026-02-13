#!/usr/bin/env python3
"""
Image Upscaler & Enhancer — Desktop GUI Application
=====================================================
Drag-and-drop (or browse) images, folders, and ZIP archives.
Adjust upscale, blur, sharpen, and downscale settings with live preview.
Export all processed images to a destination folder.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas
from PIL import Image, ImageTk, ImageDraw, ImageFont
import os
import queue
import threading
import shutil
from typing import Optional

from processor import (
    ProcessingSettings, ImageInfo, collect_images, process_image,
    format_size, get_output_dimensions, save_image, estimate_output_size,
)

# ---------------------------------------------------------------------------
# Drag-and-drop support (windnd — Windows native)
# ---------------------------------------------------------------------------
try:
    import windnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Accent colours
ACCENT = ("#3B8ED0", "#1F6AA5")
DANGER = ("#D03B3B", "#A51F1F")


def _generate_app_icon() -> Image.Image:
    """Create a 256x256 app icon programmatically."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-rect background gradient (dark blue-gray)
    pad = 16
    r = 48
    # Base rounded rect — dark charcoal
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=r, fill=(30, 34, 42, 255),
    )
    # Inner highlight rect
    draw.rounded_rectangle(
        [pad + 4, pad + 4, size - pad - 4, size - pad - 4],
        radius=r - 4, fill=(38, 44, 56, 255),
    )

    # Upward arrow (representing upscale)
    cx, cy = size // 2, size // 2 - 10
    arrow_color = (59, 142, 208, 255)  # accent blue

    # Arrow shaft
    shaft_w = 18
    draw.rectangle(
        [cx - shaft_w // 2, cy, cx + shaft_w // 2, cy + 70],
        fill=arrow_color,
    )
    # Arrow head (triangle)
    draw.polygon(
        [(cx, cy - 45), (cx - 40, cy + 5), (cx + 40, cy + 5)],
        fill=arrow_color,
    )

    # Small pixel-grid squares at the bottom to hint "image"
    sq = 16
    gap = 4
    start_x = cx - (sq * 3 + gap * 2) // 2
    start_y = cy + 78
    colors = [
        (100, 200, 130, 255), (200, 160, 80, 255), (180, 100, 180, 255),
        (80, 160, 210, 255), (210, 100, 100, 255), (120, 120, 200, 255),
    ]
    for row in range(2):
        for col in range(3):
            x = start_x + col * (sq + gap)
            y = start_y + row * (sq + gap)
            c = colors[row * 3 + col]
            draw.rectangle([x, y, x + sq, y + sq], fill=c)

    return img


# ═══════════════════════════════════════════════════════════════════════════
# Application Window
# ═══════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.title("Image Upscaler & Enhancer")
        self.geometry("1300x850")
        self.minsize(1060, 720)

        # ── app icon ──
        self._set_app_icon()

        # ── state ──
        self.image_infos: list[ImageInfo] = []
        self.settings = ProcessingSettings()
        self.preview_index: int = 0
        self._preview_timer_id: Optional[str] = None
        self._preview_pil: Optional[Image.Image] = None   # processed PIL image
        self._preview_photo = None                         # prevent GC
        self.temp_dirs: list[str] = []
        self.export_cancelled = False
        self._drop_queue: queue.Queue = queue.Queue()  # thread-safe DnD queue

        # Preview pan/zoom state
        self._zoom: float = 1.0
        self._pan_x: float = 0.0
        self._pan_y: float = 0.0
        self._drag_start: Optional[tuple] = None

        # ── build ──
        self._build_ui()
        self._setup_dnd()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ═══════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ═══════════════════════════════════════════════════════════════════

    def _set_app_icon(self):
        """Generate and apply the custom app icon (title bar + taskbar)."""
        try:
            icon = _generate_app_icon()
            # Save a temporary .ico for Windows taskbar
            import tempfile, ctypes
            self._icon_photo = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self._icon_photo)

            # Also set via Windows API so the taskbar icon updates
            ico_path = os.path.join(tempfile.gettempdir(), "imgupscaler_icon.ico")
            # .ico needs multiple sizes
            icon.save(
                ico_path, format="ICO",
                sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
            )
            self.iconbitmap(ico_path)

            # Set AppUserModelID so Windows groups this as its own taskbar entry
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "ImageUpscaler.App.1"
                )
            except Exception:
                pass
        except Exception:
            pass  # graceful fallback — default icon is fine

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=0, minsize=330)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        self._build_left_panel()
        self._build_right_panel()
        self._build_bottom_bar()

    # ── Left panel: inputs ────────────────────────────────────────────

    def _build_left_panel(self):
        left = ctk.CTkFrame(self, corner_radius=0)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 2))
        left.grid_rowconfigure(3, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(
            left, text="  Input Images",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")

        # Browse buttons
        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.grid(row=1, column=0, padx=15, pady=5, sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row, text="Add Files", height=32, command=self._browse_files,
        ).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ctk.CTkButton(
            btn_row, text="Add Folder", height=32, command=self._browse_folder,
        ).grid(row=0, column=1, padx=(4, 0), sticky="ew")

        # Drop zone
        self.drop_frame = ctk.CTkFrame(
            left, height=80, border_width=2,
            border_color=("gray70", "gray30"),
            fg_color=("gray95", "gray17"),
        )
        self.drop_frame.grid(row=2, column=0, padx=15, pady=5, sticky="ew")
        self.drop_frame.grid_propagate(False)

        dnd_text = (
            "Drag & drop files, folders, or ZIPs anywhere"
            if HAS_DND else "Use buttons above to add images"
        )
        self.drop_label = ctk.CTkLabel(
            self.drop_frame, text=dnd_text,
            text_color=("gray50", "gray60"), font=ctk.CTkFont(size=12),
        )
        self.drop_label.place(relx=0.5, rely=0.5, anchor="center")

        # Scrollable file list
        self.file_list_frame = ctk.CTkScrollableFrame(
            left, label_text="Loaded Images (0)",
        )
        self.file_list_frame.grid(row=3, column=0, padx=15, pady=5, sticky="nsew")
        self.file_list_frame.grid_columnconfigure(0, weight=1)

        # Stats
        self.stats_label = ctk.CTkLabel(
            left, text="No images loaded",
            text_color=("gray50", "gray60"), font=ctk.CTkFont(size=12),
        )
        self.stats_label.grid(row=4, column=0, padx=15, pady=(0, 5), sticky="w")

        # Clear
        ctk.CTkButton(
            left, text="Clear All", height=30,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
            command=self._clear_all,
        ).grid(row=5, column=0, padx=15, pady=(0, 15), sticky="ew")

    # ── Right panel: settings + preview ───────────────────────────────

    def _build_right_panel(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self._build_settings(right)
        self._build_preview(right)

    def _build_settings(self, parent):
        sf = ctk.CTkFrame(parent)
        sf.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="ew")
        sf.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            sf, text="  Processing Settings",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, padx=15, pady=(12, 6), sticky="w")

        # (label, attr, from, to, default, step, format, type)
        configs = [
            ("Upscale Factor",    "upscale_factor",    1,    8,    4,    1,    "{}x",    int),
            ("Blur Radius",       "blur_radius",       0.0,  3.0,  0.6,  0.05, "{:.2f}", float),
            ("Sharpen Radius",    "sharpen_radius",    0.0,  5.0,  1.2,  0.1,  "{:.1f}", float),
            ("Sharpen Amount",    "sharpen_amount",    0,    300,  120,  5,    "{}%",    int),
            ("Sharpen Threshold", "sharpen_threshold", 0,    10,   2,    1,    "{}",     int),
            ("Downscale Factor",  "downscale_factor",  0.80, 1.00, 0.97, 0.01, "{:.2f}", float),
        ]

        self._slider_configs = configs
        self._slider_refs: dict = {}
        self._slider_val_labels: dict = {}

        for i, (label, attr, lo, hi, default, step, fmt, vtype) in enumerate(configs, start=1):
            ctk.CTkLabel(sf, text=label, font=ctk.CTkFont(size=13)).grid(
                row=i, column=0, padx=(15, 10), pady=4, sticky="w",
            )

            val_label = ctk.CTkLabel(
                sf, text=fmt.format(default), width=60,
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            val_label.grid(row=i, column=2, padx=(10, 15), pady=4, sticky="e")

            n_steps = max(1, int(round((hi - lo) / step)))
            slider = ctk.CTkSlider(
                sf, from_=lo, to=hi, number_of_steps=n_steps,
                command=lambda v, a=attr, vl=val_label, f=fmt, s=step, t=vtype:
                    self._on_slider_change(v, a, vl, f, s, t),
            )
            slider.set(default)
            slider.grid(row=i, column=1, padx=5, pady=4, sticky="ew")

            self._slider_refs[attr] = slider
            self._slider_val_labels[attr] = (val_label, fmt, vtype)

        # Reset to defaults button
        reset_row = len(configs) + 1
        ctk.CTkButton(
            sf, text="Reset to Defaults", height=28,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
            font=ctk.CTkFont(size=12), command=self._reset_settings,
        ).grid(row=reset_row, column=0, columnspan=3, padx=15, pady=(6, 10), sticky="ew")

    def _build_preview(self, parent):
        pf = ctk.CTkFrame(parent)
        pf.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="nsew")
        pf.grid_rowconfigure(1, weight=1)
        pf.grid_columnconfigure(0, weight=1)

        # Header row
        hdr = ctk.CTkFrame(pf, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=15, pady=(10, 5), sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="  Preview",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.preview_selector = ctk.CTkComboBox(
            hdr, values=["No images loaded"], state="readonly", width=280,
            command=self._on_preview_select,
        )
        self.preview_selector.grid(row=0, column=1, padx=(15, 0), sticky="e")
        self.preview_selector.set("No images loaded")

        # Canvas area — dark bg, supports pan & zoom
        self.preview_canvas = Canvas(
            pf, bg="#1a1a1a", highlightthickness=0, cursor="fleur",
        )
        self.preview_canvas.grid(row=1, column=0, padx=15, pady=5, sticky="nsew")

        # Placeholder text
        self._preview_placeholder_id = self.preview_canvas.create_text(
            0, 0, text="Load images to see a live preview",
            fill="#666666", font=("Segoe UI", 12),
        )

        # Checkerboard-style subtle pattern drawn once on first resize
        self._canvas_bg_drawn = False

        # Bind pan & zoom
        self.preview_canvas.bind("<Configure>", self._on_preview_canvas_resize)
        self.preview_canvas.bind("<MouseWheel>", self._on_zoom)           # Windows
        self.preview_canvas.bind("<Button-4>", self._on_zoom)             # Linux up
        self.preview_canvas.bind("<Button-5>", self._on_zoom)             # Linux down
        self.preview_canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.preview_canvas.bind("<B1-Motion>", self._on_pan_move)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_pan_end)
        self.preview_canvas.bind("<Double-Button-1>", self._on_reset_view)

        # Info row
        info = ctk.CTkFrame(pf, fg_color="transparent")
        info.grid(row=2, column=0, padx=15, pady=(0, 10), sticky="ew")
        info.grid_columnconfigure(1, weight=1)

        self.preview_dims_label = ctk.CTkLabel(
            info, text="", font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
        )
        self.preview_dims_label.grid(row=0, column=0, sticky="w")

        self.preview_size_label = ctk.CTkLabel(
            info, text="", font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray60"),
        )
        self.preview_size_label.grid(row=0, column=1, sticky="e")

    # ── Bottom bar: format, progress, export ──────────────────────────

    def _build_bottom_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")

        # --- left: format / quality ---
        left_sec = ctk.CTkFrame(bar, fg_color="transparent")
        left_sec.pack(side="left", padx=15, pady=12)

        ctk.CTkLabel(left_sec, text="Format:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 5),
        )
        self.format_menu = ctk.CTkComboBox(
            left_sec, values=["PNG", "JPEG", "WEBP"], width=90,
            state="readonly", command=self._on_format_change,
        )
        self.format_menu.set("PNG")
        self.format_menu.pack(side="left")

        # Quality sub-frame (shown only for JPEG / WEBP)
        self.quality_frame = ctk.CTkFrame(left_sec, fg_color="transparent")

        ctk.CTkLabel(self.quality_frame, text="Quality:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(12, 5),
        )
        self.quality_slider = ctk.CTkSlider(
            self.quality_frame, from_=1, to=100, number_of_steps=99,
            width=120, command=self._on_quality_change,
        )
        self.quality_slider.set(95)
        self.quality_slider.pack(side="left")

        self.quality_val_label = ctk.CTkLabel(
            self.quality_frame, text="95", width=30,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.quality_val_label.pack(side="left", padx=(5, 0))

        # --- right: export ---
        self.export_btn = ctk.CTkButton(
            bar, text="Export All", width=140, height=38,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._export,
        )
        self.export_btn.pack(side="right", padx=15, pady=12)

        # --- centre: progress ---
        progress_sec = ctk.CTkFrame(bar, fg_color="transparent")
        progress_sec.pack(side="right", fill="x", expand=True, padx=10, pady=12)

        self.progress_label = ctk.CTkLabel(
            progress_sec, text="Ready", font=ctk.CTkFont(size=12),
        )
        self.progress_label.pack(side="right", padx=(10, 0))

        self.progress_bar = ctk.CTkProgressBar(progress_sec)
        self.progress_bar.pack(side="right", fill="x", expand=True)
        self.progress_bar.set(0)

    # ═══════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════

    def _reset_settings(self):
        """Reset all sliders to their default values."""
        defaults = ProcessingSettings()
        self.settings = defaults

        for (_label, attr, _lo, _hi, default, _step, fmt, vtype) in self._slider_configs:
            self._slider_refs[attr].set(default)
            val_label, _, _ = self._slider_val_labels[attr]
            val_label.configure(text=fmt.format(default))

        # Reset format and quality
        self.format_menu.set("PNG")
        self.settings.output_format = "PNG"
        self.quality_frame.pack_forget()
        self.quality_slider.set(95)
        self.quality_val_label.configure(text="95")
        self.settings.jpeg_quality = 95

        self._schedule_preview_update()

    def _on_slider_change(self, value, attr, val_label, fmt, step, vtype):
        if vtype is int:
            value = int(round(value))
        else:
            value = round(round(value / step) * step, 4)

        val_label.configure(text=fmt.format(value))
        setattr(self.settings, attr, vtype(value))
        self._schedule_preview_update()

    def _on_format_change(self, value):
        self.settings.output_format = value
        if value in ("JPEG", "WEBP"):
            self.quality_frame.pack(side="left")
        else:
            self.quality_frame.pack_forget()
        self._schedule_preview_update()

    def _on_quality_change(self, value):
        val = int(round(value))
        self.quality_val_label.configure(text=str(val))
        self.settings.jpeg_quality = val
        self._schedule_preview_update()

    def _on_preview_select(self, value):
        for i, info in enumerate(self.image_infos):
            if info.filename == value:
                self.preview_index = i
                self._schedule_preview_update()
                break

    def _on_preview_canvas_resize(self, _event=None):
        """Re-center placeholder and re-render preview when canvas resizes."""
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        self.preview_canvas.coords(self._preview_placeholder_id, cw // 2, ch // 2)
        if self._preview_pil is not None:
            self._render_canvas()

    # ── Zoom & Pan ────────────────────────────────────────────────────

    def _on_zoom(self, event):
        if self._preview_pil is None:
            return
        # Determine scroll direction
        if event.num == 5 or event.delta < 0:
            factor = 0.9
        else:
            factor = 1.1
        self._zoom = max(0.1, min(20.0, self._zoom * factor))
        self._render_canvas()

    def _on_pan_start(self, event):
        self._drag_start = (event.x, event.y)

    def _on_pan_move(self, event):
        if self._drag_start is None:
            return
        dx = event.x - self._drag_start[0]
        dy = event.y - self._drag_start[1]
        self._drag_start = (event.x, event.y)
        self._pan_x += dx
        self._pan_y += dy
        if self._preview_pil is not None:
            self._render_canvas()

    def _on_pan_end(self, _event):
        self._drag_start = None

    def _on_reset_view(self, _event=None):
        """Double-click resets zoom and pan to fit."""
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        if self._preview_pil is not None:
            self._render_canvas()

    # ── DnD (windnd — hooks the entire window) ────────────────────────

    def _setup_dnd(self):
        """Register the whole window as a drop target using windnd."""
        if not HAS_DND:
            return
        try:
            windnd.hook_dropfiles(self, func=self._on_drop_files)
            # Poll the thread-safe queue from the main thread
            self._poll_drop_queue()
        except Exception:
            pass  # graceful fallback — browse buttons still work

    def _poll_drop_queue(self):
        """Check for dropped paths from the main thread (safe for tkinter)."""
        try:
            while True:
                paths = self._drop_queue.get_nowait()
                self._add_paths(paths)
        except queue.Empty:
            pass
        # Re-schedule every 150ms
        self.after(150, self._poll_drop_queue)

    def _on_drop_files(self, raw_paths: list):
        """
        Called by windnd from a raw Windows thread.
        MUST NOT touch any tkinter/CTk objects — just push to the queue.
        """
        paths: list[str] = []
        for p in raw_paths:
            if isinstance(p, bytes):
                try:
                    decoded = p.decode('utf-8')
                except UnicodeDecodeError:
                    decoded = p.decode('gbk', errors='replace')
            else:
                decoded = str(p)
            paths.append(decoded)

        self._drop_queue.put(paths)

    # ═══════════════════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ═══════════════════════════════════════════════════════════════════

    def _browse_files(self):
        paths = filedialog.askopenfilenames(
            title="Select Images or ZIP Archives",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp *.gif"),
                ("ZIP archives", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if paths:
            self._add_paths(list(paths))

    def _browse_folder(self):
        path = filedialog.askdirectory(title="Select Folder Containing Images")
        if path:
            self._add_paths([path])

    def _add_paths(self, paths: list[str]):
        self.progress_label.configure(text="Scanning...")
        self.update_idletasks()

        new_paths, temp_dirs = collect_images(paths)
        self.temp_dirs.extend(temp_dirs)

        existing = {info.path for info in self.image_infos}
        added = 0

        for p in new_paths:
            if p in existing:
                continue
            try:
                info = ImageInfo.from_path(p)
                self.image_infos.append(info)
                existing.add(p)
                added += 1
            except Exception:
                continue

        self._refresh_file_list()
        self.progress_label.configure(text=f"Added {added} image(s)")

        if self.image_infos and added > 0:
            self._schedule_preview_update()

    def _clear_all(self):
        self.image_infos.clear()
        self._cleanup_temp_dirs()
        self._refresh_file_list()
        self._preview_pil = None
        self._preview_photo = None
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.preview_canvas.delete("preview")
        self.preview_canvas.itemconfigure(
            self._preview_placeholder_id,
            state="normal", text="Load images to see a live preview",
        )
        self.preview_dims_label.configure(text="")
        self.preview_size_label.configure(text="")
        self.preview_selector.configure(values=["No images loaded"])
        self.preview_selector.set("No images loaded")
        self.preview_index = 0
        self.progress_label.configure(text="Ready")
        self.progress_bar.set(0)

    def _refresh_file_list(self):
        for w in self.file_list_frame.winfo_children():
            w.destroy()

        total_size = 0
        for i, info in enumerate(self.image_infos):
            total_size += info.file_size

            row = ctk.CTkFrame(self.file_list_frame, fg_color="transparent", height=28)
            row.grid(row=i, column=0, sticky="ew", pady=1)
            row.grid_columnconfigure(0, weight=1)

            name = info.filename if len(info.filename) <= 28 else info.filename[:25] + "..."
            ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=12), anchor="w").grid(
                row=0, column=0, sticky="w",
            )
            ctk.CTkLabel(
                row, text=f"{info.width}x{info.height}",
                font=ctk.CTkFont(size=11), text_color=("gray50", "gray55"),
            ).grid(row=0, column=1, padx=5)
            ctk.CTkLabel(
                row, text=format_size(info.file_size),
                font=ctk.CTkFont(size=11), text_color=("gray50", "gray55"),
            ).grid(row=0, column=2, padx=(5, 0))

        count = len(self.image_infos)
        self.file_list_frame.configure(
            label_text=f"Loaded Images ({count})",
        )
        self.stats_label.configure(
            text=(f"{count} images  |  {format_size(total_size)} total"
                  if count else "No images loaded"),
        )

        if self.image_infos:
            names = [info.filename for info in self.image_infos]
            self.preview_selector.configure(values=names)
            if self.preview_index >= count:
                self.preview_index = 0
            self.preview_selector.set(self.image_infos[self.preview_index].filename)

    # ═══════════════════════════════════════════════════════════════════
    # PREVIEW (debounced, threaded)
    # ═══════════════════════════════════════════════════════════════════

    def _schedule_preview_update(self):
        if self._preview_timer_id is not None:
            self.after_cancel(self._preview_timer_id)
        self._preview_timer_id = self.after(200, self._kick_preview)

    def _kick_preview(self):
        self._preview_timer_id = None
        if not self.image_infos:
            return

        idx = min(self.preview_index, len(self.image_infos) - 1)
        info = self.image_infos[idx]
        settings = self.settings.copy()

        self.preview_canvas.itemconfigure(
            self._preview_placeholder_id,
            state="normal", text="Processing preview...",
        )
        threading.Thread(
            target=self._bg_process_preview, args=(info, settings), daemon=True,
        ).start()

    def _bg_process_preview(self, info: ImageInfo, settings: ProcessingSettings):
        try:
            img = Image.open(info.path).convert("RGBA")
            orig_size = img.size

            # Limit intermediate size for snappy preview
            max_dim = 2048
            up_w = img.width * max(1, settings.upscale_factor)
            up_h = img.height * max(1, settings.upscale_factor)

            if up_w > max_dim or up_h > max_dim:
                scale = min(max_dim / up_w, max_dim / up_h)
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )

            processed = process_image(img, settings)
            out_w, out_h = get_output_dimensions(orig_size[0], orig_size[1], settings)
            est = estimate_output_size(processed, settings)

            # Schedule UI update on main thread
            self.after(
                0,
                lambda: self._show_preview(processed, orig_size, (out_w, out_h), est),
            )
        except Exception as exc:
            self.after(0, lambda: self._preview_error(str(exc)))

    def _show_preview(self, pil_img, orig_size, out_size, est_bytes):
        self._preview_pil = pil_img
        self._preview_orig = orig_size
        self._preview_out = out_size
        self._preview_est = est_bytes

        # Reset view on new image
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._render_canvas()

        self.preview_dims_label.configure(
            text=f"Original: {orig_size[0]}x{orig_size[1]}  ->  Output: {out_size[0]}x{out_size[1]}",
        )
        self.preview_size_label.configure(text=f"Est. size: {format_size(est_bytes)}")

    def _render_canvas(self):
        """Render the processed image onto the canvas with current zoom & pan."""
        if self._preview_pil is None:
            return

        cw = max(1, self.preview_canvas.winfo_width())
        ch = max(1, self.preview_canvas.winfo_height())

        # Compute fit-to-canvas base scale
        iw, ih = self._preview_pil.size
        base_scale = min(cw / iw, ch / ih, 1.0)  # don't upscale past 1:1
        scale = base_scale * self._zoom

        disp_w = max(1, int(iw * scale))
        disp_h = max(1, int(ih * scale))

        display = self._preview_pil.resize((disp_w, disp_h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(display)
        self._preview_photo = photo  # prevent GC

        # Position: centred + pan offset
        cx = cw // 2 + int(self._pan_x)
        cy = ch // 2 + int(self._pan_y)

        self.preview_canvas.delete("preview")
        self.preview_canvas.create_image(cx, cy, image=photo, anchor="center", tags="preview")
        self.preview_canvas.itemconfigure(self._preview_placeholder_id, state="hidden")

    def _preview_error(self, msg: str):
        self._preview_pil = None
        self._preview_photo = None
        self.preview_canvas.delete("preview")
        self.preview_canvas.itemconfigure(self._preview_placeholder_id, state="normal")
        self.preview_canvas.itemconfigure(
            self._preview_placeholder_id, text=f"Error: {msg}",
        )

    # ═══════════════════════════════════════════════════════════════════
    # EXPORT
    # ═══════════════════════════════════════════════════════════════════

    def _export(self):
        if not self.image_infos:
            messagebox.showwarning("No Images", "Add images before exporting.")
            return

        dest = filedialog.askdirectory(title="Select Export Destination")
        if not dest:
            return

        output_dir = os.path.join(dest, "upscaled_output")
        os.makedirs(output_dir, exist_ok=True)

        self.export_cancelled = False
        self.export_btn.configure(
            text="Cancel", fg_color=DANGER, command=self._cancel_export,
        )

        threading.Thread(
            target=self._bg_export, args=(output_dir,), daemon=True,
        ).start()

    def _cancel_export(self):
        self.export_cancelled = True

    def _bg_export(self, output_dir: str):
        total = len(self.image_infos)
        settings = self.settings.copy()

        ext_map = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
        out_ext = ext_map.get(settings.output_format, ".png")

        ok = 0
        fail = 0
        used_names: set[str] = set()

        for i, info in enumerate(self.image_infos):
            if self.export_cancelled:
                self.after(0, lambda s=ok, f=fail: self._export_done(s, f, cancelled=True))
                return

            self.after(0, lambda c=i, t=total: self._export_progress(c, t))

            try:
                img = Image.open(info.path).convert("RGBA")
                processed = process_image(img, settings)

                base = os.path.splitext(info.filename)[0]
                out_name = base + out_ext
                n = 1
                while out_name in used_names:
                    out_name = f"{base}_{n}{out_ext}"
                    n += 1
                used_names.add(out_name)

                save_image(processed, os.path.join(output_dir, out_name), settings)
                ok += 1
            except Exception:
                fail += 1

        self.after(0, lambda c=total, t=total: self._export_progress(c, t))
        self.after(0, lambda s=ok, f=fail: self._export_done(s, f))

    def _export_progress(self, current: int, total: int):
        self.progress_bar.set(current / total if total else 0)
        self.progress_label.configure(text=f"Exporting {current + 1}/{total}...")

    def _export_done(self, succeeded: int, failed: int, cancelled=False):
        self.export_btn.configure(
            text="Export All", fg_color=ACCENT, command=self._export,
        )
        self.progress_bar.set(1.0 if not cancelled else self.progress_bar.get())

        if cancelled:
            self.progress_label.configure(text=f"Cancelled ({succeeded} saved)")
            messagebox.showinfo(
                "Export Cancelled",
                f"Export cancelled.\n{succeeded} image(s) were saved.",
            )
        elif failed:
            self.progress_label.configure(text=f"Done ({failed} failed)")
            messagebox.showwarning(
                "Export Complete",
                f"Exported {succeeded} image(s).\n{failed} image(s) failed.",
            )
        else:
            self.progress_label.configure(text=f"Done! {succeeded} exported")
            messagebox.showinfo(
                "Export Complete",
                f"Successfully exported {succeeded} image(s)!",
            )

    # ═══════════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════════

    def _cleanup_temp_dirs(self):
        for d in self.temp_dirs:
            shutil.rmtree(d, ignore_errors=True)
        self.temp_dirs.clear()

    def _on_close(self):
        self._cleanup_temp_dirs()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()
