# -*- coding: utf-8 -*-
"""
Simple UI translation support for File Finder.

Usage elsewhere in the app:

    from .translations import tr
    label = tr.get("search_label", "Search:")

`tr.get(key, default)` looks up `key` in the currently selected language's
dictionary and falls back to `default` (normally the English text) if the
key or the language is missing - so the UI never breaks even if a
translation is incomplete.

This file is kept in plain UTF-8 (real characters, not \\uXXXX escapes) so
it's easy to read and correct directly in a text editor. If you ever need
a pure-ASCII copy (e.g. for a tool in your pipeline that chokes on non-
ASCII source files), generate one with:

    python tools/translations_codec.py to-ascii

and convert it back to readable UTF-8 at any time with:

    python tools/translations_codec.py to-utf8

Both commands read/write app/translations.py in place by default; see
tools/translations_codec.py --help for options. This file itself is
always the one File Finder imports and runs - the ASCII form is only a
convenience export, not a separate copy that needs to be kept in sync by
hand.

To add a new language, add a new "<code>": {...} entry to `translations`
below (copy the "en" block and translate the values - keys must stay the
same) and add a friendly display name to `LANGUAGE_NAMES`. Nothing else
needs to change: it will automatically show up in the Options box's
Language dropdown.
"""

translations = {
    "en": {
        "app_title": "File Finder - fast file search",

        # Search row
        "search_label": "Search:",
        "mode_contains": "Contains",
        "mode_wildcard": "Wildcard (*, ?)",
        "mode_regex": "Regex",
        "search_btn": "Search",
        "stop_btn": "Stop",

        # Look in row
        "look_in_label": "Look in:",
        "browse_btn": "Browse...",
        "include_subfolders": "Include subfolders",
        "use_index": "Use saved index (faster)",
        "rebuild_index": "Rebuild Index",
        "show_preview": "Show preview",

        # Filters box
        "filters_title": "Filters",
        "match_case": "Match case",
        "whole_words": "Whole words",
        "accents": "Accents",
        "modified_label": "Modified:",
        "date_any_time": "Any time",
        "date_today": "Today",
        "date_past_7": "Past 7 days",
        "date_past_30": "Past 30 days",
        "date_this_year": "This year",
        "date_custom_range": "Custom range",
        "from_label": "from",
        "to_label": "To",
        "file_type_label": "File Type",
        "min_label": "Min",
        "max_label": "Max",
        "ext_all_files": "All files",
        "ext_documents": "Documents",
        "ext_images": "Images",
        "ext_music": "Music",
        "ext_video": "Video",
        "ext_archives": "Archives",
        "ext_executables": "Executables",
        "names_containing": "File names containing:",
        "all_words": "All words",
        "exact_phrase": "Exact phrase",
        "any_word": "Any word",
        "no_words": "No words",
        "no_words_placeholder": "words to exclude, or \"exact phrase\" to exclude",
        "search_placeholder": "Type a file name, part of a name (accents optional), wildcard (*iric, report*.pdf) or regex, or pick from history...",

        # Options box
        "options_title": "Options",
        "clear_history": "Clear history",
        "history_size_label": "History size:",
        "language_label": "Language:",
        "choose_font": "Choose Font...",
        "default_btn": "Default",
        "about_btn": "About",

        # Results table
        "col_name": "Name",
        "col_folder": "Folder",
        "col_size": "Size",
        "col_type": "Type",
        "col_date_modified": "Date modified",

        # Status bar
        "status_ready": "Ready",

        # Preview pane
        "preview_title": "Preview",
        "preview_select_file": "Select a file to preview it here.",
        "preview_file_not_found": "File not found.",

        # Context menu
        "menu_open": "Open",
        "menu_open_folder": "Open containing folder",
        "menu_copy_path": "Copy full path",
        "menu_copy_name": "Copy file name",
        "menu_delete": "Delete (Recycle Bin)",

        # System tray
        "tray_show": "Show File Finder",
        "tray_exit": "Exit",
    },
    "ar": {
        "app_title": "باحث الملفات - بحث سريع عن الملفات",

        "search_label": "بحث:",
        "mode_contains": "يحتوي على",
        "mode_wildcard": "حرف بدل (*, ?)",
        "mode_regex": "تعبير نمطي",
        "search_btn": "بحث",
        "stop_btn": "إيقاف",

        "look_in_label": "البحث في:",
        "browse_btn": "استعراض...",
        "include_subfolders": "تضمين المجلدات الفرعية",
        "use_index": "استخدام الفهرس المحفوظ (أسرع)",
        "rebuild_index": "إعادة بناء الفهرس",
        "show_preview": "إظهار المعاينة",

        "filters_title": "المرشحات",
        "match_case": "مطابقة حالة الأحرف",
        "whole_words": "كلمات كاملة",
        "accents": "اللكنات",
        "modified_label": "التعديل:",
        "date_any_time": "أي وقت",
        "date_today": "اليوم",
        "date_past_7": "آخر 7 أيام",
        "date_past_30": "آخر 30 يومًا",
        "date_this_year": "هذه السنة",
        "date_custom_range": "نطاق مخصص",
        "from_label": "من",
        "to_label": "إلى",
        "file_type_label": "نوع الملف",
        "min_label": "الحد الأدنى",
        "max_label": "الحد الأقصى",
        "ext_all_files": "كل الملفات",
        "ext_documents": "مستندات",
        "ext_images": "صور",
        "ext_music": "موسيقى",
        "ext_video": "فيديو",
        "ext_archives": "أرشيفات",
        "ext_executables": "ملفات تنفيذية",
        "names_containing": "أسماء الملفات تحتوي على:",
        "all_words": "كل الكلمات",
        "exact_phrase": "عبارة مطابقة",
        "any_word": "أي كلمة",
        "no_words": "بدون كلمات",
        "no_words_placeholder": "كلمات لاستبعادها، أو \"عبارة مطابقة\" لاستبعادها",
        "search_placeholder": "اكتب اسم ملف، جزءًا من اسم (اللكنات اختيارية)، حرف بدل (*iric، report*.pdf) أو تعبير نمطي، أو اختر من السجل...",

        "options_title": "الخيارات",
        "clear_history": "مسح السجل",
        "history_size_label": "حجم السجل:",
        "language_label": "اللغة:",
        "choose_font": "اختيار الخط...",
        "default_btn": "افتراضي",
        "about_btn": "حول",

        "col_name": "الاسم",
        "col_folder": "المجلد",
        "col_size": "الحجم",
        "col_type": "النوع",
        "col_date_modified": "تاريخ التعديل",

        "status_ready": "جاهز",

        "preview_title": "معاينة",
        "preview_select_file": "اختر ملفًا لمعاينته هنا.",
        "preview_file_not_found": "الملف غير موجود.",

        "menu_open": "فتح",
        "menu_open_folder": "فتح المجلد الحاوي",
        "menu_copy_path": "نسخ المسار الكامل",
        "menu_copy_name": "نسخ اسم الملف",
        "menu_delete": "حذف (سلة المحذوفات)",

        "tray_show": "إظهار باحث الملفات",
        "tray_exit": "خروج",
    },
}

