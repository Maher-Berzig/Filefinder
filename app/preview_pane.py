"""
Left-side preview pane for the results table: shows PDF/DJVU pages.

Two view modes:
  - "single"     one page at a time, with Prev/Next/page-number nav.
  - "continuous" every page stacked vertically, scroll through them all;
                 pages are rendered lazily as they scroll near the
                 visible area (and re-used once rendered).

Zoom: Ctrl +/-, Ctrl+0 to reset, or Ctrl+mouse wheel. Plain mouse wheel
scrolls inside the page/document as normal, and in single-page mode
rolling past the top/bottom edge turns to the previous/next page.

PDF rendering uses PyMuPDF (``import fitz``) - optional dependency.
DJVU rendering shells out to the djvulibre command line tools
(``ddjvu.exe`` / ``djvused.exe``).

Nothing here blocks the UI thread: every page render happens on a
QThread and reports back through a signal. A monotonically increasing
"generation" counter (bumped whenever the file, zoom, view mode, or
requested single page changes) is attached to every request so stale
results - from a page/zoom/file that's no longer current - are safely
ignored instead of overwriting newer results or corrupting state.
"""
import html
import math
import os
import subprocess
import sys
import time

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QTimer, QSize, QRectF, QPointF
from PyQt5.QtGui import QPixmap, QKeySequence, QIcon, QPainter, QPen, QColor, QPolygonF, QFontDatabase, QTransform
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSpinBox, QSizePolicy, QToolButton, QButtonGroup, QShortcut, QTextEdit,
    QApplication,
)

from . import utils
from .translations import tr

try:
    import fitz  # PyMuPDF
    HAVE_FITZ = True
except Exception:
    HAVE_FITZ = False

try:
    import docx  # python-docx
    from docx.document import Document as _DocxDocumentType
    from docx.oxml.text.paragraph import CT_P
    from docx.oxml.table import CT_Tbl
    from docx.table import Table as _DocxTable
    from docx.text.paragraph import Paragraph as _DocxParagraph
    HAVE_DOCX = True
except Exception:
    HAVE_DOCX = False

# "Reasonably sized" cutoff for the generic text preview - bigger files
# just show a message instead of being read in fully.
TEXT_PREVIEW_MAX_BYTES = 5 * 1024 * 1024  # 5 MB


NAV_BTN_SIZE = QSize(30, 30)
NAV_ICON_SIZE = QSize(18, 18)
PAGE_GAP_PX = 28  # visible gap between pages in "Show pages continuously" mode


def _single_page_icon(size=18):
    """One rectangle with a couple of text lines - "one page at a time"."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(90, 90, 90))
    pen.setWidthF(1.2)
    p.setPen(pen)
    p.setBrush(QColor(225, 225, 225))
    x0, y0 = size * 0.22, 2.0
    x1, y1 = size - 2.0, size - 2.0
    p.drawRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), 1.2, 1.2)
    line_pen = QPen(QColor(140, 140, 140))
    line_pen.setWidthF(1.0)
    p.setPen(line_pen)
    inset = (x1 - x0) * 0.22
    for frac in (0.42, 0.62):
        ly = y0 + (y1 - y0) * frac
        p.drawLine(int(x0 + inset), int(ly), int(x1 - inset), int(ly))
    p.end()
    return QIcon(pm)


def _triangle_icon(direction, size=18):
    """A simple left- or right-pointing triangle, for Prev/Next."""
    return utils.triangle_icon(direction, size=size)


def _frame_fit_icon(full_width, size=18):
    """Outer square = the window/pane; inner rectangle = the page.
    full_width=True draws the page touching the left/right edges of the
    frame ("fit width"); False draws it with margin on every side
    ("fit to window"), the classic pair of icons PDF viewers use."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    outer_pen = QPen(QColor(150, 150, 150))
    outer_pen.setWidthF(1.0)
    p.setPen(outer_pen)
    p.setBrush(Qt.NoBrush)
    om = 1.5
    p.drawRect(QRectF(om, om, size - om * 2, size - om * 2))

    inner_pen = QPen(QColor(80, 80, 80))
    inner_pen.setWidthF(1.3)
    p.setPen(inner_pen)
    p.setBrush(QColor(210, 210, 210))
    if full_width:
        x0, x1 = om + 1.5, size - om - 1.5
        y0, y1 = size * 0.32, size * 0.68
    else:
        x0, x1 = size * 0.28, size * 0.72
        y0, y1 = size * 0.24, size * 0.76
    p.drawRect(QRectF(x0, y0, x1 - x0, y1 - y0))
    p.end()
    return QIcon(pm)


