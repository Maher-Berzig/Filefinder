import os
import time

from PyQt5.QtCore import Qt, QSettings, QDate, QDateTime, QSize
from PyQt5.QtGui import QIcon, QKeySequence, QFont
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QFileDialog,
    QMenu, QAction, QMessageBox, QGroupBox, QSpinBox, QDateEdit,
    QProgressBar, QStatusBar, QSplitter, QFileIconProvider, QShortcut,
    QCompleter, QApplication, QSystemTrayIcon, QStyle, QToolButton,
    QFontDialog, QButtonGroup,
)
from PyQt5.QtCore import QFileInfo, QStringListModel

from .search_worker import SearchWorker, IndexBuildWorker
from .index_manager import IndexManager
from .preview_pane import PreviewPane
from . import native_context_menu
from . import utils
from .translations import tr, translations, LANGUAGE_NAMES, DEFAULT_LANGUAGE

ORG_NAME = "FileFinder"
APP_NAME = "FileFinderApp"
APP_VERSION = "1.0"
MAX_HISTORY = 20

# (column key, default English header) - the actual header text shown is
# always looked up fresh via tr.get() so it follows the active language.
COLUMN_KEYS = ["col_name", "col_folder", "col_size", "col_type", "col_date_modified"]
COLUMNS_EN = ["Name", "Folder", "Size", "Type", "Date modified"]