# Friendly, native-script names shown in the Language dropdown, keyed by
# the same language codes used in `translations` above.
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "العربية",
}

# Reading direction for each language - "rtl" flips the whole UI mirror-
# image (labels/buttons swap sides, text and editable fields align to
# the right), the way Windows Explorer, Office, etc. do for Arabic.
# Add "rtl" here for any future right-to-left language (Hebrew, Farsi,
# Urdu...); everything else defaults to "ltr".
LANGUAGE_DIRECTION = {
    "en": "ltr",
    "ar": "rtl",
}

DEFAULT_LANGUAGE = "en"


class _Translator:
    """Tiny helper so callers can just write tr.get(key, default) without
    worrying about which language is currently active - switching the
    active language (via set_language) is immediately reflected in every
    subsequent .get() call, from anywhere that imported `tr`."""

    def __init__(self, table, default_lang=DEFAULT_LANGUAGE):
        self._table = table
        self.lang = default_lang if default_lang in table else DEFAULT_LANGUAGE

    def set_language(self, lang_code):
        self.lang = lang_code if lang_code in self._table else DEFAULT_LANGUAGE

    def get(self, key, default=""):
        return self._table.get(self.lang, {}).get(key, default)

    def is_rtl(self):
        return LANGUAGE_DIRECTION.get(self.lang, "ltr") == "rtl"


# Shared singleton - import this everywhere the UI needs translated text.
tr = _Translator(translations)
