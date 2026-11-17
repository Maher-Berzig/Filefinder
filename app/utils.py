"""
Small helper functions shared across the application.

Everything in here is written to work on Windows 7 (32-bit) with
Python 3.8, so no walrus-only tricks that need a newer interpreter,
no pathlib features added after 3.8, etc.
"""
import ctypes
import os
import platform
import subprocess
import sys

IS_WINDOWS = platform.system() == "Windows"


# Dark-mode switch shared by the hand-drawn icons and the preview pane's
# hard-coded colours (set by MainWindow when the theme is toggled).
DARK = False


def set_dark(flag):
    global DARK
    DARK = bool(flag)


def workspace_color():
    """Background behind the pages in the preview's continuous view."""
    return "#3a3a3a" if DARK else "#c8c8c8"


def invert_icon(icon):
    """Return *icon* with its colours inverted (alpha kept), so the
    dark-grey hand-drawn glyphs become light on a dark button."""
    from PyQt5.QtGui import QImage, QPixmap, QIcon
    sizes = icon.availableSizes()
    if not sizes:
        return icon
    img = icon.pixmap(sizes[0]).toImage().convertToFormat(QImage.Format_ARGB32)
    img.invertPixels(QImage.InvertRgb)
    return QIcon(QPixmap.fromImage(img))


def triangle_icon(direction, size=18, color=None):
    """A simple solid triangle pointing left/right/up/down, drawn with
    QPainter so it's crisp at any size without needing an icon asset.
    Shared so every part of the UI (preview pane nav, the Filters/
    Options collapse toggle, etc.) uses the exact same triangle."""
    from PyQt5.QtCore import Qt, QPointF
    from PyQt5.QtGui import QPixmap, QPainter, QColor, QPolygonF, QIcon

    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(color or (QColor(190, 190, 190) if DARK else QColor(90, 90, 90)))
    m = size * 0.24
    if direction == "left":
        points = [QPointF(size - m, m), QPointF(size - m, size - m), QPointF(m, size / 2.0)]
    elif direction == "up":
        points = [QPointF(m, size - m), QPointF(size - m, size - m), QPointF(size / 2.0, m)]
    elif direction == "down":
        points = [QPointF(m, m), QPointF(size - m, m), QPointF(size / 2.0, size - m)]
    else:  # "right"
        points = [QPointF(m, m), QPointF(m, size - m), QPointF(size - m, size / 2.0)]
    p.drawPolygon(QPolygonF(points))
    p.end()
    return QIcon(pm)


def human_size(num_bytes):
    """Return a human readable file size, e.g. '12.3 MB'."""
    if num_bytes is None:
        return ""
    num = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0:
            if unit == "B":
                return "%d %s" % (num, unit)
            return "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f PB" % num


def list_windows_drives():
    """Return a list of available drive letters, e.g. ['C:\\\\', 'D:\\\\']."""
    drives = []
    if IS_WINDOWS:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in range(26):
            if bitmask & (1 << letter):
                drives.append("%s:\\" % chr(65 + letter))
    else:
        # Non-Windows fallback so the app is still usable while developing
        # / testing on Linux or macOS.
        drives.append(os.path.abspath(os.sep))
    return drives


def open_path(path):
    """Open a file (or folder) with the OS default application."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606 - intentional, Windows only API
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, ""
    except Exception as exc:  # pragma: no cover - depends on host OS
        return False, str(exc)


def reveal_in_explorer(path):
    """Open the parent folder and, on Windows, highlight the file."""
    try:
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", folder])
        return True, ""
    except Exception as exc:  # pragma: no cover - depends on host OS
        return False, str(exc)


def copy_to_clipboard(text):
    from PyQt5.QtWidgets import QApplication

    clipboard = QApplication.clipboard()
    clipboard.setText(text)


def copy_lines_to_clipboard(lines):
    """Copy a list of strings to the clipboard, one per line."""
    copy_to_clipboard(os.linesep.join(lines))


def is_previewable(path):
    """The preview pane has a fallback for essentially any file (PDF/
    DJVU render pages, .docx renders formatted, everything else shows
    as text if it looks like text and isn't too large) - so this just
    confirms there's an actual file to show something for."""
    return bool(path) and os.path.isfile(path)


# Every image format a stock PyQt5 can decode through QImageReader.
# Used as-is for the "Images" file-type filter, and as the floor for
# image_extensions() below (which also asks the running Qt what its
# installed image plugins actually support).
IMAGE_EXTENSIONS_FALLBACK = {
    ".bmp", ".cur", ".gif", ".icns", ".ico", ".jpeg", ".jpg", ".pbm",
    ".pgm", ".png", ".ppm", ".svg", ".svgz", ".tga", ".tif", ".tiff",
    ".wbmp", ".webp", ".xbm", ".xpm",
}

_image_extensions_cache = None


def image_extensions():
    """Extensions the preview pane can display as images.

    Asked of QImageReader at runtime rather than hard-coded, so the
    preview automatically covers whatever image format plugins are
    actually installed alongside Qt (a frozen build that ships fewer
    plugins, or a Qt with extra ones, both work out on their own).
    IMAGE_EXTENSIONS_FALLBACK is unioned in so the list never comes
    back short if the plugins can't be enumerated for some reason.
    """
    global _image_extensions_cache
    if _image_extensions_cache is None:
        extensions = set(IMAGE_EXTENSIONS_FALLBACK)
        try:
            from PyQt5.QtGui import QImageReader

            for fmt in QImageReader.supportedImageFormats():
                name = bytes(fmt).decode("ascii", "ignore").strip().lower()
                if name:
                    extensions.add("." + name)
        except Exception:
            pass
        _image_extensions_cache = extensions
    return _image_extensions_cache


EXTENSION_GROUPS = {
    "All files": None,
    "Documents": {
        ".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".xls", ".xlsx",
        ".ppt", ".pptx", ".csv", ".md",
    },
    "Images": set(IMAGE_EXTENSIONS_FALLBACK),
    "Music": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
    "Video": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso"},
    "Executables": {".exe", ".msi", ".bat", ".cmd", ".com"},
}


def format_seconds(seconds):
    if seconds < 60:
        return "%.1fs" % seconds
    minutes, sec = divmod(int(seconds), 60)
    return "%dm %ds" % (minutes, sec)
