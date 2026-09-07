"""
Background worker that performs the actual file search without freezing
the UI thread. Works either by walking the filesystem live, or - when the
user has built an index and it covers the selected roots - by querying the
SQLite index first and then applying the extra filters in Python.
"""
import fnmatch
import os
import re
import time
import unicodedata

from PyQt5.QtCore import QThread, pyqtSignal

from .index_manager import IndexManager

BATCH_EMIT_SIZE = 40
BATCH_EMIT_INTERVAL = 0.12  # seconds

# A few common accented/special letters that Unicode does NOT decompose
# into "base letter + combining accent" under NFKD (so the general
# unicodedata-based folding below misses them) - fold these explicitly.
_EXTRA_FOLD_MAP = str.maketrans({
    "đ": "d", "Đ": "D",
    "ø": "o", "Ø": "O",
    "ł": "l", "Ł": "L",
    "ß": "ss",
    "æ": "ae", "Æ": "AE",
    "œ": "oe", "Œ": "OE",
})


def fold_accents(text):
    """'Ćirić' -> 'Ciric', 'Đorđe' -> 'Dorde', etc. - strips accents/
    diacritics so accented and unaccented spellings match each other."""
    if not text:
        return text
    text = text.translate(_EXTRA_FOLD_MAP)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


class SearchWorker(QThread):
    resultsReady = pyqtSignal(list)          # list[dict]
    progress = pyqtSignal(int, str)          # scanned count, current path
    finished_search = pyqtSignal(int, int, float)  # scanned, matched, elapsed
    error = pyqtSignal(str)

    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = params
        self._stop = False

    def stop(self):
        self._stop = True

    # ---- matching helpers -------------------------------------------------
    def _build_matcher(self):
        pattern = self.params.get("pattern", "").strip()
        case_sensitive = self.params.get("match_case", False)
        whole_words = self.params.get("whole_words", False)
        # "Accents" checked -> match accents exactly (accent-sensitive).
        # Unchecked (default) -> accented/unaccented spellings match the
        # same way, e.g. "Ciric" also finds "\u0106iri\u0107".
        ignore_accents = not self.params.get("match_accents", False)
        word_mode = self.params.get("word_mode", "all")  # all | phrase | any
        exclude_text = (self.params.get("exclude_text") or "").strip()
        mode = self.params.get("mode", "contains")  # contains | wildcard | regex

        flags = 0 if case_sensitive else re.IGNORECASE

        def fold(text):
            # Accent-folding is a search convenience (Cric == Ćirić);
            # it doesn't make sense to silently rewrite an explicit
            # regex the user wrote themselves, so it's not applied
            # there - see the regex branch below.
            return fold_accents(text) if ignore_accents else text

        def word_pattern(word):
            escaped = re.escape(fold(word))
            return r"\b%s\b" % escaped if whole_words else escaped

        # "No words" exclusion filter - independent of the main pattern
        # and of which mode/word-mode is selected above. A "quoted"
        # value excludes that exact phrase; an unquoted value excludes
        # each space-separated word on its own (matches if the name
        # contains any of them).
        exclude_fn = None
        if exclude_text:
            if (len(exclude_text) >= 2 and exclude_text.startswith('"')
                    and exclude_text.endswith('"')):
                try:
                    compiled_exclude = re.compile(
                        word_pattern(exclude_text[1:-1]), flags)
                except re.error as exc:
                    raise ValueError("Invalid \u201cNo words\u201d text: %s" % exc)
            else:
                exclude_words = [w for w in exclude_text.split() if w]
                try:
                    compiled_exclude = re.compile(
                        "|".join(word_pattern(w) for w in exclude_words), flags)
                except re.error as exc:
                    raise ValueError("Invalid \u201cNo words\u201d text: %s" % exc)
            exclude_fn = lambda name: compiled_exclude.search(fold(name)) is not None

        def combine(base):
            if exclude_fn is None:
                return base
            return lambda name: base(name) and not exclude_fn(name)

        if not pattern:
            return combine(lambda name: True)

        # Typing "*" or "?" means "wildcard search" regardless of which
        # mode is selected in the dropdown - e.g. "*iric" should just
        # work without switching to Wildcard mode first.
        if mode == "contains" and ("*" in pattern or "?" in pattern):
            mode = "wildcard"

        if mode == "regex":
            try:
                compiled = re.compile(pattern, flags)
            except re.error as exc:
                raise ValueError("Invalid regular expression: %s" % exc)
            return combine(lambda name: compiled.search(name) is not None)

        if mode == "wildcard":
            wpattern = pattern
            if "*" not in wpattern and "?" not in wpattern:
                wpattern = "*%s*" % wpattern
            else:
                # A wildcard pattern is treated as "these pieces appear
                # in this order somewhere in the name", like a normal
                # search box - not fnmatch's strict "must match the
                # *entire* name" behaviour, which would silently require
                # e.g. "Ciric*s contraction" to end exactly with "s
                # contraction" (excluding a file extension after it) or
                # "*iric" to end exactly with "iric". Padding with "*"
                # at whichever end doesn't already have one makes both
                # ends open instead.
                if not wpattern.startswith("*"):
                    wpattern = "*" + wpattern
                if not wpattern.endswith("*"):
                    wpattern = wpattern + "*"
            wpattern = fold(wpattern)
            regex_pattern = fnmatch.translate(wpattern)
            compiled = re.compile(regex_pattern, flags)
            return combine(lambda name: compiled.match(fold(name)) is not None)

        # "contains" mode: apply the All words / Exact phrase / Any word
        # matching selected in the Filters box.
        words = [w for w in pattern.split() if w] or [pattern]

        if word_mode == "phrase" or len(words) <= 1:
            try:
                compiled = re.compile(word_pattern(pattern), flags)
            except re.error as exc:
                raise ValueError("Invalid search text: %s" % exc)
            found = lambda name: compiled.search(fold(name)) is not None
        elif word_mode == "any":
            try:
                compiled = re.compile(
                    "|".join(word_pattern(w) for w in words), flags)
            except re.error as exc:
                raise ValueError("Invalid search text: %s" % exc)
            found = lambda name: compiled.search(fold(name)) is not None
        else:  # "all"
            try:
                compiled_all = [
                    re.compile(word_pattern(w), flags) for w in words]
            except re.error as exc:
                raise ValueError("Invalid search text: %s" % exc)
            found = lambda name: all(c.search(fold(name)) for c in compiled_all)

        return combine(found)

    def _passes_filters(self, name, size, mtime):
        p = self.params

        ext_filter = p.get("extensions")  # set of lowercase extensions or None
        if ext_filter:
            ext = os.path.splitext(name)[1].lower()
            if ext not in ext_filter:
                return False

        min_size = p.get("min_size_bytes")
        if min_size is not None and (size is None or size < min_size):
            return False
        max_size = p.get("max_size_bytes")
        if max_size is not None and (size is None or size > max_size):
            return False

        date_from = p.get("date_from_ts")
        if date_from is not None and (mtime is None or mtime < date_from):
            return False
        date_to = p.get("date_to_ts")
        if date_to is not None and (mtime is None or mtime > date_to):
            return False

        return True

    def _make_record(self, path, name, dirpath, size, mtime):
        ext = os.path.splitext(name)[1].lower()
        # os.walk() only normalizes the separators it adds itself when
        # descending into subfolders - the root prefix keeps whatever
        # slash style the user typed/picked (e.g. "C:/Folder1"), so a
        # file two levels down could show up as
        # "C:/Folder1\\Folder2\\file.pdf". normpath() makes the whole
        # thing consistent (native separators, e.g. all "\\" on Windows).
        path = os.path.normpath(path)
        dirpath = os.path.normpath(dirpath)
        return {
            "path": path,
            "name": name,
            "dir": dirpath,
            "ext": ext,
            "size": size,
            "mtime": mtime,
        }

    # ---- main run -----------------------------------------------------
    def run(self):
        start = time.time()
        scanned = 0
        matched = 0
        batch = []
        last_emit = start

        try:
            matcher = self._build_matcher()
        except ValueError as exc:
            self.error.emit(str(exc))
            self.finished_search.emit(0, 0, 0.0)
            return

        try:
            if self.params.get("use_index"):
                scanned, matched = self._run_indexed(matcher, batch)
            else:
                scanned, matched = self._run_live(matcher, batch, start)
        except Exception as exc:  # pragma: no cover - defensive
            self.error.emit(str(exc))

        if batch:
            self.resultsReady.emit(batch)

        elapsed = time.time() - start
        self.finished_search.emit(scanned, matched, elapsed)

    def _run_live(self, matcher, batch, start):
        p = self.params
        roots = p.get("roots", [])
        include_subfolders = p.get("include_subfolders", True)
        scanned = 0
        matched = 0
        last_emit = start

        for root in roots:
            if self._stop:
                break
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
                if self._stop:
                    break
                if not include_subfolders and os.path.normpath(dirpath) != os.path.normpath(root):
                    dirnames[:] = []
                    continue
                for fname in filenames:
                    if self._stop:
                        break
                    scanned += 1
                    if matcher(fname):
                        full = os.path.join(dirpath, fname)
                        try:
                            st = os.stat(full)
                            size, mtime = st.st_size, st.st_mtime
                        except OSError:
                            size, mtime = None, None
                        if self._passes_filters(fname, size, mtime):
                            matched += 1
                            batch.append(self._make_record(full, fname, dirpath, size, mtime))
                    now = time.time()
                    if len(batch) >= BATCH_EMIT_SIZE or (batch and now - last_emit >= BATCH_EMIT_INTERVAL):
                        self.resultsReady.emit(batch[:])
                        batch.clear()
                        last_emit = now
                    if scanned % 500 == 0:
                        self.progress.emit(scanned, dirpath)
        return scanned, matched

    def _run_indexed(self, matcher, batch):
        p = self.params
        roots = p.get("roots", [])
        pattern = p.get("pattern", "").strip()
        mode = p.get("mode", "contains")
        case_sensitive = p.get("match_case", False)
        ignore_accents = not p.get("match_accents", False)
        has_wildcard = "*" in pattern or "?" in pattern

        index = IndexManager()
        # For a single-word, exact-phrase-equivalent "contains" search
        # with no accent-folding, no whole-word requirement, no "no
        # words" negation, and no wildcard characters, SQLite can narrow
        # the rows itself before we even look at them in Python - much
        # faster on a big index. Any of those make the SQL LIKE
        # narrowing unsafe (it would exclude rows that should match), so
        # skip it and let the Python matcher see every indexed row
        # instead.
        name_query = ""
        if (mode == "contains" and not case_sensitive and not ignore_accents
                and not p.get("whole_words", False)
                and not has_wildcard and pattern
                and len(pattern.split()) <= 1):
            name_query = pattern.lower()

        rows = index.search(roots, name_query)
        scanned = len(rows)
        matched = 0
        last_emit = time.time()

        for path, name, dirpath, ext, size, mtime in rows:
            if self._stop:
                break
            if matcher(name) and self._passes_filters(name, size, mtime):
                matched += 1
                batch.append(self._make_record(path, name, dirpath, size, mtime))
            now = time.time()
            if len(batch) >= BATCH_EMIT_SIZE or (batch and now - last_emit >= BATCH_EMIT_INTERVAL):
                self.resultsReady.emit(batch[:])
                batch.clear()
                last_emit = now

        self.progress.emit(scanned, "")
        return scanned, matched


class IndexBuildWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_build = pyqtSignal(int, float)
    error = pyqtSignal(str)

    def __init__(self, roots, parent=None):
        super().__init__(parent)
        self.roots = roots
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        start = time.time()
        index = IndexManager()
        try:
            total = index.build_index(
                self.roots,
                progress_callback=lambda n, path: self.progress.emit(n, path),
                should_stop=lambda: self._stop,
            )
        except Exception as exc:  # pragma: no cover
            self.error.emit(str(exc))
            total = 0
        elapsed = time.time() - start
        self.finished_build.emit(total, elapsed)
