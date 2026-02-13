#!/usr/bin/env python3
"""
Image Upscaler & Enhancer — Desktop GUI Application
=====================================================
Drag-and-drop (or browse) images, folders, and ZIP archives.
Adjust upscale, blur, sharpen, and downscale settings with live preview.
Export all processed images to a destination folder.
"""

import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas, ttk
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter, ImageEnhance
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

# Quality presets — upscale mode
PRESETS = {
    "Low":    ProcessingSettings(mode="upscale", upscale_factor=2, blur_radius=0.3, sharpen_radius=0.8,
                                 sharpen_amount=60,  sharpen_threshold=3, downscale_factor=1.00,
                                 edge_trim=0, contrast=1.0, saturation=1.0, brightness=1.0, noise_reduction=0),
    "Medium": ProcessingSettings(mode="upscale", upscale_factor=4, blur_radius=0.6, sharpen_radius=1.2,
                                 sharpen_amount=120, sharpen_threshold=2, downscale_factor=0.97,
                                 edge_trim=0, contrast=1.05, saturation=1.05, brightness=1.0, noise_reduction=0),
    "High":   ProcessingSettings(mode="upscale", upscale_factor=4, blur_radius=0.4, sharpen_radius=1.5,
                                 sharpen_amount=180, sharpen_threshold=1, downscale_factor=0.98,
                                 edge_trim=0, contrast=1.1, saturation=1.1, brightness=1.0, noise_reduction=1),
    "Ultra":  ProcessingSettings(mode="upscale", upscale_factor=8, blur_radius=0.5, sharpen_radius=2.0,
                                 sharpen_amount=220, sharpen_threshold=1, downscale_factor=0.97,
                                 edge_trim=0, contrast=1.15, saturation=1.15, brightness=1.0, noise_reduction=1),
}

# Quality presets — downscale mode
DOWNSCALE_PRESETS = {
    "Light":  ProcessingSettings(mode="downscale", downscale_target=0.75, downscale_blur=0.2,
                                 downscale_sharpen=40, contrast=1.0, saturation=1.0, brightness=1.0,
                                 noise_reduction=0, edge_trim=0),
    "Half":   ProcessingSettings(mode="downscale", downscale_target=0.50, downscale_blur=0.3,
                                 downscale_sharpen=60, contrast=1.02, saturation=1.02, brightness=1.0,
                                 noise_reduction=0, edge_trim=0),
    "Quarter":ProcessingSettings(mode="downscale", downscale_target=0.25, downscale_blur=0.5,
                                 downscale_sharpen=80, contrast=1.05, saturation=1.05, brightness=1.0,
                                 noise_reduction=1, edge_trim=0),
    "Tiny":   ProcessingSettings(mode="downscale", downscale_target=0.10, downscale_blur=0.8,
                                 downscale_sharpen=100, contrast=1.1, saturation=1.1, brightness=1.0,
                                 noise_reduction=1, edge_trim=0),
}


