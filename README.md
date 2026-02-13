# Image Upscaler & Enhancer

A desktop GUI application for batch upscaling and enhancing images. Drag and drop files, folders, or ZIP archives — adjust processing settings with live preview — then export everything to a single output folder.

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)

---

## Features

- **Drag & Drop** — Drop images, folders, or ZIP archives directly into the app
- **Batch Processing** — Process hundreds of images at once with a progress bar
- **Live Preview** — See real-time results as you adjust settings (pan & zoom supported)
- **11 Adjustable Sliders** — Fine-tune every aspect of the enhancement pipeline
- **Quality Presets** — Low, Medium, High, Ultra, or fully Custom
- **Multiple Formats** — Export as PNG, JPEG, or WebP
- **Resizable Panels** — Drag the dividers between panels to customize your layout
- **Single EXE** — Ships as a portable standalone executable (no install required)

## Processing Pipeline

Each image goes through up to 9 processing passes:

| Pass | Setting | Description |
|------|---------|-------------|
| 1 | **Upscale Factor** (1–8×) | Enlarge using Lanczos resampling |
| 2 | **Blur Radius** (0–3.0) | Light Gaussian blur for anti-aliasing |
| 3 | **Sharpen** (radius, amount, threshold) | Unsharp mask to recover detail |
| 4 | **Downscale Factor** (0.80–1.00) | Slight downscale to smooth stair-step edges |
| 5 | **Contrast** (0.50–2.00) | Adjust image contrast |
| 6 | **Saturation** (0.00–2.00) | Adjust color intensity |
| 7 | **Brightness** (0.50–2.00) | Adjust overall brightness |
| 8 | **Noise Reduction** (0–5) | Median filter for anti-aliasing and noise removal |
| 9 | **Edge Trim** (0–50 px) | Erode alpha channel to clean transparent edges |

## Supported Formats

**Input:** PNG, JPG, JPEG, BMP, TIFF, TIF, WebP, GIF, ZIP (containing images)

**Output:** PNG, JPEG, WebP

## Getting Started

### Prerequisites

- Python 3.10+

### Install & Run

```bash
# Clone the repo
git clone https://github.com/Chadman300/Image_Enhancer.git
cd Image_Enhancer

# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Run the app
python main.py
```

### Build Standalone EXE

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico --add-data "icon.ico;." --name ImageUpscaler main.py
```

The executable will be in the `dist/` folder.

## Dependencies

| Package | Purpose |
|---------|---------|
| [Pillow](https://pypi.org/project/Pillow/) | Image processing engine |
| [CustomTkinter](https://pypi.org/project/customtkinter/) | Modern dark-themed GUI |
| [windnd](https://pypi.org/project/windnd/) | Native Windows drag & drop |

## Project Structure

```
├── main.py            # GUI application (~1300 lines)
├── processor.py       # Image processing engine (~260 lines)
├── requirements.txt   # Python dependencies
├── icon.ico           # App icon
└── dist/
    └── ImageUpscaler.exe   # Standalone executable
```

## Screenshots

*Launch the app to see the dark-themed interface with resizable panels, live preview canvas, and processing sliders.*

## License

This project is open source and available under the [MIT License](LICENSE).
