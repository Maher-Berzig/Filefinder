"""
Gives access to the *real* Windows Explorer right-click menu for one or
more files - the same menu (including entries added by other installed
programs, e.g. "7-Zip", "Scan with...", "Send to", etc.) you'd get by
right clicking the file in Explorer itself - so it can be merged
directly into File Finder's own QMenu instead of being shown as a
separate popup.

Only works on Windows and requires pywin32 (``pip install pywin32``).
On any other platform, or if pywin32 is not installed, `is_available()`
returns False.

This uses the classic IShellFolder / IContextMenu COM approach:
    1. Get the IShellFolder for the parent directory of the file(s).
    2. Get the relative PIDL(s) of the file(s) inside that folder.
    3. Ask the shell folder for an IContextMenu for those PIDLs.
    4. Build a native (invisible) HMENU from it (QueryContextMenu) and
       walk it item by item with GetMenuItemInfo/win32gui_struct,
       turning it into a plain list of dicts that main_window.py turns
       into QActions.
    5. When one of those QActions is triggered, InvokeCommand runs
       whatever the user picked - exactly like Explorer would.
"""
import os

from PyQt5.QtGui import QIcon, QImage, QPixmap

from . import utils

IS_WINDOWS = utils.IS_WINDOWS

IDCMD_FIRST = 1
IDCMD_LAST = 0x7FFF

_import_error = None
if IS_WINDOWS:
    try:
        import ctypes
        from ctypes import wintypes
        import win32con
        import win32gui
        import win32gui_struct
        import win32com.shell.shell as shell
        import win32com.shell.shellcon as shellcon
    except Exception as exc:  # pragma: no cover - depends on host install
        _import_error = str(exc)
else:  # pragma: no cover - depends on host OS
    _import_error = "Native context menu is only available on Windows."


def is_available():
    return IS_WINDOWS and _import_error is None


def unavailable_reason():
    return _import_error or ""


def _first_value(result):
    """pywin32's ParseDisplayName returns a tuple whose *order* varies by
    pywin32/Windows build - some return (pidl, attrs), others return
    (charsEaten, pidl, attrs) with the eaten-character count (a plain
    int) first. Blindly taking element 0 sometimes grabbed that int
    instead of the PIDL, which then blew up deeper in BindToObject with
    "Only sequences (but not strings) are valid ITEMIDLIST objects".
    A PIDL is always a sequence, never a bare int, so pick the first
    non-int element instead - this works regardless of the ordering."""
    if isinstance(result, tuple):
        for item in result:
            if not isinstance(item, int):
                return item
        return result[0]
    return result


def _get_interface(result, method_name):
    """Extract a COM interface from pywin32's varying return forms.

    Several Shell methods (notably GetUIObjectOf) sometimes hand back
    the interface directly and sometimes wrap it in a tuple depending
    on the pywin32/Windows build - mirrors the same variability that
    _first_value() works around for ParseDisplayName."""
    if isinstance(result, tuple):
        for item in result:
            if hasattr(item, method_name):
                return item
        for item in result:
            if not isinstance(item, int):
                return item
        return None
    return result


# ----------------------------------------------------------------------
# Icon extraction: shell context menu items expose their icon as a plain
# HBITMAP handle (via GetMenuItemInfo's MIIM_BITMAP), which we convert
# to a QIcon by pulling the raw pixel bytes out with GDI's GetDIBits and
# wrapping them in a QImage. Many shell extensions instead use an
# owner-drawn bitmap (a sentinel handle that only resolves to real
# pixels via WM_DRAWITEM while Explorer's own message loop is running,
# which we don't have here since we never actually display the native
# popup) - for those, GetObject simply fails and we skip the icon,
# which is why some entries may end up without one ("if it exists", as
# requested - this is best-effort, not guaranteed for every item).
if IS_WINDOWS and _import_error is None:
    class _BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", ctypes.c_long),
            ("bmWidth", ctypes.c_long),
            ("bmHeight", ctypes.c_long),
            ("bmWidthBytes", ctypes.c_long),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", ctypes.c_void_p),
        ]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    _gdi32 = ctypes.windll.gdi32
    _user32 = ctypes.windll.user32


def _hbitmap_to_qicon(hbmp):
    """Best-effort HBITMAP -> QIcon. Returns None on any failure (a
    bogus/owner-draw sentinel handle, an unusual pixel format, etc.) -
    never raises, since a missing icon just means that one menu entry
    is shown without one."""
    if not IS_WINDOWS or _import_error is not None or not hbmp:
        return None
    try:
        bmp = _BITMAP()
        if not _gdi32.GetObjectW(hbmp, ctypes.sizeof(_BITMAP), ctypes.byref(bmp)):
            return None
        width, height = bmp.bmWidth, bmp.bmHeight
        if width <= 0 or height <= 0 or width > 256 or height > 256:
            return None

        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # negative = top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        hdc = _user32.GetDC(None)
        if not hdc:
            return None
        try:
            got = _gdi32.GetDIBits(hdc, hbmp, 0, height, buf, ctypes.byref(bmi), 0)
        finally:
            _user32.ReleaseDC(None, hdc)
        if not got:
            return None

        image = QImage(bytes(buf.raw), width, height, QImage.Format_ARGB32_Premultiplied)
        if image.isNull():
            return None
        pixmap = QPixmap.fromImage(image.copy())
        return None if pixmap.isNull() else QIcon(pixmap)
    except Exception:
        return None


