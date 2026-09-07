"""
Ensures only one File Finder process/tray icon exists at a time.

Without this, every "Open with File Finder" click in Explorer's context
menu starts a brand new process - and since MainWindow always creates
its own system tray icon, that meant a new tray icon piling up next to
the old ones on every single click.

Approach: a QLocalServer (named pipe on Windows) is opened by whichever
process gets there first - that one becomes "the" File Finder process.
Every later launch tries to connect to that same name; if it succeeds,
it just forwards its folder argument (or a bare "show" request) over
the socket and exits immediately without creating a window, a tray
icon, or anything else.
"""
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtNetwork import QLocalServer, QLocalSocket

# Unlikely-to-collide name so this doesn't clash with some unrelated
# app's local server on the same machine.
_SERVER_NAME = "FileFinder-SingleInstance-2f4e9b7a"


class SingleInstance(QObject):
    """Emits folderRequested/showRequested when a *later* launch of File
    Finder asks this (the primary/already-running) instance to open a
    folder or just come to the foreground."""

    folderRequested = pyqtSignal(str)
    showRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server = None

    def try_forward_to_existing(self, folder=None, timeout_ms=500):
        """If a File Finder instance is already running, send it
        *folder* (or just ask it to show itself, if folder is falsy)
        and return True. Returns False if no instance is running (the
        caller should proceed to become the primary instance)."""
        socket = QLocalSocket()
        socket.connectToServer(_SERVER_NAME)
        connected = socket.waitForConnected(timeout_ms)
        if not connected:
            return False
        message = folder if folder else "SHOW"
        socket.write(message.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def start_listening(self):
        """Become the primary instance: start listening for later
        launches to forward their requests to us instead of starting
        their own process."""
        # Clears out a stale server name left behind by a previous
        # crash, if any - harmless no-op otherwise.
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(_SERVER_NAME)

    def _on_new_connection(self):
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.waitForReadyRead(500)
        data = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
        socket.disconnectFromServer()
        if data and data != "SHOW":
            self.folderRequested.emit(data)
        else:
            self.showRequested.emit()
