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


_AND_WORDS = {"AND", "+", "&", "&&"}
_OR_WORDS = {"OR", "|", "||"}
_NOT_WORDS = {"NOT", "!"}


def tokenize_query(text):
    """Split a search query into tokens for the Boolean expression
    parser. Each token is (kind, value, is_path, is_quoted) where kind
    is "TERM", "AND", "OR", "NOT", "(" or ")".

    Operators: AND / OR / NOT (upper-case, so ordinary words like "and"
    stay words), or the symbols + (AND), | (OR), ! and a leading - (NOT).
    "quoted text" is an exact phrase. A term starting with / or \\ is a
    *path term*: it is matched against the whole file path, not only the
    file name (e.g. \\books, or \\docs\\2024).
    """
    tokens = []
    i, n = 0, len(text)

    def add_term(word, quoted=False):
        is_path = (not quoted) and word[:1] in ("/", "\\")
        if is_path:
            word = word[1:].replace("/", os.sep).replace("\\", os.sep)
        tokens.append(("TERM", word, is_path, quoted))

    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == '"':
            j = text.find('"', i + 1)
            if j == -1:
                j = n
            add_term(text[i + 1:j], quoted=True)
            i = j + 1
            continue
        if c in "()":
            tokens.append((c, c, False, False))
            i += 1
            continue
        j = i
        while j < n and not text[j].isspace() and text[j] not in '"()':
            j += 1
        word = text[i:j]
        i = j
        if word in _AND_WORDS:
            tokens.append(("AND", word, False, False))
        elif word in _OR_WORDS:
            tokens.append(("OR", word, False, False))
        elif word in _NOT_WORDS:
            tokens.append(("NOT", word, False, False))
        elif len(word) > 1 and word[0] in "-!":
            tokens.append(("NOT", word[0], False, False))
            add_term(word[1:])
        elif len(word) > 1 and word[0] == "+":
            add_term(word[1:])
        else:
            add_term(word)
    return tokens


def query_needs_expression(tokens):
    """True when the query uses any Boolean operator, quoted phrase or
    path term - i.e. when the plain word-list matching isn't enough."""
    for kind, _value, is_path, quoted in tokens:
        if kind in ("AND", "OR", "NOT") or is_path or quoted:
            return True
    return False


class _ExpressionParser(object):
    """Recursive-descent parser: OR (lowest) < AND < NOT (highest),
    parentheses group. Two terms side by side are joined with AND, or
    with OR when the Filters box is set to "Any word"."""

    def __init__(self, tokens, any_mode, leaf):
        self.tokens = tokens
        self.pos = 0
        self.any_mode = any_mode
        self.leaf = leaf

    def _peek(self):
        return self.tokens[self.pos][0] if self.pos < len(self.tokens) else None

    def _starts_operand(self):
        return self._peek() in ("TERM", "NOT", "(")

    def parse(self):
        if not self.tokens:
            return lambda subject: True
        node = self._or_expr()
        if self.pos < len(self.tokens):
            raise ValueError("Invalid search expression: unexpected \u201c%s\u201d" %
                             self.tokens[self.pos][1])
        return node

    def _or_expr(self):
        left = self._and_expr()
        while True:
            kind = self._peek()
            if kind == "OR":
                self.pos += 1
            elif not (self.any_mode and self._starts_operand()):
                break
            right = self._and_expr()
            left = (lambda a, b: lambda s: a(s) or b(s))(left, right)
        return left

    def _and_expr(self):
        left = self._unary()
        while True:
            kind = self._peek()
            if kind == "AND":
                self.pos += 1
            elif not (not self.any_mode and self._starts_operand()):
                break
            right = self._unary()
            left = (lambda a, b: lambda s: a(s) and b(s))(left, right)
        return left

    def _unary(self):
        kind = self._peek()
        if kind == "NOT":
            self.pos += 1
            inner = self._unary()
            return lambda s: not inner(s)
        if kind == "(":
            self.pos += 1
            node = self._or_expr()
            if self._peek() != ")":
                raise ValueError("Invalid search expression: missing \u201c)\u201d")
            self.pos += 1
            return node
        if kind == "TERM":
            _k, value, _p, quoted = self.tokens[self.pos]
            self.pos += 1
            return self.leaf(value, quoted)
        raise ValueError("Invalid search expression: a search term is missing "
                         "after an operator")


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
        # Boolean / path expression (AND, OR, NOT, +, |, -, quotes,
        # parentheses, and "/folder" or "\\folder" path terms). Only
        # used when the query actually contains such syntax; plain
        # queries keep the original matching below. If any path term is
        # present, every term is matched against the full path (which
        # contains the file name too), so term order doesn't matter.
        expr_tokens = None
        path_mode = False
        if mode != "regex":
            toks = tokenize_query(pattern)
            if query_needs_expression(toks):
                expr_tokens = toks
                path_mode = any(t[0] == "TERM" and t[2] for t in toks)

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
            # The returned matcher takes (name, dirpath). In path mode
            # the main pattern is tested against the full path; the
            # "No words" exclusion always looks at the file name only.
            def run(name, dirpath=None):
                if path_mode and dirpath is not None:
                    subject = os.path.normpath(os.path.join(dirpath, name))
                else:
                    subject = name
                if not base(subject):
                    return False
                return not (exclude_fn is not None and exclude_fn(name))
            return run

        if not pattern:
            return combine(lambda name: True)

        if expr_tokens is not None:
            def leaf(value, quoted):
                value = value.strip()
                if not value:
                    return lambda subject: True
                try:
                    if not quoted and ("*" in value or "?" in value):
                        wp = value
                        if not wp.startswith("*"):
                            wp = "*" + wp
                        if not wp.endswith("*"):
                            wp = wp + "*"
                        rx = re.compile(fnmatch.translate(fold(wp)), flags)
                        return lambda subject: rx.match(subject) is not None
                    rx = re.compile(word_pattern(value), flags)
                except re.error as exc:
                    raise ValueError("Invalid search text: %s" % exc)
                return lambda subject: rx.search(subject) is not None

            tree = _ExpressionParser(
                expr_tokens, word_mode == "any", leaf).parse()
            # Accent-fold the subject once, then test every term on it.
            return combine(lambda subject: tree(fold(subject)))

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
                    if matcher(fname, dirpath):
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
        toks = tokenize_query(pattern) if mode != "regex" else []
        uses_expression = query_needs_expression(toks)
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
        # Boolean / path expressions can't be narrowed by one name
        # substring (a term may only appear in the folder part, or be
        # negated), so they scan every row.
        if (not uses_expression and mode == "contains" and not case_sensitive and not ignore_accents
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
            if matcher(name, dirpath) and self._passes_filters(name, size, mtime):
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