def get_context_menu(hwnd, paths):
    """Build a native IContextMenu + HMENU for *paths* (must all live in
    the same folder). Returns (context_menu_com_obj, hmenu, error).

    On success the caller owns ``hmenu`` and must eventually call
    ``destroy_menu(hmenu)``. ``context_menu_com_obj`` must be kept alive
    (i.e. referenced) for as long as any command from the menu might
    still be invoked.
    """
    if not is_available():
        return None, None, _import_error or "Native context menu unavailable."
    if not paths:
        return None, None, "Nothing selected."

    paths = [os.path.normpath(p) for p in paths]
    folder = os.path.dirname(paths[0])
    names = [os.path.basename(p) for p in paths]

    try:
        desktop = shell.SHGetDesktopFolder()
        folder_pidl = _first_value(desktop.ParseDisplayName(hwnd, None, folder))
        folder_obj = desktop.BindToObject(folder_pidl, None, shell.IID_IShellFolder)
        folder_obj = _get_interface(folder_obj, "ParseDisplayName")
        if folder_obj is None or not hasattr(folder_obj, "ParseDisplayName"):
            return None, None, (
                "BindToObject did not return a usable IShellFolder object.")

        rel_pidls = [
            _first_value(folder_obj.ParseDisplayName(hwnd, None, name))
            for name in names
        ]

        context_menu = folder_obj.GetUIObjectOf(
            hwnd, rel_pidls, shell.IID_IContextMenu, 0)
        context_menu = _get_interface(context_menu, "QueryContextMenu")
        if context_menu is None or not hasattr(context_menu, "QueryContextMenu"):
            return None, None, (
                "GetUIObjectOf did not return a usable IContextMenu object.")

        hmenu = win32gui.CreatePopupMenu()
        context_menu.QueryContextMenu(
            hmenu, 0, IDCMD_FIRST, IDCMD_LAST,
            shellcon.CMF_NORMAL | shellcon.CMF_EXPLORE)

        return context_menu, hmenu, ""
    except Exception as exc:
        return None, None, str(exc)


def read_menu_items(hmenu):
    """Recursively turn a native HMENU into a plain list of dicts:
    {"text": str, "separator": bool, "disabled": bool,
     "id": int or None, "submenu": [items] or None, "icon": QIcon or None}
    Safe to call on any HMENU; never raises (returns [] on failure).
    """
    if not hmenu:
        return []
    items = []
    try:
        count = win32gui.GetMenuItemCount(hmenu)
    except Exception:
        return []

    mask = (win32con.MIIM_ID | win32con.MIIM_STRING | win32con.MIIM_SUBMENU |
            win32con.MIIM_FTYPE | win32con.MIIM_STATE)
    try:
        mask |= win32con.MIIM_BITMAP
    except AttributeError:  # pragma: no cover - depends on pywin32 build
        pass

    for i in range(count):
        try:
            buf, extra = win32gui_struct.EmptyMENUITEMINFO(mask=mask)
            win32gui.GetMenuItemInfo(hmenu, i, True, buf)
            (fType, fState, wID, hSubMenu, _chk, _unchk,
             _data, text, hbmpItem) = win32gui_struct.UnpackMENUITEMINFO(buf)
        except Exception:
            continue

        is_sep = bool(fType & win32con.MFT_SEPARATOR)
        disabled = bool(fState & (win32con.MFS_DISABLED | win32con.MFS_GRAYED))
        clean_text = (text or "").replace("&", "")

        items.append({
            "text": clean_text,
            "separator": is_sep,
            "disabled": disabled,
            "id": wID,
            "submenu": read_menu_items(hSubMenu) if hSubMenu else None,
            "icon": None if is_sep else _hbitmap_to_qicon(hbmpItem),
        })
    return items


def invoke_command(context_menu, hwnd, cmd_id):
    """Run the command with the given absolute menu id (as read from
    read_menu_items()'s "id" field)."""
    try:
        invoke_info = (hwnd, 0, cmd_id - IDCMD_FIRST, None, None, 0, 0, 0)
        context_menu.InvokeCommand(invoke_info)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def destroy_menu(hmenu):
    if hmenu:
        try:
            win32gui.DestroyMenu(hmenu)
        except Exception:
            pass
