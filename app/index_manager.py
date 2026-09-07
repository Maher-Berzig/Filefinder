"""
Lightweight persistent file index backed by SQLite.

The very first search over a big drive always has to touch the disk, but
once an index has been built, repeat searches (and searches while the
index is fresh) are answered straight out of SQLite in a fraction of a
second - similar in spirit to tools like "Everything", just without
needing the NTFS USN journal / admin rights.
"""
import os
import sqlite3
import time

APP_DIR_NAME = "FileFinder"


def get_app_data_dir():
    """Return (and create) a per-user folder to store the index database."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = os.path.join(base, APP_DIR_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


class IndexManager(object):
    def __init__(self, db_path=None):
        self.db_path = db_path or os.path.join(get_app_data_dir(), "file_index.db")
        self._ensure_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _ensure_schema(self):
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    name_lower TEXT NOT NULL,
                    dir TEXT NOT NULL,
                    ext TEXT,
                    size INTEGER,
                    mtime REAL,
                    root TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_name_lower ON files(name_lower)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_root ON files(root)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    root TEXT PRIMARY KEY,
                    last_build REAL,
                    file_count INTEGER
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def build_index(self, roots, progress_callback=None, should_stop=None):
        """
        Walk every folder under `roots` and (re)build the index for those
        roots. `progress_callback(scanned_count, current_path)` is called
        periodically. `should_stop()` should return True to abort early.
        Returns the total number of files indexed.
        """
        conn = self._connect()
        cur = conn.cursor()
        total = 0
        batch = []
        BATCH_SIZE = 500
        start = time.time()

        try:
            for root in roots:
                root = os.path.normpath(root)
                cur.execute("DELETE FROM files WHERE root = ?", (root,))
                cur.execute("DELETE FROM meta WHERE root = ?", (root,))
                for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda e: None):
                    if should_stop and should_stop():
                        conn.commit()
                        return total
                    dirpath = os.path.normpath(dirpath)
                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        try:
                            st = os.stat(full)
                            size = st.st_size
                            mtime = st.st_mtime
                        except OSError:
                            size, mtime = None, None
                        ext = os.path.splitext(fname)[1].lower()
                        batch.append(
                            (full, fname, fname.lower(), dirpath, ext, size, mtime, root)
                        )
                        total += 1
                        if len(batch) >= BATCH_SIZE:
                            cur.executemany(
                                "INSERT OR REPLACE INTO files "
                                "(path, name, name_lower, dir, ext, size, mtime, root) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                batch,
                            )
                            conn.commit()
                            batch = []
                            if progress_callback:
                                progress_callback(total, dirpath)
                if batch:
                    cur.executemany(
                        "INSERT OR REPLACE INTO files "
                        "(path, name, name_lower, dir, ext, size, mtime, root) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        batch,
                    )
                    conn.commit()
                    batch = []
                cur.execute(
                    "INSERT OR REPLACE INTO meta (root, last_build, file_count) VALUES (?, ?, ?)",
                    (root, time.time(), total),
                )
                conn.commit()
        finally:
            conn.close()
        return total

    def has_index_for(self, roots):
        conn = self._connect()
        try:
            cur = conn.cursor()
            for root in roots:
                cur.execute("SELECT 1 FROM meta WHERE root = ?", (os.path.normpath(root),))
                if cur.fetchone() is None:
                    return False
            return True
        finally:
            conn.close()

    def get_index_info(self):
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT root, last_build, file_count FROM meta ORDER BY last_build DESC")
            return cur.fetchall()
        finally:
            conn.close()

    def clear(self):
        conn = self._connect()
        try:
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM meta")
            conn.commit()
        finally:
            conn.close()

    def search(self, roots, name_query_lower, limit=200000):
        """
        Fast pre-filter straight in SQLite (substring match on the lower
        cased name). Additional filters (regex/wildcard/size/date) are
        applied afterwards in Python by the caller because they are hard
        to express efficiently in SQL.
        """
        conn = self._connect()
        try:
            cur = conn.cursor()
            roots = [os.path.normpath(r) for r in roots]
            placeholders = ",".join("?" for _ in roots)
            params = list(roots)
            sql = "SELECT path, name, dir, ext, size, mtime FROM files WHERE root IN (%s)" % placeholders
            if name_query_lower:
                sql += " AND name_lower LIKE ?"
                params.append("%" + name_query_lower + "%")
            sql += " LIMIT ?"
            params.append(limit)
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            conn.close()
