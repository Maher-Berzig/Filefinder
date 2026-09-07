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
        "date_custom_range": "Custom dates",
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
        "search_placeholder": "Type a file name, part of a name (accents optional), wildcard (report*.pdf) or regex, or pick from history...",

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

        # Search row
        "search_label": "بحث:",
        "mode_contains": "يحتوي على",
        "mode_wildcard": "حرف بدل (*, ?)",
        "mode_regex": "تعبير نمطي",
        "search_btn": "بحث",
        "stop_btn": "إيقاف",

        # Look in row
        "look_in_label": "البحث في:",
        "browse_btn": "استعراض...",
        "include_subfolders": "تضمين المجلدات الفرعية",
        "use_index": "استخدام الفهرس المحفوظ (أسرع)",
        "rebuild_index": "إعادة بناء الفهرس",
        "show_preview": "إظهار المعاينة",

        # Filters box
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
        "date_custom_range": "تواريخ مخصصة",
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
        "search_placeholder": "اكتب اسم ملف، جزءًا من اسم (اللكنات اختيارية)، حرف بدل (report*.pdf) أو تعبير نمطي، أو اختر من السجل...",

        # Options box
        "options_title": "الخيارات",
        "clear_history": "مسح السجل",
        "history_size_label": "حجم السجل:",
        "language_label": "اللغة:",
        "choose_font": "اختيار الخط...",
        "default_btn": "افتراضي",
        "about_btn": "حول",

        # Results table
        "col_name": "الاسم",
        "col_folder": "المجلد",
        "col_size": "الحجم",
        "col_type": "النوع",
        "col_date_modified": "تاريخ التعديل",

        # Status bar
        "status_ready": "جاهز",

        # Preview pane
        "preview_title": "معاينة",
        "preview_select_file": "اختر ملفًا لمعاينته هنا.",
        "preview_file_not_found": "الملف غير موجود.",

        # Context menu
        "menu_open": "فتح",
        "menu_open_folder": "فتح المجلد الحاوي",
        "menu_copy_path": "نسخ المسار الكامل",
        "menu_copy_name": "نسخ اسم الملف",
        "menu_delete": "حذف (سلة المحذوفات)",

        # System tray
        "tray_show": "إظهار باحث الملفات",
        "tray_exit": "خروج",

        # Friendly, native-script names shown in the Language dropdown, keyed by
        # the same language codes used in `translations` above.
        "en": "English",
        "ar": "العربية",

        # Reading direction for each language - "rtl" flips the whole UI mirror-
        # image (labels/buttons swap sides, text and editable fields align to
        # the right), the way Windows Explorer, Office, etc. do for Arabic.
        # Add "rtl" here for any future right-to-left language (Hebrew, Farsi,
        # Urdu...); everything else defaults to "ltr".
        "en": "ltr",
        "ar": "rtl",

        # Shared singleton - import this everywhere the UI needs translated text.
    },
    "fr": {
        "app_title": "File Finder - recherche rapide de fichiers",

        # Search row
        "search_label": "Recherche:",
        "mode_contains": "Contient",
        "mode_wildcard": "Caractère générique (*, ?)",
        "mode_regex": "Regex",
        "search_btn": "Recherche",
        "stop_btn": "Arrêt",

        # Look in row
        "look_in_label": "Regarder dans:",
        "browse_btn": "Parcourir...",
        "include_subfolders": "Inclure les sous-dossiers",
        "use_index": "Utiliser l'index enregistré (plus rapide)",
        "rebuild_index": "Reconstruire l'index",
        "show_preview": "Afficher l'aperçu",

        # Filters box
        "filters_title": "Filtres",
        "match_case": "Correspondance des mots",
        "whole_words": "Des mots entiers",
        "accents": "Accents",
        "modified_label": "Modifié:",
        "date_any_time": "À tout moment",
        "date_today": "Aujourd'hui",
        "date_past_7": "7 derniers jours",
        "date_past_30": "30 derniers jours",
        "date_this_year": "Cette année",
        "date_custom_range": "Dates personnalisée",
        "from_label": "depuis",
        "to_label": "À",
        "file_type_label": "Type de fichier",
        "min_label": "Min",
        "max_label": "Maximum",
        "ext_all_files": "Tous les fichiers",
        "ext_documents": "Documents",
        "ext_images": "Images",
        "ext_music": "Musique",
        "ext_video": "Vidéo",
        "ext_archives": "Archives",
        "ext_executables": "Exécutables",
        "names_containing": "Noms de fichiers contenant :",
        "all_words": "Tous les mots",
        "exact_phrase": "Expression exacte",
        "any_word": "N'importe quel mot",
        "no_words": "Pas de mots",
        "no_words_placeholder": "mots à exclure ou \"expression exacte\" à exclure",
        "search_placeholder": "Saisissez un nom de fichier, une partie d'un nom (accents facultatifs), un caractère générique (report*.pdf) ou une expression régulière, ou choisissez dans l'historique...",        

        # Options box
        "options_title": "Options",
        "clear_history": "Effacer l'historique",
        "history_size_label": "Taille de l'historique :",
        "language_label": "Langue:",
        "choose_font": "Choisissez la police...",
        "default_btn": "Défaut",
        "about_btn": "À propos de",

        # Results table
        "col_name": "Nom",
        "col_folder": "Dossier",
        "col_size": "Taille",
        "col_type": "Taper",
        "col_date_modified": "Date de modification",

        # Status bar
        "status_ready": "Prêt",

        # Preview pane
        "preview_title": "Aperçu",
        "preview_select_file": "Sélectionnez un fichier pour le prévisualiser ici.",
        "preview_file_not_found": "Fichier introuvable.",

        # Context menu
        "menu_open": "Ouvrir",
        "menu_open_folder": "Ouvrir le dossier contenant",
        "menu_copy_path": "Copier le chemin complet",
        "menu_copy_name": "Copier le nom du fichier",
        "menu_delete": "Supprimer (Corbeille)",

        # System tray
        "tray_show": "Afficher l'outil de recherche de fichiers",
        "tray_exit": "Sortie",

    },
}



# Friendly, native-script names shown in the Language dropdown, keyed by
# the same language codes used in `translations` above.
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "العربية",
    "fr": "Français",
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
