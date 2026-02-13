"""
Image processing engine for the Image Upscaler & Enhancer.
Handles image scanning, processing passes, and export.
"""

import os
import zipfile
import tempfile
from dataclasses import dataclass
from PIL import Image, ImageFilter, ImageEnhance
from io import BytesIO
from typing import List, Tuple, Set

SUPPORTED_EXTENSIONS: Set[str] = {
    '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp', '.gif'
}


def format_size(size_bytes: float) -> str:
    """Format byte count to human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


@dataclass
class ProcessingSettings:
    """All adjustable image processing parameters."""
    upscale_factor: int = 4
    blur_radius: float = 0.6
    sharpen_radius: float = 1.2
    sharpen_amount: int = 120
    sharpen_threshold: int = 2
    downscale_factor: float = 0.97
    edge_trim: int = 0          # pixels to crop from each edge
    contrast: float = 1.0       # 1.0 = unchanged
    saturation: float = 1.0     # 1.0 = unchanged
    brightness: float = 1.0     # 1.0 = unchanged
    noise_reduction: int = 0    # 0 = off, median-filter strength for anti-aliasing
    output_format: str = 'PNG'
    jpeg_quality: int = 95

    def copy(self) -> 'ProcessingSettings':
        return ProcessingSettings(
            upscale_factor=self.upscale_factor,
            blur_radius=self.blur_radius,
            sharpen_radius=self.sharpen_radius,
            sharpen_amount=self.sharpen_amount,
            sharpen_threshold=self.sharpen_threshold,
            downscale_factor=self.downscale_factor,
            edge_trim=self.edge_trim,
            contrast=self.contrast,
            saturation=self.saturation,
            brightness=self.brightness,
            noise_reduction=self.noise_reduction,
            output_format=self.output_format,
            jpeg_quality=self.jpeg_quality,
        )


@dataclass
class ImageInfo:
    """Metadata about a loaded image file."""
    path: str
    filename: str
    file_size: int
    width: int
    height: int
    mode: str

    @classmethod
    def from_path(cls, path: str) -> 'ImageInfo':
        filename = os.path.basename(path)
        file_size = os.path.getsize(path)
        with Image.open(path) as img:
            width, height = img.size
            mode = img.mode
        return cls(
            path=path, filename=filename, file_size=file_size,
            width=width, height=height, mode=mode
        )


def collect_images(paths: List[str]) -> Tuple[List[str], List[str]]:
    """
    Scan a list of file/folder/zip paths and find all supported images.
    Returns (list_of_image_paths, list_of_temp_dirs_to_cleanup).
    """
    images: List[str] = []
    temp_dirs: List[str] = []
    seen: Set[str] = set()

    for raw_path in paths:
        path = raw_path.strip().strip('"').strip("'")
        if not os.path.exists(path):
            continue

        if os.path.isdir(path):
            _scan_directory(path, images, seen, temp_dirs)

        elif zipfile.is_zipfile(path):
            tmp = tempfile.mkdtemp(prefix="imgupscaler_")
            temp_dirs.append(tmp)
            try:
                with zipfile.ZipFile(path, 'r') as zf:
                    zf.extractall(tmp)
                _scan_directory(tmp, images, seen, temp_dirs)
            except zipfile.BadZipFile:
                continue

        elif os.path.isfile(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in SUPPORTED_EXTENSIONS and path not in seen:
                images.append(path)
                seen.add(path)

    return images, temp_dirs


def _scan_directory(directory: str, images: List[str], seen: Set[str],
                    temp_dirs: List[str] | None = None):
    """Recursively find all supported image files (and ZIPs) in a directory."""
    for root, _, files in os.walk(directory):
        for f in files:
            fp = os.path.join(root, f)
            ext = os.path.splitext(f)[1].lower()
            if ext in SUPPORTED_EXTENSIONS and fp not in seen:
                images.append(fp)
                seen.add(fp)
            elif ext == '.zip' and fp not in seen and temp_dirs is not None:
                seen.add(fp)
                try:
                    if zipfile.is_zipfile(fp):
                        tmp = tempfile.mkdtemp(prefix="imgupscaler_")
                        temp_dirs.append(tmp)
                        with zipfile.ZipFile(fp, 'r') as zf:
                            zf.extractall(tmp)
                        _scan_directory(tmp, images, seen, temp_dirs)
                except Exception:
                    pass


def process_image(img: Image.Image, settings: ProcessingSettings) -> Image.Image:
    """Apply all processing passes to a PIL Image and return the result."""
    # Ensure RGBA for transparency support
    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    # Pass 1: Upscale using Lanczos resampling
    if settings.upscale_factor > 1:
        new_w = img.width * settings.upscale_factor
        new_h = img.height * settings.upscale_factor
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Pass 2: Light Gaussian blur for anti-aliasing
    if settings.blur_radius > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=settings.blur_radius))

    # Pass 3: Unsharp mask to recover sharpness
    if settings.sharpen_amount > 0:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=settings.sharpen_radius,
            percent=settings.sharpen_amount,
            threshold=settings.sharpen_threshold,
        ))

    # Pass 4: Slight downscale to smooth stair-step edges
    if settings.downscale_factor < 1.0:
        new_w = max(1, int(img.width * settings.downscale_factor))
        new_h = max(1, int(img.height * settings.downscale_factor))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    # Pass 5: Contrast adjustment
    if settings.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(settings.contrast)

    # Pass 6: Saturation adjustment
    if settings.saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(settings.saturation)

    # Pass 7: Brightness adjustment
    if settings.brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(settings.brightness)

    # Pass 8: Noise reduction / anti-aliasing (median filter)
    if settings.noise_reduction > 0:
        # MedianFilter removes noise and softens jagged edges
        # Kernel size must be odd and >= 3
        k = settings.noise_reduction * 2 + 1  # 1->3, 2->5, 3->7 ...
        img = img.filter(ImageFilter.MedianFilter(size=k))

    # Pass 9: Erode outer pixels of visible (non-transparent) content
    if settings.edge_trim > 0 and img.mode == 'RGBA':
        alpha = img.getchannel('A')
        # Erode alpha: repeatedly apply a MinFilter to shrink opaque area
        # Each MinFilter(3) pass erodes ~1 pixel from each edge
        eroded = alpha
        for _ in range(settings.edge_trim):
            eroded = eroded.filter(ImageFilter.MinFilter(3))
        img.putalpha(eroded)

    return img


def get_output_dimensions(
    width: int, height: int, settings: ProcessingSettings
) -> Tuple[int, int]:
    """Calculate the final output dimensions without processing."""
    w = width * settings.upscale_factor if settings.upscale_factor > 1 else width
    h = height * settings.upscale_factor if settings.upscale_factor > 1 else height
    if settings.downscale_factor < 1.0:
        w = max(1, int(w * settings.downscale_factor))
        h = max(1, int(h * settings.downscale_factor))
    # edge_trim erodes alpha but doesn't change image dimensions
    return w, h


def save_image(img: Image.Image, path: str, settings: ProcessingSettings):
    """Save a processed image with the appropriate format settings."""
    fmt = settings.output_format.upper()

    if fmt in ('JPEG', 'JPG'):
        # JPEG cannot store transparency — flatten onto white
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.save(path, format='JPEG', quality=settings.jpeg_quality, optimize=True)

    elif fmt == 'WEBP':
        img.save(path, format='WEBP', quality=settings.jpeg_quality, method=4)

    else:  # PNG
        img.save(path, format='PNG', compress_level=1)


def estimate_output_size(img: Image.Image, settings: ProcessingSettings) -> int:
    """Estimate the output file size in bytes (fast, uses higher compression)."""
    buf = BytesIO()
    fmt = settings.output_format.upper()

    if fmt in ('JPEG', 'JPG'):
        save_img = img
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            save_img = bg
        elif img.mode != 'RGB':
            save_img = img.convert('RGB')
        save_img.save(buf, format='JPEG', quality=settings.jpeg_quality)

    elif fmt == 'WEBP':
        img.save(buf, format='WEBP', quality=settings.jpeg_quality)

    else:
        img.save(buf, format='PNG', compress_level=6)

    return buf.tell()