def _magnifier_icon(sign, size=18):
    """A magnifying glass (lens + handle) with a "+" or "-" inside the
    lens, for the zoom in/out buttons."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    lens_d = size * 0.62
    cx, cy = size * 0.42, size * 0.42
    r = lens_d / 2.0

    lens_pen = QPen(QColor(90, 90, 90))
    lens_pen.setWidthF(1.5)
    p.setPen(lens_pen)
    p.setBrush(QColor(235, 235, 235))
    p.drawEllipse(QPointF(cx, cy), r, r)

    handle_pen = QPen(QColor(90, 90, 90))
    handle_pen.setWidthF(2.0)
    handle_pen.setCapStyle(Qt.RoundCap)
    p.setPen(handle_pen)
    angle = math.radians(45)
    hx0 = cx + r * math.cos(angle)
    hy0 = cy + r * math.sin(angle)
    hx1 = size - 1.5
    hy1 = size - 1.5
    p.drawLine(QPointF(hx0, hy0), QPointF(hx1, hy1))

    sign_pen = QPen(QColor(70, 70, 70))
    sign_pen.setWidthF(1.6)
    sign_pen.setCapStyle(Qt.RoundCap)
    p.setPen(sign_pen)
    sr = r * 0.5
    p.drawLine(QPointF(cx - sr, cy), QPointF(cx + sr, cy))
    if sign == "+":
        p.drawLine(QPointF(cx, cy - sr), QPointF(cx, cy + sr))

    p.end()
    return QIcon(pm)

import math
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QPixmap, QPainter, QPen, QColor, QIcon

def _rotate_icon(direction, size=18):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)

    if direction == "left":
        p.translate(size, 0)
        p.scale(-1, 1)

    color = QColor(90, 90, 90)
    pen = QPen(color)
    pen.setWidthF(size * 0.12)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)

    cx, cy = size * 0.5, size * 0.5
    r = size * 0.32
    start_deg = 100
    sweep_deg = 260
    rect = QRectF(cx - r, cy - r, r * 2, r * 2)
    p.drawArc(rect, int(start_deg * 16), int(sweep_deg * 16))

    # 1. Find the tip of the arc
    end_angle_rad = math.radians(start_deg + sweep_deg)
    tip = QPointF(cx + r * math.cos(end_angle_rad), cy - r * math.sin(end_angle_rad))

    # -------------------------------------------------------------------------
    # ADJUST THESE PARAMETERS:
    # -------------------------------------------------------------------------
    # arrow_rotation_offset: 
    #   0 = Perfectly aligned with the arc's path.
    #   Positive values (e.g. 10, 20) = Rotates arrowhead clockwise.
    #   Negative values (e.g. -10, -20) = Rotates arrowhead counter-clockwise.
    arrow_rotation_offset = 200 
    
    
    # wing_spread: 
    #   Controls how "open" the V is. 30 is narrow, 60 is wide.
    wing_spread = 30 
    
    # head_length:
    #   How long the arrowhead wings are.
    head_length = size * 0.22
    # -------------------------------------------------------------------------

    # Calculate travel direction + your custom offset
    # Base tangent for clockwise arc is (sin, -cos)
    base_angle = end_angle_rad + math.radians(arrow_rotation_offset)
    tx = math.sin(base_angle)
    ty = -math.cos(base_angle)

    # Rotate tangent by wing_spread to get the two wings
    def rotate_vec(vx, vy, angle_deg):
        rad = math.radians(angle_deg)
        return (vx * math.cos(rad) - vy * math.sin(rad),
                vx * math.sin(rad) + vy * math.cos(rad))

    v1_x, v1_y = rotate_vec(tx, ty, wing_spread)
    v2_x, v2_y = rotate_vec(tx, ty, -wing_spread)

    p1 = QPointF(tip.x() + v1_x * head_length, tip.y() + v1_y * head_length)
    p2 = QPointF(tip.x() + v2_x * head_length, tip.y() + v2_y * head_length)

    p.drawLine(p1, tip)
    p.drawLine(tip, p2)

    p.end()
    return QIcon(pm)



    
def _make_nav_button(icon=None, text=None, tooltip="", checkable=False):
    """A QToolButton sized/iconned consistently with the rest of the
    preview pane's header row, so every button ends up the same width."""
    btn = QToolButton()
    if icon is not None:
        btn.setIcon(icon)
        btn.setIconSize(NAV_ICON_SIZE)
    if text is not None:
        btn.setText(text)
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setFixedSize(NAV_BTN_SIZE)
    return btn


def _default_djvu_tools_dir():
    """Where to find ddjvu.exe/djvused.exe without the user having to
    point at them manually - this is where Filefinder.bat's
    --add-binary lines put them when building with PyInstaller."""
    candidates = []
    if getattr(sys, "frozen", False):
        # PyInstaller sets _MEIPASS to the bundle's extraction root -
        # for --onedir builds (what Filefinder.bat produces) that's the
        # "_internal" folder next to the .exe, exactly where
        # --add-binary "...;." puts things.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(meipass)
        candidates.append(os.path.dirname(sys.executable))
    else:
        # Running from source (e.g. "python main.py") - check next to
        # this file, and the conventional resources/djvulibre folder.
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(here)
        candidates.append(os.path.join(os.path.dirname(here), "resources", "djvulibre"))

    for candidate in candidates:
        if candidate and os.path.exists(os.path.join(candidate, "ddjvu.exe")):
            return candidate
    return None


def _run_hidden(*args, **kwargs):
    """subprocess.run that doesn't flash a console window on Windows."""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(*args, **kwargs)