class MainWindow(QMainWindow):
    def __init__(self, initial_folder=None):
        super().__init__()
        self.resize(1050, 680)

        self.settings = QSettings(ORG_NAME, APP_NAME)
        # Apply the saved UI language before building any widgets, so
        # everything is created with the right text the first time -
        # _retranslate_ui() (triggered by the Language dropdown) handles
        # updating it live afterwards.
        tr.set_language(self.settings.value("language", DEFAULT_LANGUAGE))
        self._apply_layout_direction()
        self.setWindowTitle(tr.get("app_title", "File Finder - fast file search"))
        self.icon_provider = QFileIconProvider()
        self.search_worker = None
        self.index_worker = None
        self._scanned = 0
        self._matched = 0
        self._search_start = 0.0
        self._force_quit = False
        self._initial_folder = initial_folder
        # Set by main.py before any custom font is applied, so "Default"
        # can restore Qt's real default font rather than whatever font
        # happens to be active (a previous custom choice) when clicked.
        self._default_font = QFont(
            getattr(QApplication.instance(), "ff_default_font", QApplication.instance().font()))

        self._build_ui()
        self._align_text_edits(Qt.RightToLeft if tr.is_rtl() else Qt.LeftToRight)
        self._build_tray_icon()
        self._load_settings()
        self._refresh_index_status()

        # A folder passed on the command line (e.g. via an Explorer
        # "Open with File Finder" context menu entry - see README.md)
        # takes priority over whatever "Look in" location was restored
        # from settings above.
        if self._initial_folder and os.path.isdir(self._initial_folder):
            self._set_location(self._initial_folder)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setSpacing(8)

        root_layout.addLayout(self._build_search_row())
        root_layout.addLayout(self._build_location_row())

        filters_options_row = QHBoxLayout()
        filters_options_row.addWidget(self._build_filters_box(), stretch=2)
        filters_options_row.addWidget(self._build_options_box(), stretch=1)
        root_layout.addLayout(filters_options_row)

        self.table = QTableWidget(0, len(COLUMN_KEYS))
        self._set_table_headers()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        # Every boundary should be freely draggable, like Explorer's own
        # details view - Stretch mode (previously used for "Folder")
        # auto-fills the column and disables the resize handle on its
        # right edge, which is exactly why that boundary was stuck.
        for col in range(len(COLUMN_KEYS)):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 260)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.preview_pane = PreviewPane()

        self.results_splitter = QSplitter(Qt.Horizontal)
        self.results_splitter.addWidget(self.preview_pane)
        self.results_splitter.addWidget(self.table)
        self.results_splitter.setStretchFactor(0, 1)
        self.results_splitter.setStretchFactor(1, 1)
        # Equal 50/50 initial split - QSplitter normalizes any sizes
        # given to setSizes() proportionally against the actual space
        # available once the window is shown, so equal values here
        # always mean "half and half" regardless of window size.
        self.results_splitter.setSizes([1, 1])
        root_layout.addWidget(self.results_splitter, stretch=1)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_label = QLabel(tr.get("status_ready", "Ready"))
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(160)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.status.addWidget(self.status_label, stretch=1)
        self.status.addPermanentWidget(self.progress_bar)

        enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self.search_edit)
        enter_shortcut.activated.connect(self._start_search)
        esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc_shortcut.activated.connect(self._stop_search)

    def _build_search_row(self):
        layout = QHBoxLayout()
        self.search_label = QLabel(tr.get("search_label", "Search:"))
        layout.addWidget(self.search_label)

        self.search_edit = QComboBox()
        self.search_edit.setEditable(True)
        self.search_edit.setInsertPolicy(QComboBox.NoInsert)
        self.search_edit.lineEdit().setPlaceholderText(
            tr.get("search_placeholder",
                   "Type a file name, part of a name (accents optional), "
                   "wildcard (*iric, report*.pdf) or regex, or pick from history..."))
        self.history_model = QStringListModel(self._load_history())
        completer = QCompleter(self.history_model, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.search_edit.setCompleter(completer)
        self.search_edit.addItems(self._load_history())
        self.search_edit.setCurrentText("")
        layout.addWidget(self.search_edit, stretch=1)

        # Item data holds the canonical (language-independent) mode code
        # used by _gather_params(), so switching the display language
        # never changes what the currently selected mode *means*.
        self.mode_combo = QComboBox()
        for code, key, default in (
                ("contains", "mode_contains", "Contains"),
                ("wildcard", "mode_wildcard", "Wildcard (*, ?)"),
                ("regex", "mode_regex", "Regex")):
            self.mode_combo.addItem(tr.get(key, default), code)
        layout.addWidget(self.mode_combo)

        self.search_btn = QPushButton(tr.get("search_btn", "Search"))
        self.search_btn.setDefault(True)
        self.search_btn.clicked.connect(self._start_search)
        layout.addWidget(self.search_btn)

        self.stop_btn = QPushButton(tr.get("stop_btn", "Stop"))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_search)
        layout.addWidget(self.stop_btn)

        return layout

    def _build_location_row(self):
        layout = QHBoxLayout()
        self.look_in_label = QLabel(tr.get("look_in_label", "Look in:"))
        layout.addWidget(self.look_in_label)

        self.location_combo = QComboBox()
        self.location_combo.setEditable(False)
        self._populate_locations()
        layout.addWidget(self.location_combo, stretch=1)

        self.browse_btn = QPushButton(tr.get("browse_btn", "Browse..."))
        self.browse_btn.clicked.connect(self._browse_folder)
        layout.addWidget(self.browse_btn)

        self.subfolders_check = QCheckBox(tr.get("include_subfolders", "Include subfolders"))
        self.subfolders_check.setChecked(True)
        layout.addWidget(self.subfolders_check)

        self.use_index_check = QCheckBox(tr.get("use_index", "Use saved index (faster)"))
        layout.addWidget(self.use_index_check)

        self.rebuild_index_btn = QPushButton(tr.get("rebuild_index", "Rebuild Index"))
        self.rebuild_index_btn.clicked.connect(self._rebuild_index)
        layout.addWidget(self.rebuild_index_btn)

        self.preview_check = QCheckBox(tr.get("show_preview", "Show preview"))
        self.preview_check.setToolTip("Show/hide the PDF/DJVU preview pane")
        self.preview_check.toggled.connect(self._on_preview_toggled)
        layout.addWidget(self.preview_check)

        # Small collapse/expand toggle for the Filters box below, right
        # at the end of this line rather than on a row of its own - so
        # collapsing it actually frees up vertical space for the
        # preview/table area instead of just moving the button there.
        self.filters_toggle_btn = QToolButton()
        self.filters_toggle_btn.setIconSize(QSize(14, 14))
        self.filters_toggle_btn.setToolTip("Show/hide Filters and Options")
        self.filters_toggle_btn.clicked.connect(self._toggle_filters)
        layout.addWidget(self.filters_toggle_btn)

        return layout

    def _build_filters_box(self):
        box = QGroupBox(tr.get("filters_title", "Filters"))
        self.filters_box = box
        outer = QVBoxLayout(box)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 14, 10, 10)

        def row_layout():
            lay = QHBoxLayout()
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            return lay

        # Line 1: Match case / Whole words / Accents; Modified: [..] from [] To []
        line1 = row_layout()
        self.match_case_check = QCheckBox(tr.get("match_case", "Match case"))
        self.whole_words_check = QCheckBox(tr.get("whole_words", "Whole words"))
        self.whole_words_check.setToolTip(
            "Only match whole words, not text found in the middle of a "
            "longer word.")
        self.match_accents_check = QCheckBox(tr.get("accents", "Accents"))
        self.match_accents_check.setToolTip(
            "When checked, accented letters must match exactly. When "
            "unchecked, accented and unaccented spellings match the same "
            "way, e.g. \"Ciric\" also finds \"\u0106iri\u0107\".")
        line1.addWidget(self.match_case_check)
        line1.addWidget(self.whole_words_check)
        line1.addWidget(self.match_accents_check)

        self.filters_line1_sep = QLabel(";")
        line1.addWidget(self.filters_line1_sep)

        self.modified_label = QLabel(tr.get("modified_label", "Modified:"))
        line1.addWidget(self.modified_label)
        # Item data holds the canonical (language-independent) date-mode
        # code used by _gather_params()/_on_date_mode_changed(), so the
        # currently selected mode's *meaning* never changes when the
        # display language is switched.
        self.date_combo = QComboBox()
        for code, key, default in (
                ("any", "date_any_time", "Any time"),
                ("today", "date_today", "Today"),
                ("past7", "date_past_7", "Past 7 days"),
                ("past30", "date_past_30", "Past 30 days"),
                ("thisyear", "date_this_year", "This year"),
                ("custom", "date_custom_range", "Custom range")):
            self.date_combo.addItem(tr.get(key, default), code)
        self.date_combo.currentIndexChanged.connect(self._on_date_mode_changed)
        line1.addWidget(self.date_combo)

        self.date_from_edit = QDateEdit(calendarPopup=True)
        self.date_from_edit.setDate(QDate.currentDate().addMonths(-1))
        self.date_from_edit.setEnabled(False)
        self.date_to_edit = QDateEdit(calendarPopup=True)
        self.date_to_edit.setDate(QDate.currentDate())
        self.date_to_edit.setEnabled(False)
        self.from_label = QLabel(tr.get("from_label", "from"))
        self.to_label = QLabel(tr.get("to_label", "To"))
        line1.addWidget(self.from_label)
        line1.addWidget(self.date_from_edit)
        line1.addWidget(self.to_label)
        line1.addWidget(self.date_to_edit)
        line1.addStretch(1)
        outer.addLayout(line1)

        # Line 2: File Type [..] Min [..] [..] Max [..] [..]
        line2 = row_layout()
        self.file_type_label = QLabel(tr.get("file_type_label", "File Type"))
        line2.addWidget(self.file_type_label)
        # Item data holds the canonical (English) key used to look names
        # up in utils.EXTENSION_GROUPS, independent of display language.
        self.filetype_combo = QComboBox()
        for ext_key in utils.EXTENSION_GROUPS.keys():
            i18n_key = "ext_" + ext_key.lower().replace(" ", "_")
            self.filetype_combo.addItem(tr.get(i18n_key, ext_key), ext_key)
        line2.addWidget(self.filetype_combo)

        self.min_label = QLabel(tr.get("min_label", "Min"))
        line2.addWidget(self.min_label)
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 1_000_000)
        self.min_size_unit = QComboBox()
        self.min_size_unit.addItems(["KB", "MB", "GB"])
        line2.addWidget(self.min_size_spin)
        line2.addWidget(self.min_size_unit)

        self.max_label = QLabel(tr.get("max_label", "Max"))
        line2.addWidget(self.max_label)
        self.max_size_spin = QSpinBox()
        self.max_size_spin.setRange(0, 1_000_000)
        self.max_size_unit = QComboBox()
        self.max_size_unit.addItems(["KB", "MB", "GB"])
        self.max_size_spin.setToolTip("0 = no limit")
        line2.addWidget(self.max_size_spin)
        line2.addWidget(self.max_size_unit)
        line2.addStretch(1)
        outer.addLayout(line2)

        # Line 3: File names containing: All words / Exact phrase / Any
        # word / No words [text field]
        line3 = row_layout()
        self.names_containing_label = QLabel(tr.get("names_containing", "File names containing:"))
        self.names_containing_label.setStyleSheet("font-weight: bold;")
        line3.addWidget(self.names_containing_label)

        self.words_all_check = QCheckBox(tr.get("all_words", "All words"))
        self.words_all_check.setToolTip(
            "Match names that contain every word typed in the Search box "
            "(in any order).")
        self.words_exact_check = QCheckBox(tr.get("exact_phrase", "Exact phrase"))
        self.words_exact_check.setToolTip(
            "Match names that contain the typed text exactly, as one phrase.")
        self.words_any_check = QCheckBox(tr.get("any_word", "Any word"))
        self.words_any_check.setToolTip(
            "Match names that contain at least one of the typed words.")

        self.word_mode_group = QButtonGroup(self)
        self.word_mode_group.setExclusive(True)
        for cb in (self.words_all_check, self.words_exact_check,
                   self.words_any_check):
            self.word_mode_group.addButton(cb)
        self.words_all_check.setChecked(True)

        line3.addWidget(self.words_all_check)
        line3.addWidget(self.words_exact_check)
        line3.addWidget(self.words_any_check)

        # "No words" is a separate exclusion filter, not part of the
        # All/Exact/Any group above - when checked, it applies on top of
        # whichever of those is selected, skipping any result whose name
        # contains the text typed here. Quoting it ("...") excludes that
        # exact phrase; without quotes, each space-separated word is
        # excluded independently (matching if the name contains any of
        # them). The checkbox just enables/disables the text field.
        self.no_words_check = QCheckBox(tr.get("no_words", "No words"))
        self.no_words_check.setToolTip(
            "Skip results whose name contains the text typed here.")
        self.no_words_edit = QLineEdit()
        self.no_words_edit.setPlaceholderText(
            tr.get("no_words_placeholder", "words to exclude, or \"exact phrase\" to exclude"))
        self.no_words_edit.setEnabled(False)
        self.no_words_edit.setToolTip(
            "Skip results whose name contains this text. Wrap it in "
            "double quotes to exclude an exact phrase; without quotes, "
            "each word is excluded on its own (matches if the name "
            "contains any of them).")
        self.no_words_check.toggled.connect(self.no_words_edit.setEnabled)
        line3.addWidget(self.no_words_check)
        line3.addWidget(self.no_words_edit, stretch=1)
        outer.addLayout(line3)

        return box

    def _build_options_box(self):
        box = QGroupBox(tr.get("options_title", "Options"))
        self.options_box = box
        layout = QVBoxLayout(box)

        self.clear_history_btn = QPushButton(tr.get("clear_history", "Clear history"))
        self.clear_history_btn.setToolTip(
            "Empties the search and \u201cLook in\u201d history dropdowns "
            "and resets them to their defaults.")
        self.clear_history_btn.clicked.connect(self._clear_all_history)
        layout.addWidget(self.clear_history_btn)

        history_row = QHBoxLayout()
        self.history_size_label = QLabel(tr.get("history_size_label", "History size:"))
        history_row.addWidget(self.history_size_label)
        self.history_limit_spin = QSpinBox()
        self.history_limit_spin.setRange(1, 200)
        self.history_limit_spin.setValue(MAX_HISTORY)
        self.history_limit_spin.setToolTip(
            "How many recent entries to keep in the search and "
            "\u201cLook in\u201d history dropdowns.")
        self.history_limit_spin.valueChanged.connect(self._on_history_limit_changed)
        history_row.addWidget(self.history_limit_spin)

        self.language_label = QLabel(tr.get("language_label", "Language:"))
        history_row.addWidget(self.language_label)
        self.language_combo = QComboBox()
        for code in translations.keys():
            self.language_combo.addItem(LANGUAGE_NAMES.get(code, code), code)
        idx = self.language_combo.findData(DEFAULT_LANGUAGE)
        self.language_combo.setCurrentIndex(idx if idx != -1 else 0)
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        history_row.addWidget(self.language_combo)

        history_row.addStretch(1)
        layout.addLayout(history_row)

        self.font_btn = QPushButton(tr.get("choose_font", "Choose Font..."))
        self.font_btn.setToolTip("Change the font used throughout File Finder.")
        self.font_btn.clicked.connect(self._choose_font)
        layout.addWidget(self.font_btn)

        default_about_row = QHBoxLayout()
        self.default_btn = QPushButton(tr.get("default_btn", "Default"))
        self.default_btn.setToolTip("Restore File Finder to its default settings.")
        self.default_btn.clicked.connect(self._restore_defaults)
        default_about_row.addWidget(self.default_btn)

        self.about_btn = QPushButton(tr.get("about_btn", "About"))
        self.about_btn.setToolTip("About File Finder.")
        self.about_btn.clicked.connect(self._show_about)
        default_about_row.addWidget(self.about_btn)
        layout.addLayout(default_about_row)

        layout.addStretch(1)
        return box

    def _set_table_headers(self):
        for col, key in enumerate(COLUMN_KEYS):
            self.table.setHorizontalHeaderItem(
                col, QTableWidgetItem(tr.get(key, COLUMNS_EN[col])))

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------
    def _on_language_changed(self, index):
        lang_code = self.language_combo.currentData()
        tr.set_language(lang_code)
        self._apply_layout_direction()
        self._retranslate_ui()
        self.settings.setValue("language", tr.lang)

    def _apply_layout_direction(self):
        """Mirrors the whole UI for right-to-left languages (labels and
        buttons swap sides, text - including what's typed into the
        Search/No words boxes - aligns to the right), the way Windows
        Explorer and Office do for Arabic. Applied at the QApplication
        level so every widget, current and future, picks it up."""
        direction = Qt.RightToLeft if tr.is_rtl() else Qt.LeftToRight
        app = QApplication.instance()
        if app is not None:
            app.setLayoutDirection(direction)
        self.setLayoutDirection(direction)
        self._align_text_edits(direction)

    def _align_text_edits(self, direction):
        """QComboBox's internal line edit and plain QLineEdit fields
        don't reliably pick up a *new* layout direction on their own
        (existing widgets keep their old text alignment and cursor
        side after a language switch, even once the surrounding layout
        has mirrored) - set both explicitly so typed text, the caret,
        and the placeholder all sit on the correct side."""
        align = (Qt.AlignRight | Qt.AlignVCenter) if direction == Qt.RightToLeft \
            else (Qt.AlignLeft | Qt.AlignVCenter)
        search_line_edit = self.search_edit.lineEdit() if hasattr(self, "search_edit") else None
        no_words_edit = getattr(self, "no_words_edit", None)
        for line_edit in (search_line_edit, no_words_edit):
            if line_edit is None:
                continue
            line_edit.setLayoutDirection(direction)
            line_edit.setAlignment(align)

    def _retranslate_ui(self):
        """Refresh the text of every widget built from the translation
        table, in place, without rebuilding the UI - called whenever the
        Language dropdown changes. Combo boxes that carry a language-
        independent value in their item data (mode/date/file type) keep
        their current *selection* across the switch; only their on-
        screen labels change."""
        self.setWindowTitle(tr.get("app_title", "File Finder - fast file search"))

        self.search_label.setText(tr.get("search_label", "Search:"))
        self.search_edit.lineEdit().setPlaceholderText(
            tr.get("search_placeholder",
                   "Type a file name, part of a name (accents optional), "
                   "wildcard (*iric, report*.pdf) or regex, or pick from history..."))
        for i, (key, default) in enumerate((
                ("mode_contains", "Contains"),
                ("mode_wildcard", "Wildcard (*, ?)"),
                ("mode_regex", "Regex"))):
            self.mode_combo.setItemText(i, tr.get(key, default))
        self.search_btn.setText(tr.get("search_btn", "Search"))
        self.stop_btn.setText(tr.get("stop_btn", "Stop"))

        self.look_in_label.setText(tr.get("look_in_label", "Look in:"))
        self.browse_btn.setText(tr.get("browse_btn", "Browse..."))
        self.subfolders_check.setText(tr.get("include_subfolders", "Include subfolders"))
        self.use_index_check.setText(tr.get("use_index", "Use saved index (faster)"))
        self.rebuild_index_btn.setText(tr.get("rebuild_index", "Rebuild Index"))
        self.preview_check.setText(tr.get("show_preview", "Show preview"))

        self.filters_box.setTitle(tr.get("filters_title", "Filters"))
        self.match_case_check.setText(tr.get("match_case", "Match case"))
        self.whole_words_check.setText(tr.get("whole_words", "Whole words"))
        self.match_accents_check.setText(tr.get("accents", "Accents"))
        self.modified_label.setText(tr.get("modified_label", "Modified:"))
        for i, (key, default) in enumerate((
                ("date_any_time", "Any time"),
                ("date_today", "Today"),
                ("date_past_7", "Past 7 days"),
                ("date_past_30", "Past 30 days"),
                ("date_this_year", "This year"),
                ("date_custom_range", "Custom range"))):
            self.date_combo.setItemText(i, tr.get(key, default))
        self.from_label.setText(tr.get("from_label", "from"))
        self.to_label.setText(tr.get("to_label", "To"))

        self.file_type_label.setText(tr.get("file_type_label", "File Type"))
        for i, ext_key in enumerate(utils.EXTENSION_GROUPS.keys()):
            i18n_key = "ext_" + ext_key.lower().replace(" ", "_")
            self.filetype_combo.setItemText(i, tr.get(i18n_key, ext_key))
        self.min_label.setText(tr.get("min_label", "Min"))
        self.max_label.setText(tr.get("max_label", "Max"))

        self.names_containing_label.setText(tr.get("names_containing", "File names containing:"))
        self.words_all_check.setText(tr.get("all_words", "All words"))
        self.words_exact_check.setText(tr.get("exact_phrase", "Exact phrase"))
        self.words_any_check.setText(tr.get("any_word", "Any word"))
        self.no_words_check.setText(tr.get("no_words", "No words"))
        self.no_words_edit.setPlaceholderText(
            tr.get("no_words_placeholder", "words to exclude, or \"exact phrase\" to exclude"))

        self.options_box.setTitle(tr.get("options_title", "Options"))
        self.clear_history_btn.setText(tr.get("clear_history", "Clear history"))
        self.history_size_label.setText(tr.get("history_size_label", "History size:"))
        self.language_label.setText(tr.get("language_label", "Language:"))
        self.font_btn.setText(tr.get("choose_font", "Choose Font..."))
        self.default_btn.setText(tr.get("default_btn", "Default"))
        self.about_btn.setText(tr.get("about_btn", "About"))

        self._set_table_headers()

        self.preview_pane.retranslate_ui()

        if self.tray_icon is not None:
            self.tray_show_action.setText(tr.get("tray_show", "Show File Finder"))
            self.tray_exit_action.setText(tr.get("tray_exit", "Exit"))

    # ------------------------------------------------------------------
    # Location helpers
    # ------------------------------------------------------------------
    def _populate_locations(self):
        self.location_combo.clear()
        drives = utils.list_windows_drives()
        for drive in drives:
            self.location_combo.addItem(drive)
        home = os.path.expanduser("~")
        self.location_combo.addItem(home)
        for path in self._load_location_history():
            if self.location_combo.findText(path) == -1:
                self.location_combo.addItem(path)

    def _set_location(self, folder):
        """Insert (if needed) and select *folder* in the "Look in" combo,
        and remember it in the location history - shared by Browse... and
        by a folder path passed in on the command line (see README.md's
        "Explorer context menu" section)."""
        folder = os.path.normpath(folder)
        if self.location_combo.findText(folder) == -1:
            self.location_combo.insertItem(0, folder)
        self.location_combo.setCurrentIndex(self.location_combo.findText(folder))
        self._remember_location_history(folder)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose folder to search")
        if folder:
            # QFileDialog always returns "/"-separated paths, even on
            # Windows - normalize so the combo box (and everything
            # downstream) shows/uses native "\\" separators instead of
            # a mix of the two.
            self._set_location(folder)

    def handle_folder_request(self, folder):
        """Called when a *second* File Finder launch (e.g. another
        "Open with File Finder" click in Explorer) forwards a folder to
        this, the already-running instance - see app/single_instance.py.
        Brings the window to the front instead of a new process/tray
        icon appearing."""
        if os.path.isdir(folder):
            self._set_location(folder)
        self._restore_from_tray()

    def handle_show_request(self):
        """Called when a second launch (with no folder argument) just
        asks the already-running instance to come to the foreground."""
        self._restore_from_tray()

    def _on_date_mode_changed(self, index):
        custom = self.date_combo.currentData() == "custom"
        self.date_from_edit.setEnabled(custom)
        self.date_to_edit.setEnabled(custom)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _gather_params(self):
        root = self.location_combo.currentText().strip()
        if not root:
            root = os.path.expanduser("~")
        # Normalize once, here, so every downstream consumer (live walk,
        # index build, index search, and the "Folder" column it all ends
        # up displayed in) agrees on one separator style instead of
        # mixing "/" (however the user typed/pasted it) with the "\\"
        # os.walk()/os.path.join() add for subfolders.
        root = os.path.normpath(root)
        roots = [root]

        mode = self.mode_combo.currentData()

        extensions = None
        ftype = self.filetype_combo.currentData()
        if utils.EXTENSION_GROUPS.get(ftype):
            extensions = utils.EXTENSION_GROUPS[ftype]

        if self.words_exact_check.isChecked():
            word_mode = "phrase"
        elif self.words_any_check.isChecked():
            word_mode = "any"
        else:
            word_mode = "all"
        exclude_text = self.no_words_edit.text().strip() if self.no_words_check.isChecked() else ""

        min_size_bytes = None
        if self.min_size_spin.value() > 0:
            mult = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[self.min_size_unit.currentText()]
            min_size_bytes = self.min_size_spin.value() * mult

        max_size_bytes = None
        if self.max_size_spin.value() > 0:
            mult = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}[self.max_size_unit.currentText()]
            max_size_bytes = self.max_size_spin.value() * mult

        date_from_ts = None
        date_to_ts = None
        date_mode = self.date_combo.currentData()
        now = QDateTime.currentDateTime()
        if date_mode == "today":
            date_from_ts = QDateTime(QDate.currentDate()).toSecsSinceEpoch()
        elif date_mode == "past7":
            date_from_ts = now.addDays(-7).toSecsSinceEpoch()
        elif date_mode == "past30":
            date_from_ts = now.addDays(-30).toSecsSinceEpoch()
        elif date_mode == "thisyear":
            date_from_ts = QDateTime(QDate(QDate.currentDate().year(), 1, 1)).toSecsSinceEpoch()
        elif date_mode == "custom":
            date_from_ts = QDateTime(self.date_from_edit.date()).toSecsSinceEpoch()
            date_to_ts = QDateTime(self.date_to_edit.date()).addDays(1).toSecsSinceEpoch()

        use_index = self.use_index_check.isChecked()
        if use_index:
            index = IndexManager()
            if not index.has_index_for(roots):
                use_index = False
                self.use_index_check.setChecked(False)
                QMessageBox.information(
                    self, "No index yet",
                    "There is no saved index for this location yet.\n"
                    "Falling back to a live search. Click 'Rebuild Index' "
                    "to speed up future searches.")

        return {
            "pattern": self.search_edit.currentText(),
            "mode": mode,
            "word_mode": word_mode,
            "exclude_text": exclude_text,
            "match_case": self.match_case_check.isChecked(),
            "whole_words": self.whole_words_check.isChecked(),
            "match_accents": self.match_accents_check.isChecked(),
            "roots": roots,
            "include_subfolders": self.subfolders_check.isChecked(),
            "extensions": extensions,
            "min_size_bytes": min_size_bytes,
            "max_size_bytes": max_size_bytes,
            "date_from_ts": date_from_ts,
            "date_to_ts": date_to_ts,
            "use_index": use_index,
        }

    def _start_search(self):
        if self.search_worker and self.search_worker.isRunning():
            return

        params = self._gather_params()
        query = params["pattern"].strip()
        if query:
            self._remember_history(query)

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._scanned = 0
        self._matched = 0
        self._search_start = time.time()

        self.search_worker = SearchWorker(params)
        self.search_worker.resultsReady.connect(self._on_results)
        self.search_worker.progress.connect(self._on_progress)
        self.search_worker.finished_search.connect(self._on_finished)
        self.search_worker.error.connect(self._on_error)

        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Searching in %s ..." % params["roots"][0])
        self.search_worker.start()

    def _stop_search(self):
        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()
            self.status_label.setText("Stopping...")
        if self.index_worker and self.index_worker.isRunning():
            self.index_worker.stop()

    def _on_results(self, records):
        self.table.setSortingEnabled(False)
        for rec in records:
            row = self.table.rowCount()
            self.table.insertRow(row)

            name_item = QTableWidgetItem(rec["name"])
            try:
                icon = self.icon_provider.icon(QFileInfo(rec["path"]))
                name_item.setIcon(icon)
            except Exception:
                pass
            name_item.setData(Qt.UserRole, rec["path"])
            self.table.setItem(row, 0, name_item)

            self.table.setItem(row, 1, QTableWidgetItem(rec["dir"]))

            size_item = QTableWidgetItem(utils.human_size(rec["size"]))
            size_item.setData(Qt.UserRole, rec["size"] or 0)
            self.table.setItem(row, 2, size_item)

            ext = rec["ext"].lstrip(".").upper() if rec["ext"] else "FILE"
            self.table.setItem(row, 3, QTableWidgetItem(ext))

            mtime_str = ""
            if rec["mtime"]:
                mtime_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(rec["mtime"]))
            date_item = QTableWidgetItem(mtime_str)
            date_item.setData(Qt.UserRole, rec["mtime"] or 0)
            self.table.setItem(row, 4, date_item)

            self._matched += 1
        self.status_label.setText(
            "Scanned %d items - %d matches so far..." % (self._scanned, self._matched))

    def _on_progress(self, scanned, current_path):
        self._scanned = scanned
        short_path = current_path
        if len(short_path) > 60:
            short_path = "..." + short_path[-57:]
        self.status_label.setText(
            "Scanned %d items - %d matches so far... %s" % (scanned, self._matched, short_path))

    def _on_finished(self, scanned, matched, elapsed):
        self._scanned = scanned
        self._matched = matched
        self.table.setSortingEnabled(True)
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(
            "Done. Scanned %d items, found %d matches in %s."
            % (scanned, matched, utils.format_seconds(elapsed)))

    def _on_error(self, message):
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "Search error", message)
        self.status_label.setText("Error: %s" % message)

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------
    def _rebuild_index(self):
        root = self.location_combo.currentText().strip() or os.path.expanduser("~")
        answer = QMessageBox.question(
            self, "Rebuild index",
            "This will scan '%s' and all its subfolders and save the file "
            "list for faster future searches. This can take a while for "
            "large drives. Continue?" % root,
            QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return

        self.rebuild_index_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Building index for %s ..." % root)

        self.index_worker = IndexBuildWorker([root])
        self.index_worker.progress.connect(
            lambda n, path: self.status_label.setText("Indexing... %d files scanned" % n))
        self.index_worker.finished_build.connect(self._on_index_built)
        self.index_worker.error.connect(self._on_error)
        self.index_worker.start()

    def _on_index_built(self, total, elapsed):
        self.rebuild_index_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(
            "Index built: %d files in %s." % (total, utils.format_seconds(elapsed)))
        self._refresh_index_status()

    def _refresh_index_status(self):
        try:
            info = IndexManager().get_index_info()
        except Exception:
            info = []
        if info:
            tips = ["%s: %d files" % (root, count) for root, _, count in info]
            self.rebuild_index_btn.setToolTip("Indexed:\n" + "\n".join(tips))
        else:
            self.rebuild_index_btn.setToolTip("No index built yet.")

    # ------------------------------------------------------------------
    # Preview pane
    # ------------------------------------------------------------------
    def _toggle_filters(self):
        self._apply_filters_visible(not self.filters_box.isVisible())
        self.settings.setValue("filters_visible", self.filters_box.isVisible())

    def _apply_filters_visible(self, visible):
        self.filters_box.setVisible(visible)
        self.options_box.setVisible(visible)
        # Same triangle icon as the preview pane's Prev/Next buttons,
        # just rotated by direction: down-pointing = "expanded, click
        # to collapse"; right-pointing = "collapsed, click to expand".
        self.filters_toggle_btn.setIcon(utils.triangle_icon("down" if visible else "right"))

    def _on_preview_toggled(self, checked):
        self.preview_pane.setVisible(checked)
        self.settings.setValue("preview_visible", checked)
        if checked:
            # The splitter collapses a hidden widget to 0 width, so
            # showing it again needs an explicit reset back to a 50/50
            # split - otherwise it reappears squeezed into whatever
            # sliver of space it last had.
            total = self.results_splitter.width()
            half = max(total // 2, 1)
            self.results_splitter.setSizes([half, total - half])
            self._on_selection_changed()

    def _on_selection_changed(self):
        if not self.preview_check.isChecked():
            return
        paths = self._selected_paths()
        if len(paths) == 1 and utils.is_previewable(paths[0]):
            self.preview_pane.show_file(paths[0])
        elif not paths:
            self.preview_pane.clear()
        else:
            self.preview_pane.show_message("No preview available for this selection.")

    # ------------------------------------------------------------------
    # Row actions / context menu
    # ------------------------------------------------------------------
    def _selected_path(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _selected_paths(self):
        """Full paths of every currently selected row, in row order."""
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        paths = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                paths.append(item.data(Qt.UserRole))
        return paths

    def _open_selected(self):
        path = self._selected_path()
        if not path:
            return
        ok, err = utils.open_path(path)
        if not ok:
            QMessageBox.warning(self, "Could not open file", err)

    def _reveal_selected(self):
        path = self._selected_path()
        if not path:
            return
        ok, err = utils.reveal_in_explorer(path)
        if not ok:
            QMessageBox.warning(self, "Could not open folder", err)

    def _copy_path_selected(self):
        path = self._selected_path()
        if path:
            utils.copy_to_clipboard(path)
            self.status_label.setText("Copied path to clipboard.")

    def _copy_name_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        name = self.table.item(row, 0).text()
        utils.copy_to_clipboard(name)
        self.status_label.setText("Copied file name to clipboard.")

    def _copy_list_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        utils.copy_lines_to_clipboard(paths)
        self.status_label.setText("Copied %d item(s) to clipboard." % len(paths))

    def _delete_selected(self):
        path = self._selected_path()
        if not path:
            return
        answer = QMessageBox.question(
            self, "Delete file",
            "Send this file to the Recycle Bin?\n\n%s" % path,
            QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        try:
            try:
                from send2trash import send2trash
                send2trash(path)
            except ImportError:
                os.remove(path)
            row = self.table.currentRow()
            self.table.removeRow(row)
            self.status_label.setText("Deleted: %s" % path)
        except Exception as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))

    def _show_context_menu(self, pos):
        if self.table.rowCount() == 0:
            return
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        # A right click on a row that isn't part of the current multi
        # selection replaces the selection, same as Explorer; a right
        # click inside an existing multi selection keeps it intact.
        if not self.table.selectionModel().isRowSelected(index.row(), index.parent()):
            self.table.selectRow(index.row())

        selected_paths = self._selected_paths()
        multi = len(selected_paths) > 1

        menu = QMenu(self)
        if not multi:
            menu.addAction(tr.get("menu_open", "Open"), self._open_selected)
            menu.addAction(tr.get("menu_open_folder", "Open containing folder"), self._reveal_selected)
            menu.addSeparator()

        menu.addAction(tr.get("menu_copy_path", "Copy full path"), self._copy_path_selected)
        menu.addAction(tr.get("menu_copy_name", "Copy file name"), self._copy_name_selected)
        if multi:
            menu.addAction(
                "Copy List (%d items)" % len(selected_paths), self._copy_list_selected)
        menu.addSeparator()
        menu.addAction(tr.get("menu_delete", "Delete (Recycle Bin)"), self._delete_selected)

        # Merge the real Windows Explorer context menu straight into
        # this menu (rather than a separate "..." entry), so every
        # shell/third-party action shows up alongside File Finder's own.
        context_menu_obj = None
        hmenu = None
        if native_context_menu.is_available():
            hwnd = int(self.table.viewport().winId())
            context_menu_obj, hmenu, err = native_context_menu.get_context_menu(
                hwnd, selected_paths)
            if context_menu_obj is not None and hmenu is not None:
                items = native_context_menu.read_menu_items(hmenu)
                if items:
                    menu.addSeparator()

                    def invoke(cmd_id, _cm=context_menu_obj, _hwnd=hwnd):
                        ok, ierr = native_context_menu.invoke_command(_cm, _hwnd, cmd_id)
                        if not ok:
                            QMessageBox.warning(self, "Action failed", ierr)

                    self._populate_native_menu(menu, items, invoke)
            elif err:
                menu.addSeparator()
                note = menu.addAction("Windows context menu unavailable (%s)" % err)
                note.setEnabled(False)

        menu.exec_(self.table.viewport().mapToGlobal(pos))

        if hmenu is not None:
            native_context_menu.destroy_menu(hmenu)

    def _populate_native_menu(self, qmenu, items, invoke_callback):
        """Recursively add the shell menu's items/submenus as QActions,
        carrying over each item's icon when the shell handed us one."""
        for entry in items:
            if entry["separator"]:
                qmenu.addSeparator()
                continue
            if entry["submenu"] is not None:
                if not entry["text"]:
                    continue
                sub = qmenu.addMenu(entry["text"])
                if entry.get("icon") is not None:
                    sub.menuAction().setIcon(entry["icon"])
                self._populate_native_menu(sub, entry["submenu"], invoke_callback)
                continue
            if not entry["text"]:
                continue
            action = qmenu.addAction(entry["text"])
            if entry.get("icon") is not None:
                action.setIcon(entry["icon"])
            action.setEnabled(not entry["disabled"])
            cmd_id = entry["id"]
            action.triggered.connect(
                lambda checked=False, cid=cmd_id: invoke_callback(cid))

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------
    def _build_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return

        icon = self.windowIcon()
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_FileIcon)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("File Finder")

        tray_menu = QMenu(self)
        self.tray_show_action = tray_menu.addAction(tr.get("tray_show", "Show File Finder"))
        self.tray_show_action.triggered.connect(self._restore_from_tray)
        tray_menu.addSeparator()
        self.tray_exit_action = tray_menu.addAction(tr.get("tray_exit", "Exit"))
        self.tray_exit_action.triggered.connect(self._quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self._restore_from_tray()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_app(self):
        self._force_quit = True
        self.close()

    # ------------------------------------------------------------------
    # Settings / history persistence
    # ------------------------------------------------------------------
    def _history_limit(self):
        return self.settings.value("history_limit", MAX_HISTORY, type=int)

    def _load_history(self):
        history = self.settings.value("search_history", [])
        if isinstance(history, str):
            history = [history]
        return list(history) if history else []

    def _remember_history(self, query):
        history = self._load_history()
        if query in history:
            history.remove(query)
        history.insert(0, query)
        history = history[: self._history_limit()]
        self.settings.setValue("search_history", history)
        self.history_model.setStringList(history)
        self._refresh_search_history_items(history)

    def _refresh_search_history_items(self, history):
        current = self.search_edit.currentText()
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.addItems(history)
        self.search_edit.setCurrentText(current)
        self.search_edit.blockSignals(False)

    def _load_location_history(self):
        history = self.settings.value("location_history", [])
        if isinstance(history, str):
            history = [history]
        return list(history) if history else []

    def _remember_location_history(self, path):
        history = self._load_location_history()
        if path in history:
            history.remove(path)
        history.insert(0, path)
        history = history[: self._history_limit()]
        self.settings.setValue("location_history", history)

    def _on_history_limit_changed(self, value):
        self.settings.setValue("history_limit", value)
        # Trim what's already stored/shown down to the new limit right
        # away, rather than waiting for the next search/browse.
        search_history = self._load_history()[:value]
        self.settings.setValue("search_history", search_history)
        self.history_model.setStringList(search_history)
        self._refresh_search_history_items(search_history)

        location_history = self._load_location_history()[:value]
        self.settings.setValue("location_history", location_history)
        self._populate_locations()

    def _clear_all_history(self):
        reply = QMessageBox.question(
            self, "Clear history",
            "Clear the search and \u201cLook in\u201d history, and reset "
            "them to their defaults?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self.settings.setValue("search_history", [])
        self.history_model.setStringList([])
        self.search_edit.blockSignals(True)
        self.search_edit.clear()
        self.search_edit.setCurrentText("")
        self.search_edit.blockSignals(False)

        self.settings.setValue("location_history", [])
        self.settings.remove("last_location")
        self._populate_locations()
        if self.location_combo.count() > 0:
            self.location_combo.setCurrentIndex(0)

        self.status_label.setText("History cleared.")

    def _choose_font(self):
        current_font = QApplication.instance().font()
        font, ok = QFontDialog.getFont(current_font, self, "Choose UI Font")
        if not ok:
            return
        self._apply_font(font)
        self.settings.setValue("ui_font", font.toString())

    def _apply_font(self, font):
        app = QApplication.instance()
        app.setFont(font)
        # setFont() on the QApplication only changes the *default* used
        # by widgets created from now on - explicitly re-apply it to
        # everything that already exists so the change is visible
        # immediately, as promised, rather than only after a restart.
        self.setFont(font)
        for widget in self.findChildren(QWidget):
            widget.setFont(font)

    def _restore_defaults(self):
        reply = QMessageBox.question(
            self, "Restore defaults",
            "Restore File Finder's search options, filters, and "
            "appearance to their default values? Your search/\u201cLook "
            "in\u201d history is kept - use \u201cClear history\u201d for "
            "that.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # Appearance
        self._apply_font(self._default_font)
        self.settings.remove("ui_font")

        # Search row
        self.mode_combo.setCurrentIndex(0)

        # Look in
        home = os.path.expanduser("~")
        idx = self.location_combo.findText(home)
        self.location_combo.setCurrentIndex(idx if idx != -1 else 0)
        self.subfolders_check.setChecked(True)

        # Filters
        self.filetype_combo.setCurrentIndex(0)
        self.words_all_check.setChecked(True)
        self.no_words_check.setChecked(False)
        self.no_words_edit.clear()
        self.match_case_check.setChecked(False)
        self.whole_words_check.setChecked(False)
        self.match_accents_check.setChecked(False)
        self.min_size_spin.setValue(0)
        self.min_size_unit.setCurrentIndex(0)
        self.max_size_spin.setValue(0)
        self.max_size_unit.setCurrentIndex(0)
        self.date_combo.setCurrentIndex(0)
        self.date_from_edit.setDate(QDate.currentDate().addMonths(-1))
        self.date_to_edit.setDate(QDate.currentDate())

        self._apply_filters_visible(True)
        self.settings.setValue("filters_visible", True)

        # Preview
        self.preview_check.setChecked(False)

        # Options
        self.history_limit_spin.setValue(MAX_HISTORY)

        self.status_label.setText("Settings restored to defaults.")

    def _show_about(self):
        QMessageBox.about(
            self, "About File Finder",
            "<h3>File Finder</h3>"
            "<p>Version %s</p>"
            "<p>A fast, lightweight file search and preview tool.</p>"
            "<p>Built with Python and PyQt5. Live and indexed search, "
            "accent-insensitive and wildcard matching, a PDF/DJVU preview "
            "pane, and native Windows Explorer context menu integration.</p>"
            "<p>&copy; %s</p>" % (APP_VERSION, time.strftime("%Y")))

    def _load_settings(self):
        idx = self.language_combo.findData(tr.lang)
        if idx != -1:
            self.language_combo.blockSignals(True)
            self.language_combo.setCurrentIndex(idx)
            self.language_combo.blockSignals(False)

        last_location = self.settings.value("last_location", "")
        if last_location:
            if self.location_combo.findText(last_location) == -1:
                self.location_combo.insertItem(0, last_location)
            self.location_combo.setCurrentIndex(self.location_combo.findText(last_location))

        preview_visible = self.settings.value("preview_visible", False, type=bool)
        self.preview_check.setChecked(preview_visible)
        self.preview_pane.setVisible(preview_visible)

        word_mode = self.settings.value("word_mode", "all")
        {
            "all": self.words_all_check,
            "phrase": self.words_exact_check,
            "any": self.words_any_check,
        }.get(word_mode, self.words_all_check).setChecked(True)
        self.no_words_check.setChecked(self.settings.value("exclude_enabled", False, type=bool))
        self.no_words_edit.setText(self.settings.value("exclude_text", ""))
        self.no_words_edit.setEnabled(self.no_words_check.isChecked())
        self.match_case_check.setChecked(self.settings.value("match_case", False, type=bool))
        self.whole_words_check.setChecked(self.settings.value("whole_words", False, type=bool))
        self.match_accents_check.setChecked(self.settings.value("match_accents", False, type=bool))

        self._apply_filters_visible(self.settings.value("filters_visible", True, type=bool))

        self.history_limit_spin.blockSignals(True)
        self.history_limit_spin.setValue(self._history_limit())
        self.history_limit_spin.blockSignals(False)

        font_str = self.settings.value("ui_font", "")
        if font_str:
            font = QFont()
            if font.fromString(font_str):
                self._apply_font(font)

    def closeEvent(self, event):
        self.settings.setValue("language", tr.lang)
        self.settings.setValue("last_location", self.location_combo.currentText())
        if self.words_exact_check.isChecked():
            word_mode = "phrase"
        elif self.words_any_check.isChecked():
            word_mode = "any"
        else:
            word_mode = "all"
        self.settings.setValue("word_mode", word_mode)
        self.settings.setValue("exclude_enabled", self.no_words_check.isChecked())
        self.settings.setValue("exclude_text", self.no_words_edit.text())
        self.settings.setValue("match_case", self.match_case_check.isChecked())
        self.settings.setValue("whole_words", self.whole_words_check.isChecked())
        self.settings.setValue("match_accents", self.match_accents_check.isChecked())

        # Minimize to the system tray instead of quitting, unless the
        # user picked "Exit" from the tray menu (or there is no tray).
        if self.tray_icon is not None and not self._force_quit:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "File Finder", "Still running - click the tray icon to reopen.",
                QSystemTrayIcon.Information, 2000)
            return

        if self.search_worker and self.search_worker.isRunning():
            self.search_worker.stop()
            self.search_worker.wait(2000)
        if self.index_worker and self.index_worker.isRunning():
            self.index_worker.stop()
            self.index_worker.wait(2000)
        self.preview_pane.wait_for_pending()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        super().closeEvent(event)