def _generate_app_icon() -> Image.Image:
    """Create a 256x256 blue-square app icon programmatically."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Solid blue rounded-square background
    pad = 12
    r = 44
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=r, fill=(41, 121, 204, 255),   # nice medium blue
    )
    # Subtle lighter inner highlight
    draw.rounded_rectangle(
        [pad + 3, pad + 3, size - pad - 3, size - pad - 3],
        radius=r - 3, fill=(50, 132, 217, 255),
    )

    # White upward arrow (representing upscale)
    cx, cy = size // 2, size // 2 - 6
    white = (255, 255, 255, 255)

    # Arrow shaft
    shaft_w = 22
    draw.rectangle(
        [cx - shaft_w // 2, cy + 2, cx + shaft_w // 2, cy + 72],
        fill=white,
    )
    # Arrow head (triangle)
    draw.polygon(
        [(cx, cy - 48), (cx - 44, cy + 8), (cx + 44, cy + 8)],
        fill=white,
    )

    # Small pixel-grid at the bottom — white with slight transparency
    sq = 14
    gap = 5
    start_x = cx - (sq * 3 + gap * 2) // 2
    start_y = cy + 82
    grid_fill = (255, 255, 255, 180)
    for row in range(2):
        for col in range(3):
            x = start_x + col * (sq + gap)
            y = start_y + row * (sq + gap)
            draw.rectangle([x, y, x + sq, y + sq], fill=grid_fill)

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
        self._custom_settings = self.settings.copy()  # remember user's custom values
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

        # Loading overlay state
        self._loading_blur_photo = None
        self._loading_overlay_active = False

        # ── build ──
        self._build_ui()
        self._setup_dnd()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Set initial sash positions after the window has rendered
        self.after(100, self._set_initial_sash_positions)

    def _set_initial_sash_positions(self):
        """Place sashes so left panel is 330px and settings gets ~55% of vertical space."""
        self.update_idletasks()
        try:
            self._h_pane.sashpos(0, 330)
        except Exception:
            pass
        try:
            h = self._v_pane.winfo_height()
            if h > 10:
                self._v_pane.sashpos(0, max(220, int(h * 0.55)))
            else:
                # Window not mapped yet, retry
                self.after(200, self._set_initial_sash_positions)
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    # UI CONSTRUCTION
    # ═══════════════════════════════════════════════════════════════════

    def _set_app_icon(self):
        """Generate and apply the custom app icon (title bar + taskbar)."""
        try:
            icon = _generate_app_icon()
            import ctypes

            # Save .ico — use PyInstaller's temp dir if bundled, else script dir
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(__file__))
            ico_path = os.path.join(base_dir, "icon.ico")
            if not os.path.exists(ico_path):
                icon.save(
                    ico_path, format="ICO",
                    sizes=[(256, 256), (48, 48), (32, 32), (16, 16)],
                )

            # Set the icon on the window title-bar
            self._icon_photo = ImageTk.PhotoImage(icon)
            self.iconphoto(True, self._icon_photo)

            # Also set via .ico so Windows taskbar picks it up
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
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # Style for ttk PanedWindows
        style = ttk.Style(self)
        style.configure("Dark.TPanedwindow", background="#2b2b2b")
        # Make the sash handle easier to grab
        style.configure("Sash", sashthickness=6, handlesize=10)

        # Horizontal PanedWindow: left panel | right panel
        self._h_pane = ttk.PanedWindow(
            self, orient="horizontal", style="Dark.TPanedwindow",
        )
        self._h_pane.grid(row=0, column=0, sticky="nsew")

        self._build_left_panel(self._h_pane)
        self._build_right_panel(self._h_pane)
        self._build_bottom_bar()

    # ── Left panel: inputs ────────────────────────────────────────────

    def _build_left_panel(self, pane):
        left = ctk.CTkFrame(pane, corner_radius=0)
        pane.add(left, weight=0)
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

    def _build_right_panel(self, pane):
        right = ctk.CTkFrame(pane, corner_radius=0, fg_color="transparent")
        pane.add(right, weight=1)
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Vertical PanedWindow: settings (top) | preview (bottom)
        self._v_pane = ttk.PanedWindow(
            right, orient="vertical", style="Dark.TPanedwindow",
        )
        self._v_pane.grid(row=0, column=0, sticky="nsew")

        self._build_settings(self._v_pane)
        self._build_preview(self._v_pane)

    def _build_settings(self, parent):
        # Outer wrapper so the PanedWindow can manage it
        settings_wrapper = ctk.CTkFrame(parent, corner_radius=0)
        settings_wrapper.configure(height=350)
        settings_wrapper.grid_propagate(True)
        parent.add(settings_wrapper, weight=1)
        settings_wrapper.grid_rowconfigure(0, weight=1)
        settings_wrapper.grid_columnconfigure(0, weight=1)

        # Tabview: Upscale | Downscale
        self._settings_tabview = ctk.CTkTabview(settings_wrapper, height=300)
        self._settings_tabview.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        up_tab = self._settings_tabview.add("Upscale")
        dn_tab = self._settings_tabview.add("Downscale")
        self._settings_tabview.set("Upscale")
        self._settings_tabview.configure(command=self._on_tab_change)

        # ── Upscale tab ──────────────────────────────────────────────
        up_sf = ctk.CTkScrollableFrame(up_tab, fg_color="transparent")
        up_sf.pack(fill="both", expand=True)
        up_sf.grid_columnconfigure(1, weight=1)

        # Preset selector
        preset_row = ctk.CTkFrame(up_sf, fg_color="transparent")
        preset_row.grid(row=0, column=0, columnspan=4, padx=10, pady=(2, 6), sticky="ew")
        ctk.CTkLabel(preset_row, text="Preset:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8),
        )
        self.preset_menu = ctk.CTkComboBox(
            preset_row, values=["Custom", "Low", "Medium", "High", "Ultra"],
            width=120, state="readonly", command=self._on_preset_change,
        )
        self.preset_menu.set("Custom")
        self.preset_menu.pack(side="left")

        # Upscale-specific sliders
        upscale_configs = [
            ("Upscale Factor",    "upscale_factor",    1,    8,    4,    1,    "{}x",    int),
            ("Blur Radius",       "blur_radius",       0.0,  3.0,  0.6,  0.05, "{:.2f}", float),
            ("Sharpen Radius",    "sharpen_radius",    0.0,  5.0,  1.2,  0.1,  "{:.1f}", float),
            ("Sharpen Amount",    "sharpen_amount",    0,    300,  120,  5,    "{}%",    int),
            ("Sharpen Threshold", "sharpen_threshold", 0,    10,   2,    1,    "{}",     int),
            ("Downscale Factor",  "downscale_factor",  0.80, 1.00, 0.97, 0.01, "{:.2f}", float),
            ("Contrast",          "contrast",          0.50, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Saturation",        "saturation",        0.00, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Brightness",        "brightness",        0.50, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Noise Reduction",   "noise_reduction",   0,    5,    0,    1,    "{}",     int),
            ("Edge Trim (px)",    "edge_trim",         0,    50,   0,    1,    "{}px",   int),
        ]

        # ── Downscale tab ────────────────────────────────────────────
        dn_sf = ctk.CTkScrollableFrame(dn_tab, fg_color="transparent")
        dn_sf.pack(fill="both", expand=True)
        dn_sf.grid_columnconfigure(1, weight=1)

        # Preset selector for downscale
        dn_preset_row = ctk.CTkFrame(dn_sf, fg_color="transparent")
        dn_preset_row.grid(row=0, column=0, columnspan=4, padx=10, pady=(2, 6), sticky="ew")
        ctk.CTkLabel(dn_preset_row, text="Preset:", font=ctk.CTkFont(size=13)).pack(
            side="left", padx=(0, 8),
        )
        self.dn_preset_menu = ctk.CTkComboBox(
            dn_preset_row, values=["Custom", "Light", "Half", "Quarter", "Tiny"],
            width=120, state="readonly", command=self._on_dn_preset_change,
        )
        self.dn_preset_menu.set("Custom")
        self.dn_preset_menu.pack(side="left")

        # Downscale-specific sliders
        downscale_configs = [
            ("Scale To",          "downscale_target",  0.10, 1.00, 0.50, 0.05, "{:.0%}", float),
            ("Pre-Blur",          "downscale_blur",    0.0,  3.0,  0.3,  0.05, "{:.2f}", float),
            ("Sharpen Amount",    "downscale_sharpen", 0,    300,  60,   5,    "{}%",    int),
            ("Contrast",          "contrast",          0.50, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Saturation",        "saturation",        0.00, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Brightness",        "brightness",        0.50, 2.00, 1.0,  0.05, "{:.2f}", float),
            ("Noise Reduction",   "noise_reduction",   0,    5,    0,    1,    "{}",     int),
            ("Edge Trim (px)",    "edge_trim",         0,    50,   0,    1,    "{}px",   int),
        ]

        # Build all sliders for both tabs
        all_configs = upscale_configs + downscale_configs
        self._slider_configs = all_configs  # used by _apply_settings_to_ui
        self._upscale_configs = upscale_configs
        self._downscale_configs = downscale_configs
        self._slider_refs: dict = {}
        self._slider_val_labels: dict = {}

        self._populate_sliders(up_sf, upscale_configs, start_row=1)
        self._populate_sliders(dn_sf, downscale_configs, start_row=1)

        # Reset buttons
        reset_row_up = len(upscale_configs) + 1
        ctk.CTkButton(
            up_sf, text="Reset to Defaults", height=26,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
            font=ctk.CTkFont(size=12), command=self._reset_settings,
        ).grid(row=reset_row_up, column=0, columnspan=4, padx=10, pady=(4, 6), sticky="ew")

        reset_row_dn = len(downscale_configs) + 1
        ctk.CTkButton(
            dn_sf, text="Reset to Defaults", height=26,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
            font=ctk.CTkFont(size=12), command=self._reset_settings,
        ).grid(row=reset_row_dn, column=0, columnspan=4, padx=10, pady=(4, 6), sticky="ew")

    def _populate_sliders(self, parent_frame, configs, start_row=1):
        """Create slider rows inside a scrollable frame."""
        for i, (label, attr, lo, hi, default, step, fmt, vtype) in enumerate(configs, start=start_row):
            ctk.CTkLabel(parent_frame, text=label, font=ctk.CTkFont(size=12)).grid(
                row=i, column=0, padx=(10, 6), pady=2, sticky="w",
            )

            val_label = ctk.CTkLabel(
                parent_frame, text=fmt.format(default), width=50,
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            val_label.grid(row=i, column=2, padx=(2, 0), pady=2, sticky="e")

            n_steps = max(1, int(round((hi - lo) / step)))
            slider = ctk.CTkSlider(
                parent_frame, from_=lo, to=hi, number_of_steps=n_steps, height=14,
                command=lambda v, a=attr, vl=val_label, f=fmt, s=step, t=vtype:
                    self._on_slider_change(v, a, vl, f, s, t),
            )
            slider.set(default)
            slider.grid(row=i, column=1, padx=4, pady=2, sticky="ew")

            # +/- buttons
            btn_frame = ctk.CTkFrame(parent_frame, fg_color="transparent")
            btn_frame.grid(row=i, column=3, padx=(2, 6), pady=2, sticky="e")

            ctk.CTkButton(
                btn_frame, text="\u2212", width=22, height=22,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
                corner_radius=4,
                command=lambda a=attr, s=step, l=lo, h=hi: self._step_slider(a, -s, l, h),
            ).pack(side="left", padx=(0, 2))

            ctk.CTkButton(
                btn_frame, text="+", width=22, height=22,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"),
                corner_radius=4,
                command=lambda a=attr, s=step, l=lo, h=hi: self._step_slider(a, s, l, h),
            ).pack(side="left")

            # For shared attrs (contrast, etc.) that appear in both tabs,
            # the second tab's slider will overwrite the ref — that's fine,
            # _apply_settings_to_ui updates both via _all_slider_widgets.
            if attr not in self._slider_refs:
                self._slider_refs[attr] = []
                self._slider_val_labels[attr] = []
            self._slider_refs[attr].append(slider)
            self._slider_val_labels[attr].append((val_label, fmt, vtype))

    def _build_preview(self, parent):
        pf = ctk.CTkFrame(parent, corner_radius=0)
        parent.add(pf, weight=1)
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

        # Checkerboard background tile (generated once, tiled on resize)
        self._checker_tile = self._make_checker_tile()
        self._checker_photo = None  # tiled PhotoImage
        self._checker_id = None     # canvas item id

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
        bar.grid(row=1, column=0, sticky="ew")

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
    # CHECKERBOARD BACKGROUND
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def _make_checker_tile(tile_size: int = 16) -> Image.Image:
        """Create a small 2x2-square checkerboard tile (dark grays)."""
        s = tile_size
        tile = Image.new("RGB", (s * 2, s * 2))
        dark = (26, 26, 26)    # #1a1a1a
        light = (38, 38, 38)   # #262626
        draw = ImageDraw.Draw(tile)
        draw.rectangle([0, 0, s - 1, s - 1], fill=dark)
        draw.rectangle([s, 0, s * 2 - 1, s - 1], fill=light)
        draw.rectangle([0, s, s - 1, s * 2 - 1], fill=light)
        draw.rectangle([s, s, s * 2 - 1, s * 2 - 1], fill=dark)
        return tile

    def _draw_checkerboard(self, cw: int, ch: int):
        """Tile a zoom-scaled checkerboard across the entire canvas, offset by pan."""
        base_tile = 16
        s = max(2, int(base_tile * self._zoom))
        dark = (26, 26, 26)
        light = (38, 38, 38)

        # Compute pan offset so the checkerboard moves with the image
        ox = int(self._pan_x) % (s * 2)
        oy = int(self._pan_y) % (s * 2)

        bg = Image.new("RGB", (cw, ch), dark)
        draw = ImageDraw.Draw(bg)
        for ty in range(-s * 2 + oy, ch, s):
            for tx in range(-s * 2 + ox, cw, s):
                # Use the offset-adjusted index for the checker pattern
                col_idx = (tx - ox) // s
                row_idx = (ty - oy) // s
                if (col_idx + row_idx) % 2 == 1:
                    x0 = max(0, tx)
                    y0 = max(0, ty)
                    x1 = min(tx + s - 1, cw - 1)
                    y1 = min(ty + s - 1, ch - 1)
                    if x1 >= x0 and y1 >= y0:
                        draw.rectangle([x0, y0, x1, y1], fill=light)
        self._checker_photo = ImageTk.PhotoImage(bg)
        self.preview_canvas.delete("checker")
        self._checker_id = self.preview_canvas.create_image(
            0, 0, image=self._checker_photo, anchor="nw", tags="checker",
        )
        self.preview_canvas.tag_lower("checker")

    def _composite_checkerboard(self, display: Image.Image) -> Image.Image:
        """
        Composite a zoom-scaled checkerboard behind an RGBA image so that
        only truly transparent pixels reveal the pattern.  Returns an RGB image.
        """
        w, h = display.size
        base_tile_size = 16
        scaled_tile = max(2, int(base_tile_size * self._zoom))

        dark = (30, 30, 30)
        light = (50, 50, 50)
        bg = Image.new("RGB", (w, h), dark)
        draw = ImageDraw.Draw(bg)
        for ty in range(0, h, scaled_tile):
            for tx in range(0, w, scaled_tile):
                if (tx // scaled_tile + ty // scaled_tile) % 2 == 1:
                    draw.rectangle(
                        [tx, ty,
                         min(tx + scaled_tile - 1, w - 1),
                         min(ty + scaled_tile - 1, h - 1)],
                        fill=light,
                    )
        bg.paste(display, (0, 0), display)  # alpha-composite
        return bg

    # ═══════════════════════════════════════════════════════════════════
    # EVENT HANDLERS
    # ═══════════════════════════════════════════════════════════════════

    def _on_tab_change(self):
        """Called when the user switches between Upscale / Downscale tabs."""
        tab = self._settings_tabview.get()
        self.settings.mode = "downscale" if tab == "Downscale" else "upscale"
        self._schedule_preview_update()

    def _on_dn_preset_change(self, value):
        """Apply a downscale preset or restore saved custom values."""
        if value == "Custom":
            self.settings = self._custom_settings.copy()
            self._apply_settings_to_ui(self.settings)
            self._schedule_preview_update()
            return
        if value not in DOWNSCALE_PRESETS:
            return
        self._custom_settings = self.settings.copy()
        preset = DOWNSCALE_PRESETS[value].copy()
        self.settings = preset
        self._apply_settings_to_ui(preset)
        self._schedule_preview_update()

    def _reset_settings(self):
        """Reset all sliders to their default values."""
        mode = self.settings.mode
        defaults = ProcessingSettings(mode=mode)
        self.settings = defaults
        self._apply_settings_to_ui(defaults)
        self.preset_menu.set("Custom")
        self.dn_preset_menu.set("Custom")

        # Reset format and quality
        self.format_menu.set("PNG")
        self.settings.output_format = "PNG"
        self.quality_frame.pack_forget()
        self.quality_slider.set(95)
        self.quality_val_label.configure(text="95")
        self.settings.jpeg_quality = 95

        self._schedule_preview_update()

    def _on_preset_change(self, value):
        """Apply an upscale quality preset, or restore saved custom values."""
        if value == "Custom":
            self.settings = self._custom_settings.copy()
            self._apply_settings_to_ui(self.settings)
            self._schedule_preview_update()
            return
        if value not in PRESETS:
            return
        self._custom_settings = self.settings.copy()
        preset = PRESETS[value].copy()
        self.settings = preset
        self._apply_settings_to_ui(preset)
        self._schedule_preview_update()

    def _apply_settings_to_ui(self, s: ProcessingSettings):
        """Sync all slider widgets to match a ProcessingSettings object."""
        for attr, sliders in self._slider_refs.items():
            val = getattr(s, attr, None)
            if val is None:
                continue
            for slider in sliders:
                slider.set(val)
            for (val_label, fmt, vtype) in self._slider_val_labels[attr]:
                val_label.configure(text=fmt.format(val))

    def _on_slider_change(self, value, attr, val_label, fmt, step, vtype):
        if vtype is int:
            value = int(round(value))
        else:
            value = round(round(value / step) * step, 4)

        val_label.configure(text=fmt.format(value))
        setattr(self.settings, attr, vtype(value))

        # Sync duplicate sliders for shared attrs (contrast, saturation, etc.)
        for slider in self._slider_refs.get(attr, []):
            if abs(slider.get() - value) > 0.0001:
                slider.set(value)
        for (vl, f, _) in self._slider_val_labels.get(attr, []):
            vl.configure(text=f.format(value))

        self.preset_menu.set("Custom")
        self.dn_preset_menu.set("Custom")
        self._custom_settings = self.settings.copy()
        self._schedule_preview_update()

    def _step_slider(self, attr: str, delta: float, lo: float, hi: float):
        """Nudge a slider by one step (+/-)."""
        sliders = self._slider_refs[attr]
        current = sliders[0].get()
        new_val = max(lo, min(hi, current + delta))
        vtype = self._slider_val_labels[attr][0][2]
        if vtype is int:
            new_val = int(round(new_val))
        else:
            new_val = round(new_val, 4)
        for slider in sliders:
            slider.set(new_val)
        for (vl, fmt, _) in self._slider_val_labels[attr]:
            vl.configure(text=fmt.format(new_val))
        setattr(self.settings, attr, vtype(new_val))
        self.preset_menu.set("Custom")
        self.dn_preset_menu.set("Custom")
        self._custom_settings = self.settings.copy()
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

    def _select_preview(self, idx):
        """Select a file from the list by index and show it in preview."""
        if 0 <= idx < len(self.image_infos):
            self.preview_index = idx
            self.preview_selector.set(self.image_infos[idx].filename)
            self._schedule_preview_update()

    def _on_preview_canvas_resize(self, _event=None):
        """Re-draw checkerboard, re-center placeholder, re-render preview."""
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        if cw > 1 and ch > 1:
            self._draw_checkerboard(cw, ch)
        self.preview_canvas.coords(self._preview_placeholder_id, cw // 2, ch // 2)
        if self._preview_pil is not None:
            self._render_canvas()

    # ── Zoom & Pan ────────────────────────────────────────────────────

    def _on_zoom(self, event):
        if self._preview_pil is None or self._loading_overlay_active:
            return
        # Determine scroll direction
        if event.num == 5 or event.delta < 0:
            factor = 0.9
        else:
            factor = 1.1
        new_zoom = max(0.1, min(20.0, self._zoom * factor))
        if new_zoom != self._zoom:
            self._zoom = new_zoom
            self._render_canvas()

    def _on_pan_start(self, event):
        if self._loading_overlay_active:
            return
        self._drag_start = (event.x, event.y)

    def _on_pan_move(self, event):
        if self._drag_start is None or self._loading_overlay_active:
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
        if self._loading_overlay_active:
            return
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
        self.progress_bar.set(0)
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()
        self.update_idletasks()

        new_paths, temp_dirs = collect_images(paths)
        self.temp_dirs.extend(temp_dirs)

        existing = {info.path for info in self.image_infos}
        added = 0
        total_new = len(new_paths)

        for idx, p in enumerate(new_paths):
            if p in existing:
                continue
            try:
                info = ImageInfo.from_path(p)
                self.image_infos.append(info)
                existing.add(p)
                added += 1
            except Exception:
                continue
            # Update progress periodically
            if added % 10 == 0:
                self.progress_label.configure(
                    text=f"Loading {idx + 1}/{total_new}..."
                )
                self.update_idletasks()

        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)
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
            lbl = ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=12), anchor="w")
            lbl.grid(row=0, column=0, sticky="w")
            # Double-click to show in preview
            lbl.bind("<Double-Button-1>", lambda _e, idx=i: self._select_preview(idx))
            row.bind("<Double-Button-1>", lambda _e, idx=i: self._select_preview(idx))
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

        # Show blurred loading overlay on top of everything
        self._show_loading_overlay()

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
        self._clear_loading_overlay()

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

        # Cap display pixels to prevent lag at high zoom
        MAX_DISPLAY_PIXELS = 4_000_000  # ~2000x2000
        pixel_count = disp_w * disp_h
        if pixel_count > MAX_DISPLAY_PIXELS:
            shrink = (MAX_DISPLAY_PIXELS / pixel_count) ** 0.5
            disp_w = max(1, int(disp_w * shrink))
            disp_h = max(1, int(disp_h * shrink))

        # Use NEAREST for fast zooming when heavily zoomed in, LANCZOS for quality at normal zoom
        resample = Image.NEAREST if self._zoom > 3.0 else Image.LANCZOS
        display = self._preview_pil.resize((disp_w, disp_h), resample)

        photo = ImageTk.PhotoImage(display)
        self._preview_photo = photo  # prevent GC

        # Position: centred + pan offset
        cx = cw // 2 + int(self._pan_x)
        cy = ch // 2 + int(self._pan_y)

        self.preview_canvas.delete("preview")

        # Redraw full-canvas checkerboard at current zoom scale
        self._draw_checkerboard(cw, ch)

        self.preview_canvas.create_image(cx, cy, image=photo, anchor="center", tags="preview")
        self.preview_canvas.itemconfigure(self._preview_placeholder_id, state="hidden")

    # ── Loading overlay ───────────────────────────────────────────────

    def _show_loading_overlay(self):
        """Capture the current canvas, blur it, and overlay with loading text."""
        cw = max(1, self.preview_canvas.winfo_width())
        ch = max(1, self.preview_canvas.winfo_height())

        # Build a snapshot of what's currently on the canvas
        # Start with the dark background
        snap = Image.new("RGB", (cw, ch), (26, 26, 26))

        # Paste the checkerboard if it exists
        if self._checker_photo is not None:
            try:
                # Re-create checker at current size
                base_tile = 16
                s = max(2, int(base_tile * self._zoom))
                dark = (26, 26, 26)
                light = (38, 38, 38)
                ox = int(self._pan_x) % (s * 2)
                oy = int(self._pan_y) % (s * 2)
                draw = ImageDraw.Draw(snap)
                for ty in range(-s * 2 + oy, ch, s):
                    for tx in range(-s * 2 + ox, cw, s):
                        col_idx = (tx - ox) // s
                        row_idx = (ty - oy) // s
                        if (col_idx + row_idx) % 2 == 1:
                            x0, y0 = max(0, tx), max(0, ty)
                            x1, y1 = min(tx + s - 1, cw - 1), min(ty + s - 1, ch - 1)
                            if x1 >= x0 and y1 >= y0:
                                draw.rectangle([x0, y0, x1, y1], fill=light)
            except Exception:
                pass

        # Paste the current preview image if present
        if self._preview_pil is not None and self._preview_photo is not None:
            try:
                iw, ih = self._preview_pil.size
                base_scale = min(cw / iw, ch / ih, 1.0)
                scale = base_scale * self._zoom
                disp_w = max(1, int(iw * scale))
                disp_h = max(1, int(ih * scale))
                display = self._preview_pil.resize((disp_w, disp_h), Image.NEAREST)
                cx = cw // 2 + int(self._pan_x)
                cy = ch // 2 + int(self._pan_y)
                paste_x = cx - disp_w // 2
                paste_y = cy - disp_h // 2
                if display.mode == "RGBA":
                    snap.paste(display, (paste_x, paste_y), display)
                else:
                    snap.paste(display, (paste_x, paste_y))
            except Exception:
                pass

        # Blur the snapshot slightly
        blurred = snap.filter(ImageFilter.GaussianBlur(radius=4))
        blurred = ImageEnhance.Brightness(blurred).enhance(0.95)

        # Draw loading text onto the blurred image
        draw = ImageDraw.Draw(blurred)
        text = "Processing preview..."
        try:
            font = ImageFont.truetype("segoeui.ttf", 18)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (cw - tw) // 2
        ty = (ch - th) // 2
        # Text background pill
        pad = 12
        draw.rounded_rectangle(
            [tx - pad * 2, ty - pad, tx + tw + pad * 2, ty + th + pad],
            radius=10, fill=(40, 40, 40, 220),
        )
        draw.text((tx, ty), text, fill=(255, 255, 255), font=font)

        self._loading_blur_photo = ImageTk.PhotoImage(blurred)
        self.preview_canvas.delete("loading")
        self.preview_canvas.create_image(
            0, 0, image=self._loading_blur_photo, anchor="nw", tags="loading",
        )
        # Ensure loading overlay is on top of everything
        self.preview_canvas.tag_raise("loading")
        self._loading_overlay_active = True

    def _clear_loading_overlay(self):
        """Remove the loading overlay."""
        self.preview_canvas.delete("loading")
        self._loading_blur_photo = None
        self._loading_overlay_active = False

    def _preview_error(self, msg: str):
        self._preview_pil = None
        self._preview_photo = None
        self.preview_canvas.delete("preview")
        self._clear_loading_overlay()
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

        # Ask for output folder name
        from tkinter import simpledialog
        folder_name = simpledialog.askstring(
            "Folder Name",
            "Enter a name for the output folder:",
            initialvalue="upscaled_output",
            parent=self,
        )
        if not folder_name:
            return
        # Sanitise folder name
        folder_name = folder_name.strip().replace('\\', '_').replace('/', '_')
        if not folder_name:
            folder_name = "upscaled_output"

        output_dir = os.path.join(dest, folder_name)
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
                out_path = os.path.join(output_dir, out_name)
                n = 1
                while out_name in used_names or os.path.exists(out_path):
                    out_name = f"{base} ({n}){out_ext}"
                    out_path = os.path.join(output_dir, out_name)
                    n += 1
                used_names.add(out_name)

                save_image(processed, out_path, settings)
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