def _continuous_pages_icon(size=18):
    """Three stacked rectangles - "scroll through every page"."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(90, 90, 90))
    pen.setWidthF(1.2)
    p.setPen(pen)
    p.setBrush(QColor(225, 225, 225))
    margin = 2.0
    gap = 2.0
    page_h = (size - margin * 2 - gap * 2) / 3.0
    y = margin
    for _ in range(3):
        p.drawRoundedRect(QRectF(margin, y, size - margin * 2, page_h), 1.2, 1.2)
        y += page_h + gap
    p.end()
    return QIcon(pm)


class _PdfPageWorker(QThread):
    # generation, page(0-based), pixmap, page_count, error
    pageReady = pyqtSignal(int, int, QPixmap, int, str)

    def __init__(self, generation, path, page_index, target_width_px):
        super().__init__()
        self.generation = generation
        self.path = path
        self.page_index = page_index
        self.target_width_px = target_width_px

    def run(self):
        if not HAVE_FITZ:
            self.pageReady.emit(
                self.generation, self.page_index, QPixmap(), 0,
                "PDF preview needs PyMuPDF. Install it with:\n"
                "    pip install PyMuPDF")
            return
        try:
            doc = fitz.open(self.path)
            page_count = doc.page_count
            index = max(0, min(self.page_index, page_count - 1))
            page = doc[index]
            page_width_pts = max(page.rect.width, 1.0)
            zoom = self.target_width_px / page_width_pts
            zoom = max(0.2, min(zoom, 12.0))
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            expected_h = int(round(page.rect.height * zoom))
            pixmap = QPixmap()
            # PNG instead of PPM: self-describing and losslessly
            # validated, rather than a raw pixel dump that depends on
            # the header/byte-count lining up exactly - also a much
            # smaller payload to move off the worker thread.
            pixmap.loadFromData(pix.tobytes("png"), "PNG")
            doc.close()

            if pixmap.isNull() or pixmap.height() < expected_h * 0.9:
                # Rendered noticeably shorter than the page's own
                # aspect ratio says it should be - surface that as a
                # visible error instead of silently showing a page
                # that looks like it's been cut off partway through.
                self.pageReady.emit(
                    self.generation, index, QPixmap(), page_count,
                    "This page didn't render completely. Try scrolling "
                    "away and back, or changing zoom, to re-render it.")
                return

            self.pageReady.emit(self.generation, index, pixmap, page_count, "")
        except Exception as exc:
            self.pageReady.emit(self.generation, self.page_index, QPixmap(), 0, str(exc))


class _DjvuPageWorker(QThread):
    # generation, page(0-based), pixmap, page_count, error
    pageReady = pyqtSignal(int, int, QPixmap, int, str)

    def __init__(self, generation, path, page_index, tools_dir, target_width_px):
        super().__init__()
        self.generation = generation
        self.path = path
        self.page_index = page_index
        self.tools_dir = tools_dir
        self.target_width_px = target_width_px

    def _tool(self, name):
        if self.tools_dir:
            candidate = os.path.join(self.tools_dir, name)
            if os.path.exists(candidate):
                return candidate
        return name  # rely on PATH

    def run(self):
        try:
            r = _run_hidden(
                [self._tool("djvused.exe"), self.path, "-e", "n"],
                capture_output=True, text=True, timeout=15)
            page_count = int(r.stdout.strip())
        except Exception:
            page_count = 1

        index = max(0, min(self.page_index, page_count - 1))
        w = max(self.target_width_px, 100)
        h = int(w * 1.8)
        try:
            result = _run_hidden(
                [self._tool("ddjvu.exe"), "-format=ppm", "-size=%dx%d" % (w, h),
                 "-page=%d" % (index + 1), self.path],
                capture_output=True, check=True, timeout=30)
            pixmap = QPixmap()
            pixmap.loadFromData(result.stdout, "PPM")
            self.pageReady.emit(self.generation, index, pixmap, page_count, "")
        except FileNotFoundError:
            self.pageReady.emit(
                self.generation, index, QPixmap(), page_count,
                "DJVU preview needs the djvulibre tools (ddjvu.exe, "
                "djvused.exe) - place them next to the .exe (or bundle "
                "them via Filefinder.bat) or on the system PATH.")
        except Exception as exc:
            self.pageReady.emit(self.generation, index, QPixmap(), page_count, str(exc))


def _iter_docx_block_items(document):
    """Yield a document's paragraphs and tables in the order they
    actually appear - python-docx's own .paragraphs/.tables properties
    are separate lists with no ordering between them, so this walks the
    underlying XML body directly instead (a well-known python-docx
    recipe, since the library doesn't provide this itself)."""
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield _DocxParagraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield _DocxTable(child, document)


def _docx_run_to_html(run):
    text = html.escape(run.text).replace("\n", "<br/>")
    if not text:
        return ""
    if run.bold:
        text = "<b>%s</b>" % text
    if run.italic:
        text = "<i>%s</i>" % text
    if run.underline:
        text = "<u>%s</u>" % text
    return text


def _docx_paragraph_to_html(para):
    style_name = (para.style.name or "").strip().lower() if para.style else ""
    inner = "".join(_docx_run_to_html(r) for r in para.runs) or "&nbsp;"
    if style_name in ("title",) or style_name.startswith("heading 1"):
        return "<h2>%s</h2>" % inner
    if style_name.startswith("heading 2"):
        return "<h3>%s</h3>" % inner
    if style_name.startswith("heading"):
        return "<h4>%s</h4>" % inner
    return "<p>%s</p>" % inner


def _docx_table_to_html(table):
    rows_html = []
    for row in table.rows:
        cells_html = []
        for cell in row.cells:
            cell_text = "<br/>".join(html.escape(p.text) for p in cell.paragraphs)
            cells_html.append(
                "<td style='border:1px solid #999; padding:4px;'>%s</td>"
                % (cell_text or "&nbsp;"))
        rows_html.append("<tr>%s</tr>" % "".join(cells_html))
    return "<table style='border-collapse:collapse; margin:8px 0;'>%s</table>" % "".join(rows_html)


class _DocxLoadWorker(QThread):
    contentReady = pyqtSignal(int, str, str)  # generation, html, error

    MAX_BLOCKS = 4000  # safety cap so a huge document can't hang the UI

    def __init__(self, generation, path):
        super().__init__()
        self.generation = generation
        self.path = path

    def run(self):
        if not HAVE_DOCX:
            self.contentReady.emit(
                self.generation, "",
                "DOCX preview needs python-docx. Install it with:\n"
                "    pip install python-docx")
            return
        try:
            document = docx.Document(self.path)
            parts = []
            for i, block in enumerate(_iter_docx_block_items(document)):
                if isinstance(block, _DocxParagraph):
                    parts.append(_docx_paragraph_to_html(block))
                else:
                    parts.append(_docx_table_to_html(block))
                if i >= self.MAX_BLOCKS:
                    parts.append(
                        "<p><i>... preview truncated (very large document) ...</i></p>")
                    break
            html_str = "<html><body>%s</body></html>" % "".join(parts)
            self.contentReady.emit(self.generation, html_str, "")
        except Exception as exc:
            self.contentReady.emit(
                self.generation, "", "Could not open this .docx file: %s" % exc)


class _TextLoadWorker(QThread):
    contentReady = pyqtSignal(int, str, str)  # generation, text, error

    def __init__(self, generation, path):
        super().__init__()
        self.generation = generation
        self.path = path

    def run(self):
        try:
            size = os.path.getsize(self.path)
        except OSError as exc:
            self.contentReady.emit(self.generation, "", "Could not read this file: %s" % exc)
            return

        if size > TEXT_PREVIEW_MAX_BYTES:
            self.contentReady.emit(
                self.generation, "",
                "This file is %.1f MB - too large to preview here (limit "
                "%.0f MB). Open it in another program instead."
                % (size / (1024 * 1024), TEXT_PREVIEW_MAX_BYTES / (1024 * 1024)))
            return

        try:
            with open(self.path, "rb") as f:
                raw = f.read()
        except OSError as exc:
            self.contentReady.emit(self.generation, "", "Could not read this file: %s" % exc)
            return

        # A NUL byte in the first chunk pretty reliably means "not
        # text" - decoding binary data as text just produces unreadable
        # noise, so say so instead of dumping that.
        if b"\x00" in raw[:8192]:
            self.contentReady.emit(
                self.generation, "",
                "This doesn't look like a text file - no preview available.")
            return

        text = None
        for encoding in ("utf-8", "utf-16", "cp1252"):
            try:
                text = raw.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = raw.decode("latin-1")  # never raises

        self.contentReady.emit(self.generation, text, "")


class _PreviewScrollArea(QScrollArea):
    """Adds Ctrl+wheel zoom and end-of-page wheel roll-over to the next
    (or previous) page, on top of QScrollArea's normal scrolling."""

    def __init__(self, pane, parent=None):
        super().__init__(parent)
        self._pane = pane
        self._last_page_turn = 0.0

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self._pane.zoom_in()
            elif delta < 0:
                self._pane.zoom_out()
            event.accept()
            return

        if self._pane.view_mode == "single" and self._pane.page_count > 1:
            bar = self.verticalScrollBar()
            delta = event.angleDelta().y()
            at_top = bar.value() <= bar.minimum()
            at_bottom = bar.value() >= bar.maximum()
            now = time.monotonic()
            turned = False
            if delta < 0 and at_bottom and now - self._last_page_turn > 0.5:
                if self._pane.page_index + 1 < self._pane.page_count:
                    self._last_page_turn = now
                    self._pane.go_next(scroll_to="top")
                    turned = True
            elif delta > 0 and at_top and now - self._last_page_turn > 0.5:
                if self._pane.page_index > 0:
                    self._last_page_turn = now
                    self._pane.go_prev(scroll_to="bottom")
                    turned = True
            if turned:
                event.accept()
                return

        super().wheelEvent(event)


class PreviewPane(QWidget):
    """Shows PDF/DJVU pages, single-page or continuous, with zoom."""

    MIN_ZOOM = 0.25
    MAX_ZOOM = 5.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("FileFinder", "FileFinderApp")
        self.current_path = None
        self.current_kind = None  # "pdf" | "djvu" | "docx" | "doc" | "text"
        self.page_index = 0
        self.page_count = 0
        self.zoom_factor = 1.0
        self.rotation_angle = 0   # 0/90/180/270, clockwise
        self._last_aspect_ratio = 1.294  # sane default (~A4) until a page renders
        self.view_mode = self.settings.value("preview_view_mode", "single")
        if self.view_mode not in ("single", "continuous"):
            self.view_mode = "single"

        self._pending_workers = []   # keep refs alive until they finish
        self._generation = 0         # invalidates stale/in-flight results
        self._pending_scroll_to = None
        self._message_key = None

        self._continuous_container = None
        self._page_labels = {}
        self._page_loaded = set()
        self._page_loading = set()
        # Prevents _check_visible_pages() from running with stale/
        # mid-update geometry - e.g. swapping in a new container or
        # resizing a label can synchronously fire the scrollbar's
        # valueChanged signal, which is otherwise wired straight to
        # _check_visible_pages() and would then read positions that
        # haven't been recomputed yet, causing pages to be sized/
        # positioned against each other inconsistently (visible as
        # pages overlapping instead of having a gap).
        self._updating_layout = False

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._refresh_for_new_render_settings)

        self._build_ui()
        self._sync_mode_buttons()
        self._set_nav_visible(self.view_mode == "single")
        self.clear()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        # No bottom margin: the table sits directly in the splitter
        # with no margin of its own, so its horizontal scrollbar is
        # flush with the splitter's bottom edge. Matching that here
        # (rather than the 4px on every side we use elsewhere) is what
        # keeps the preview's scrollbar aligned with the table's
        # instead of sitting a few pixels above it.
        layout.setContentsMargins(4, 4, 4, 0)

        header = QHBoxLayout()
        self.title_label = QLabel(tr.get("preview_title", "Preview"))
        header.addWidget(self.title_label)

        self.prev_btn = _make_nav_button(
            icon=_triangle_icon("left"), tooltip="Previous page")
        self.prev_btn.clicked.connect(lambda: self.go_prev())
        header.addWidget(self.prev_btn)

        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setMaximum(1)
        self.page_spin.valueChanged.connect(self._on_page_spin_changed)
        header.addWidget(self.page_spin)

        self.page_count_label = QLabel("/ 1")
        header.addWidget(self.page_count_label)

        self.next_btn = _make_nav_button(
            icon=_triangle_icon("right"), tooltip="Next page")
        self.next_btn.clicked.connect(lambda: self.go_next())
        header.addWidget(self.next_btn)

        self.zoom_out_btn = _make_nav_button(
            icon=_magnifier_icon("-"), tooltip="Zoom out (Ctrl+-)")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        header.addWidget(self.zoom_out_btn)

        self.zoom_in_btn = _make_nav_button(
            icon=_magnifier_icon("+"), tooltip="Zoom in (Ctrl++)")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        header.addWidget(self.zoom_in_btn)
        
        self.rotate_left_btn = _make_nav_button(
            icon=_rotate_icon("left"), tooltip="Rotate right")
        self.rotate_left_btn.clicked.connect(self.rotate_right)
        header.addWidget(self.rotate_left_btn)

        self.rotate_right_btn = _make_nav_button(
            icon=_rotate_icon("right"), tooltip="Rotate left")
        self.rotate_right_btn.clicked.connect(self.rotate_left)
        header.addWidget(self.rotate_right_btn)      

        header.addStretch(1)

        self.fit_width_btn = _make_nav_button(
            icon=_frame_fit_icon(True),
            tooltip="Fit page width - page fills the pane's width (Ctrl+0)")
        self.fit_width_btn.clicked.connect(self.fit_width)
        header.addWidget(self.fit_width_btn)

        self.fit_window_btn = _make_nav_button(
            icon=_frame_fit_icon(False),
            tooltip="Fit page to window - the whole page fits without scrolling")
        self.fit_window_btn.clicked.connect(self.fit_window)
        header.addWidget(self.fit_window_btn)

        self.continuous_btn = _make_nav_button(
            icon=_continuous_pages_icon(), checkable=True,
            tooltip="Show pages continuously - scroll through every page in one long view")
        self.continuous_btn.clicked.connect(lambda: self._set_view_mode("continuous"))
        header.addWidget(self.continuous_btn)

        self.single_btn = _make_nav_button(
            icon=_single_page_icon(), checkable=True,
            tooltip="Show a single page - one page at a time")
        self.single_btn.clicked.connect(lambda: self._set_view_mode("single"))
        header.addWidget(self.single_btn)

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.continuous_btn)
        self._mode_group.addButton(self.single_btn)

        layout.addLayout(header)

        self.scroll = _PreviewScrollArea(self)
        # True: the scroll area keeps its content widget's size in sync
        # with its own layout automatically (growing it to fit content
        # larger than the viewport, which is what makes zoom/scrollbars
        # work) - this is what actually keeps continuous-mode pages
        # correctly positioned as they resize from placeholder to real
        # size; the explicit container.resize()/layout().activate()
        # calls elsewhere are kept too as defense in depth, but this
        # property is what makes Qt itself responsible for keeping the
        # container's size right, rather than relying solely on our own
        # imperative resize calls never missing an edge case.
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.verticalScrollBar().valueChanged.connect(self._check_visible_pages)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll, stretch=1)

        # For .docx (rendered as rich text) and the generic "everything
        # else" plain-text fallback - these aren't page-based, so they
        # use their own normal scrolling widget instead of living inside
        # self.scroll (which is tuned for paged zoom/continuous-scroll).
        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self.text_view, stretch=1)
        self.text_view.hide()

        self._set_nav_enabled(False)

        QShortcut(QKeySequence("Ctrl++"), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+="), self, activated=self.zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self, activated=self.zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.zoom_reset)

    # ------------------------------------------------------------------
    def _set_nav_enabled(self, enabled):
        self.prev_btn.setEnabled(enabled)
        self.next_btn.setEnabled(enabled)
        self.page_spin.setEnabled(enabled)

    def _set_nav_visible(self, visible):
        self.prev_btn.setVisible(visible)
        self.next_btn.setVisible(visible)
        self.page_spin.setVisible(visible)
        self.page_count_label.setVisible(visible)


    def _set_paged_controls_visible(self, visible):
        """Prev/Next/zoom/fit/Continuous/Single only make sense for
        page-based content (PDF/DJVU) - hide the lot for .docx/text."""
        self._set_nav_visible(visible and self.view_mode == "single")
        for widget in (self.zoom_out_btn, self.zoom_in_btn,
                       self.rotate_left_btn, self.rotate_right_btn,
                       self.fit_width_btn, self.fit_window_btn,
                       self.continuous_btn, self.single_btn):
            widget.setVisible(visible)

    def _set_content_widget(self, mode):
        """Switch between the paged (PDF/DJVU) scroll area and the
        plain text/rich-text view (.docx and everything else)."""
        self.scroll.setVisible(mode == "paged")
        self.text_view.setVisible(mode == "text")

    def _set_text_view_font(self, monospace):
        self.text_view.setFont(
            QFontDatabase.systemFont(QFontDatabase.FixedFont) if monospace
            else QApplication.font())

    def _sync_mode_buttons(self):
        self.continuous_btn.setChecked(self.view_mode == "continuous")
        self.single_btn.setChecked(self.view_mode == "single")

    def _resolve_djvu_tools_dir(self):
        """A manually-set folder (from an older build without bundled
        binaries) always wins if present; otherwise use the bundled
        location Filefinder.bat's --add-binary lines put ddjvu.exe/
        djvused.exe in, requiring no configuration at all."""
        explicit = self.settings.value("djvu_tools_dir", "") or None
        return explicit or _default_djvu_tools_dir()

    def _bump_generation(self):
        self._generation += 1
        return self._generation

    def _set_scroll_widget(self, widget):
        """Swap the scroll area's contents without deleting anything.

        QScrollArea.setWidget() deletes whatever widget was previously
        set - fine for a one-shot use, but fatal here since we keep our
        own long-lived references (self.image_label,
        self._continuous_container) and swap between them repeatedly.
        take Widget() first detaches the current widget without
        deleting it."""
        self.scroll.takeWidget()
        self.scroll.setWidget(widget)

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------
    def show_message(self, text, message_key=None):
        # message_key remembers which translated message (if any) is
        # currently showing, purely so retranslate_ui() can refresh it
        # in place after a language switch - actual file content isn't
        # tracked this way, only these static placeholder/error strings.
        self._message_key = message_key
        self.current_path = None
        self.current_kind = None
        self._bump_generation()
        self._set_content_widget("paged")
        self._set_paged_controls_visible(False)
        self._set_scroll_widget(self.image_label)
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(text)
        self.image_label.resize(self.image_label.sizeHint())
        self._set_nav_enabled(False)

    def clear(self):
        self.show_message(
            tr.get("preview_select_file", "Select a file to preview it here."),
            message_key="preview_select_file")

    def retranslate_ui(self):
        """Refreshes the "Preview" header and, if a static placeholder/
        error message is currently showing (not real file content), its
        text too - called by MainWindow when the Language dropdown
        changes."""
        self.title_label.setText(tr.get("preview_title", "Preview"))
        if self._message_key:
            key = self._message_key
            default = {
                "preview_select_file": "Select a file to preview it here.",
                "preview_file_not_found": "File not found.",
            }.get(key, "")
            self.show_message(tr.get(key, default), message_key=key)

    def show_file(self, path):
        """Load and preview *path*: PDF/DJVU render as pages, .docx
        renders formatted (needs python-docx), .doc (legacy binary
        format) shows an explanatory message, and everything else shows
        as plain text if it looks like text and isn't too large."""
        if not path or not os.path.exists(path):
            self.show_message(
                tr.get("preview_file_not_found", "File not found."),
                message_key="preview_file_not_found")
            return
        if path == self.current_path:
            return  # already showing it

        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            kind = "pdf"
        elif ext in (".djvu", ".djv"):
            kind = "djvu"
        elif ext == ".docx":
            kind = "docx"
        elif ext == ".doc":
            kind = "doc"
        else:
            kind = "text"

        self.current_path = path
        self.current_kind = kind

        if kind in ("pdf", "djvu"):
            self._set_content_widget("paged")
            self._set_paged_controls_visible(True)
            self.page_index = 0
            self.page_count = 0
            self.image_label.setText("Loading...")
            self.image_label.setPixmap(QPixmap())
            self._set_nav_visible(self.view_mode == "single")
            if self.view_mode == "single":
                self._set_scroll_widget(self.image_label)
            self._bump_generation()
            self._start_page_worker(0, bootstrap=True)
        else:
            self._set_content_widget("text")
            self._set_paged_controls_visible(False)
            self._bump_generation()
            if kind == "docx":
                self._show_docx(path)
            elif kind == "doc":
                self._show_doc_message()
            else:
                self._show_text(path)

    # ------------------------------------------------------------------
    # .docx / plain-text preview
    # ------------------------------------------------------------------
    def _show_docx(self, path):
        generation = self._generation
        self.text_view.setPlainText("Loading...")
        worker = _DocxLoadWorker(generation, path)
        worker.contentReady.connect(self._on_docx_ready)
        self._pending_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()

    def _on_docx_ready(self, generation, html_str, error):
        if generation != self._generation:
            return
        self._set_text_view_font(monospace=False)
        if error:
            self.text_view.setPlainText(error)
        else:
            self.text_view.setHtml(html_str)

    def _show_doc_message(self):
        self._set_text_view_font(monospace=False)
        self.text_view.setPlainText(
            "Legacy .doc files aren't supported by this preview (only "
            "the newer .docx format is). Convert it to .docx, or open "
            "it in Word, to view it.")

    def _show_text(self, path):
        generation = self._generation
        self.text_view.setPlainText("Loading...")
        worker = _TextLoadWorker(generation, path)
        worker.contentReady.connect(self._on_text_ready)
        self._pending_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()

    def _on_text_ready(self, generation, text, error):
        if generation != self._generation:
            return
        self._set_text_view_font(monospace=True)
        self.text_view.setPlainText(error if error else text)

    # ------------------------------------------------------------------
    # Rendering plumbing (shared by single + continuous)
    # ------------------------------------------------------------------
    def _logical_target_width(self):
        logical_width = max(self.scroll.viewport().width(), 320)
        return max(200, int(logical_width * self.zoom_factor) - 8)

    def _target_render_width(self):
        """Device-pixel width to render at: the pane's logical target
        width (accounting for zoom), scaled for the screen's device
        pixel ratio, and oversampled 2x so the final precise downscale
        (never an upscale) is what keeps the result sharp."""
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        width_px = int(self._logical_target_width() * dpr * 2)
        return max(500, min(width_px, 4000))

    def _start_page_worker(self, page_index, bootstrap=False):
        generation = self._generation
        target_width_px = self._target_render_width()
        if self.current_kind == "pdf":
            worker = _PdfPageWorker(generation, self.current_path, page_index, target_width_px)
        else:
            tools_dir = self._resolve_djvu_tools_dir()
            worker = _DjvuPageWorker(
                generation, self.current_path, page_index, tools_dir, target_width_px)

        worker.pageReady.connect(
            lambda gen, idx, pm, cnt, err, b=bootstrap: self._on_worker_result(gen, idx, pm, cnt, err, b))
        # Keep a reference until the thread actually finishes - dropping
        # the last reference to a QThread while it's still running
        # causes a hard crash ("QThread: Destroyed while thread is
        # still running"). Stale/superseded results are simply ignored
        # via the generation check in _on_worker_result.
        self._pending_workers.append(worker)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        worker.start()
        return worker

    def _cleanup_worker(self, worker):
        if worker in self._pending_workers:
            self._pending_workers.remove(worker)
        worker.deleteLater()

    def wait_for_pending(self, timeout_ms=3000):
        """Block briefly for any in-flight render workers to finish, so
        the app can shut down without a 'thread destroyed while running'
        crash. Call this from the main window's closeEvent."""
        for worker in list(self._pending_workers):
            worker.wait(timeout_ms)

    def _on_worker_result(self, generation, page_index, pixmap, page_count, error, bootstrap):
        if generation != self._generation:
            return  # a newer request superseded this one; ignore
        self.page_count = max(self.page_count, page_count, 1)

        if bootstrap and self.view_mode == "continuous":
            self._build_continuous_view()
            self._apply_continuous_result(page_index, pixmap, error)
            QTimer.singleShot(0, self._check_visible_pages)
            return

        if self.view_mode == "continuous":
            self._apply_continuous_result(page_index, pixmap, error)
        else:
            self._apply_single_result(page_index, pixmap, error)

    def _scale_for_display(self, pixmap, target_logical_width):
        if pixmap.width() > 0:
            self._last_aspect_ratio = pixmap.height() / pixmap.width()
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        target_device_width = max(int(target_logical_width * dpr), 1)
        # We deliberately over-rendered (see _target_render_width), so
        # this is a precise downscale, never an upscale - that's what
        # keeps the result sharp instead of blurry.
        if pixmap.width() != target_device_width:
            pixmap = pixmap.scaledToWidth(target_device_width, Qt.SmoothTransformation)
        if self.rotation_angle:
            pixmap = pixmap.transformed(QTransform().rotate(self.rotation_angle), Qt.SmoothTransformation)
        pixmap.setDevicePixelRatio(dpr)
        return pixmap

    # ------------------------------------------------------------------
    # Single-page mode
    # ------------------------------------------------------------------
    def _load_page(self, page_index):
        if not self.current_path:
            return
        self.image_label.setText("Loading...")
        self._set_nav_enabled(False)
        self._bump_generation()
        self._start_page_worker(page_index, bootstrap=False)

    def _apply_single_result(self, page_index, pixmap, error):
        self.page_index = page_index

        if pixmap.isNull():
            self.image_label.setPixmap(QPixmap())
            self.image_label.setText(error or "Could not render this page.")
            self.image_label.resize(self.image_label.sizeHint())
        else:
            pixmap = self._scale_for_display(pixmap, self._logical_target_width())
            self.image_label.setPixmap(pixmap)
            self.image_label.setText("")
            # Let Qt's own sizeHint() (which already accounts for the
            # pixmap's devicePixelRatio internally) size the label,
            # rather than recomputing pixmap.size()/devicePixelRatio()
            # by hand - safer, and avoids the page being clipped if
            # that hand computation is ever off by even a few pixels.
            self.image_label.resize(self.image_label.sizeHint())

        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(max(self.page_count, 1))
        self.page_spin.setValue(self.page_index + 1)
        self.page_spin.blockSignals(False)
        self.page_count_label.setText("/ %d" % self.page_count)
        self._set_nav_enabled(self.page_count > 1)

        if self._pending_scroll_to:
            self._apply_pending_scroll()

    def _apply_pending_scroll(self):
        target = self._pending_scroll_to
        self._pending_scroll_to = None

        def apply():
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.minimum() if target == "top" else bar.maximum())
        QTimer.singleShot(0, apply)

    def go_prev(self, scroll_to=None):
        if self.page_index > 0:
            self._pending_scroll_to = scroll_to
            self._load_page(self.page_index - 1)

    def go_next(self, scroll_to=None):
        if self.page_index + 1 < self.page_count:
            self._pending_scroll_to = scroll_to
            self._load_page(self.page_index + 1)

    def _on_page_spin_changed(self, value):
        target = value - 1
        if target != self.page_index:
            self._load_page(target)

    # ------------------------------------------------------------------
    # Continuous mode
    # ------------------------------------------------------------------
    def _build_continuous_view(self):
        self._updating_layout = True
        try:
            self.scroll.takeWidget()  # detach current widget without deleting it
            if self._continuous_container is not None:
                self._continuous_container.deleteLater()
                self._continuous_container = None

            container = QWidget()
            # A visibly different "workspace" background (like Chrome's or
            # Adobe Reader's continuous-scroll view) makes the gap between
            # pages unmistakable, instead of relying only on QVBoxLayout's
            # invisible spacing - which is easy to miss against a white
            # scroll background even when it IS being applied.
            container.setStyleSheet("background-color: #c8c8c8;")
            vbox = QVBoxLayout(container)
            vbox.setSpacing(0)  # real spacer widgets below do the work instead
            vbox.setContentsMargins(0, PAGE_GAP_PX, 0, PAGE_GAP_PX)

            self._page_labels = {}
            self._page_loaded = set()
            self._page_loading = set()

            target_w = self._logical_target_width()
            count = max(self.page_count, 1)
            for i in range(count):
                lbl = QLabel("Page %d" % (i + 1))
                lbl.setAlignment(Qt.AlignCenter)
                lbl.setStyleSheet(
                    "background-color: white; color: black; border: 1px solid #808080;")
                lbl.setFixedSize(target_w, int(target_w * 1.3))
                vbox.addWidget(lbl, alignment=Qt.AlignHCenter)
                self._page_labels[i] = lbl
                if i != count - 1:
                    spacer = QWidget()
                    spacer.setFixedHeight(PAGE_GAP_PX)
                    vbox.addWidget(spacer)
            vbox.addStretch(1)

            self._continuous_container = container
            self._set_scroll_widget(container)
            # Force an immediate layout pass rather than leaving it for
            # the next paint cycle - _check_visible_pages() (called
            # right after this, via a 0ms timer) reads each label's
            # geometry() to decide what to render next, and needs those
            # positions to already be correct or pages can end up
            # rendered/stacked at stale (overlapping) coordinates.
            vbox.activate()
            # setWidgetResizable(False) means the scroll area does NOT
            # automatically grow this container to fit its layout - do
            # that explicitly, or the container stays at its (smaller)
            # initial size and later items get positioned as if
            # everything above them were still placeholder-sized.
            container.resize(container.sizeHint())
        finally:
            self._updating_layout = False

    def _apply_continuous_result(self, page_index, pixmap, error):
        self._page_loading.discard(page_index)
        lbl = self._page_labels.get(page_index)
        if lbl is None:
            return
        if pixmap.isNull():
            lbl.setText(error or "Could not render this page.")
            return
        self._updating_layout = True
        try:
            pixmap = self._scale_for_display(pixmap, self._logical_target_width())
            # The placeholder (or a previous render at a different zoom
            # level) already called setFixedSize() on this label, which
            # pins minimumSize == maximumSize - sizeHint() would just
            # report that old fixed size back, not the new pixmap's
            # actual size, unless those constraints are lifted first.
            lbl.setMinimumSize(0, 0)
            lbl.setMaximumSize(16777215, 16777215)
            lbl.setPixmap(pixmap)
            # Let Qt's own sizeHint() (which already accounts for the
            # pixmap's devicePixelRatio internally) size the label,
            # rather than recomputing pixmap.size()/devicePixelRatio()
            # by hand - safer, and avoids the page being clipped if
            # that hand computation is ever off by even a few pixels.
            lbl.setFixedSize(lbl.sizeHint())
            self._page_loaded.add(page_index)
            # Same reasoning as in _build_continuous_view(): make the
            # reflow (this page's real height replacing its placeholder
            # guess, which shifts every page below it) happen
            # immediately instead of at the next paint, so positions
            # stay correct/non-overlapping even when several pages
            # finish rendering back-to-back.
            if self._continuous_container is not None:
                self._continuous_container.layout().activate()
                # Same setWidgetResizable(False) reasoning as in
                # _build_continuous_view(): the container doesn't grow
                # on its own just because a child got taller - without
                # this, every page after this one keeps the Y position
                # it would have had if this page were still its
                # (shorter) placeholder size, i.e. they end up
                # overlapping it instead of having a gap.
                self._continuous_container.resize(self._continuous_container.sizeHint())
        finally:
            self._updating_layout = False
        # Now that geometry has actually settled, give visibility
        # checking a legitimate (non-reentrant) chance to run again -
        # this reflow may have pushed a not-yet-loaded page into view.
        QTimer.singleShot(0, self._check_visible_pages)

    def _check_visible_pages(self):
        if self._updating_layout:
            return
        if self.view_mode != "continuous" or not self._page_labels:
            return
        vp_height = self.scroll.viewport().height()
        top = self.scroll.verticalScrollBar().value()
        bottom = top + vp_height
        margin = max(vp_height, 200)  # preload ~1 screen above/below

        for idx, lbl in self._page_labels.items():
            if idx in self._page_loaded or idx in self._page_loading:
                continue
            lbl_top = lbl.geometry().y()
            lbl_bottom = lbl_top + lbl.height()
            if lbl_bottom >= top - margin and lbl_top <= bottom + margin:
                self._page_loading.add(idx)
                self._start_page_worker(idx, bootstrap=False)

    def _topmost_visible_page(self):
        if not self._page_labels:
            return self.page_index
        top = self.scroll.verticalScrollBar().value()
        for idx in sorted(self._page_labels):
            lbl = self._page_labels[idx]
            if lbl.geometry().y() + lbl.height() > top:
                return idx
        return max(self._page_labels)

    def _scroll_to_page(self, page_index):
        lbl = self._page_labels.get(page_index)
        if lbl is not None:
            self.scroll.verticalScrollBar().setValue(lbl.geometry().y())

    # ------------------------------------------------------------------
    # View mode switching
    # ------------------------------------------------------------------
    def _set_view_mode(self, mode):
        if mode == self.view_mode:
            self._sync_mode_buttons()
            return

        if mode == "continuous":
            target_page = self.page_index
            self.view_mode = "continuous"
            self._set_nav_visible(False)
            if self.current_path:
                self._bump_generation()
                self._build_continuous_view()
                self.page_index = target_page

                def after_build():
                    self._scroll_to_page(self.page_index)
                    self._check_visible_pages()
                QTimer.singleShot(0, after_build)
        else:
            target_page = self._topmost_visible_page() if self.current_path else self.page_index
            self.view_mode = "single"
            self._set_nav_visible(True)
            self._set_scroll_widget(self.image_label)
            if self.current_path:
                self.page_index = target_page
                self._bump_generation()
                self._start_page_worker(self.page_index, bootstrap=False)
                self._set_nav_enabled(False)

        self.settings.setValue("preview_view_mode", self.view_mode)
        self._sync_mode_buttons()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------
    def zoom_in(self):
        self._set_zoom(self.zoom_factor * 1.25)

    def zoom_out(self):
        self._set_zoom(self.zoom_factor / 1.25)

    def zoom_reset(self):
        self._set_zoom(1.0)

    def fit_width(self):
        """Page width == pane width - this is what zoom_factor == 1.0
        already means (see _logical_target_width), so it's the same as
        resetting zoom."""
        self._set_zoom(1.0)

    def fit_window(self):
        """Shrink/grow so the *whole* page (width and height) fits the
        pane without needing to scroll, using the last rendered page's
        aspect ratio - there's nothing to measure against before a page
        has actually rendered once, so this falls back to fit_width()."""
        if not self.current_path:
            self.fit_width()
            return
        viewport = self.scroll.viewport()
        vw = max(viewport.width(), 50)
        vh = max(viewport.height(), 50)
        aspect = self._last_aspect_ratio or 1.294  # height / width
        width_for_full_height = vh / aspect
        target_width = min(vw, width_for_full_height)
        self._set_zoom(target_width / vw)

    def _set_zoom(self, factor):
        if self.current_kind not in ("pdf", "djvu"):
            return  # zoom is meaningless for the .docx/text view
        factor = max(self.MIN_ZOOM, min(factor, self.MAX_ZOOM))
        if abs(factor - self.zoom_factor) < 1e-3:
            return
        self.zoom_factor = factor
        self._refresh_for_new_render_settings()
    # ------------------------------------------------------------------
    # Rotate
    # ------------------------------------------------------------------
    def rotate_left(self):
        self.rotation_angle = (self.rotation_angle - 90) % 360
        self._refresh_for_new_render_settings()

    def rotate_right(self):
        self.rotation_angle = (self.rotation_angle + 90) % 360
        self._refresh_for_new_render_settings()
    # ------------------------------------------------------------------
    # Resize / re-render
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Debounce: only actually re-render once the user stops
        # dragging the splitter/resizing the window.
        if self.current_path and self.current_kind in ("pdf", "djvu"):
            self._resize_timer.start(300)

    def _refresh_for_new_render_settings(self):
        if not self.current_path or self.current_kind not in ("pdf", "djvu"):
            return
        self._bump_generation()
        if self.view_mode == "continuous":
            self._build_continuous_view()
            QTimer.singleShot(0, self._check_visible_pages)
        else:
            self._load_page(self.page_index)
