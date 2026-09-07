#!/usr/bin/env python
"""
File Finder - a fast, lightweight file search tool built with PyQt5.

Designed to run on Windows 7 (32-bit) with Python 3.8, but also runs fine
on newer Windows, Linux and macOS for development/testing.

Usage:
    python main.py
"""
import os
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QFont
from PyQt5.QtCore import Qt, QSettings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main_window import MainWindow  # noqa: E402
from app.single_instance import SingleInstance  # noqa: E402

# Must be set before QApplication is constructed. Without these, Qt can
# report a device pixel ratio of 1.0 on HiDPI/scaled Windows displays
# (typical 125%/150% scaling) and/or bitmap-scale already-rendered
# pixmaps instead of using the sharp ones the preview pane produces -
# both look "blurry".
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def _folder_from_args(args):
    """Explorer's "Open with File Finder" context menu entry (see
    README.md's "Explorer context menu" section) launches File Finder
    as ``FileFinder.exe "C:\\path\\to\\folder"``, i.e. the folder as a
    plain positional argument. Returns that folder if present/valid."""
    for arg in args:
        if arg.startswith("-") or arg.startswith("/"):
            continue
        candidate = os.path.normpath(arg)
        if os.path.isdir(candidate):
            return candidate
    return None


def _wants_tray_start(args):
    """True if launched with a "start minimized to the tray" flag, as
    used by the "Run automatically when Windows starts" installer task
    (see installer/Filefinder.iss) - accepts the Windows-style "/tray"
    it actually passes, plus "--tray"/"-tray" for anyone invoking
    main.py directly."""
    flags = {a.lower() for a in args}
    return bool(flags & {"/tray", "--tray", "-tray"})


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("File Finder")
    app.setOrganizationName("FileFinder")
    # Keep running in the tray after the main window is closed/hidden.
    app.setQuitOnLastWindowClosed(False)

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    folder = _folder_from_args(sys.argv[1:])
    tray_start = _wants_tray_start(sys.argv[1:])

    # If File Finder is already running, forward this launch's folder
    # (from an "Open with File Finder" Explorer click) to it and stop -
    # otherwise every click spawned a whole new process, each with its
    # own tray icon piling up next to the last one.
    instance = SingleInstance()
    if instance.try_forward_to_existing(folder):
        return
    instance.start_listening()

    # Stash Qt's own default font before we possibly override it below,
    # so Options > Default can restore *that* rather than whatever font
    # happened to be active when it was clicked.
    app.ff_default_font = QFont(app.font())

    # Apply a previously chosen UI font (Options > Choose Font...) before
    # any widget is built, so the window opens with it right away
    # instead of flashing the default font first.
    settings = QSettings("FileFinder", "FileFinderApp")
    font_str = settings.value("ui_font", "")
    if font_str:
        font = QFont()
        if font.fromString(font_str):
            app.setFont(font)

    window = MainWindow(initial_folder=folder)
    instance.folderRequested.connect(window.handle_folder_request)
    instance.showRequested.connect(window.handle_show_request)

    # Launched at Windows startup (installer's "Run automatically when
    # Windows starts" task, via /tray) - stay in the system tray only,
    # don't pop the main window open. If there's no tray available for
    # some reason, show the window anyway so the app isn't invisible
    # with no way to reach it.
    if not (tray_start and window.tray_icon is not None):
        window.show()
        window.showMaximized()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
