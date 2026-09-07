#!/usr/bin/env python
"""
Convert app/translations.py between plain UTF-8 (real characters - easy to
read and edit) and pure ASCII (\\uXXXX escapes for every non-ASCII
character - safe for tools/editors/pipelines that only handle ASCII
source files). Both forms are exactly equivalent Python source: importing
either one gives the identical strings at runtime, since Python decodes
\\uXXXX escapes inside string literals automatically while parsing the
file.

Only the two built-in string methods str.encode()/str.decode() are used
to do the actual conversion (see utf8_to_ascii/ascii_to_utf8 below) - no
external dependencies.

Usage:
    python tools/translations_codec.py to-ascii
    python tools/translations_codec.py to-utf8

By default both commands read and write app/translations.py in place (a
timestamped backup of the previous content is written alongside it first,
so nothing is lost by accident). Use --in/--out to operate on different
files instead, e.g. to preview the result without touching the original:

    python tools/translations_codec.py to-ascii --out /tmp/ascii_preview.py
"""
import argparse
import os
import re
import shutil
import sys
import time

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "translations.py")

_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def utf8_to_ascii(text):
    """Escape every non-ASCII character in `text` to its \\uXXXX form
    using str.encode('unicode_escape'), leaving every ASCII character
    (including existing backslashes and quotes, e.g. the \\" in
    no_words_placeholder) exactly as it was. The result is plain ASCII
    and is still valid, equivalent Python source."""
    return "".join(
        ch if ord(ch) < 128 else ch.encode("unicode_escape").decode("ascii")
        for ch in text
    )


def ascii_to_utf8(text):
    """Reverse of utf8_to_ascii(): turn literal \\uXXXX escapes back into
    real UTF-8 characters, using int()/chr() rather than a blanket
    str.decode('unicode_escape') so that other backslash escapes already
    in the file (\\", \\n, ...) are left completely untouched instead of
    being (re)interpreted."""
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


def _backup(path):
    if not os.path.exists(path):
        return
    backup_path = "%s.%s.bak" % (path, time.strftime("%Y%m%d%H%M%S"))
    shutil.copy2(path, backup_path)
    print("Backed up existing file to %s" % backup_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("direction", choices=["to-ascii", "to-utf8"],
                         help="to-ascii: escape non-ASCII characters to \\uXXXX. "
                              "to-utf8: turn \\uXXXX escapes back into real characters.")
    parser.add_argument("--in", dest="in_path", default=DEFAULT_PATH,
                         help="File to read (default: app/translations.py)")
    parser.add_argument("--out", dest="out_path", default=None,
                         help="File to write (default: same as --in, edited in place)")
    parser.add_argument("--no-backup", action="store_true",
                         help="Skip writing a .bak copy before overwriting --out")
    args = parser.parse_args()

    out_path = args.out_path or args.in_path

    with open(args.in_path, "r", encoding="utf-8") as f:
        content = f.read()

    if args.direction == "to-ascii":
        result = utf8_to_ascii(content)
    else:
        result = ascii_to_utf8(content)

    if out_path == args.in_path and not args.no_backup:
        _backup(out_path)

    # Written as UTF-8 either way - for the "to-ascii" result this is a
    # no-op (the text is pure ASCII, a subset of UTF-8), and it's the
    # correct encoding to use for the "to-utf8" result.
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)

    print("Wrote %s (%s)" % (out_path, args.direction))


if __name__ == "__main__":
    sys.exit(main())
