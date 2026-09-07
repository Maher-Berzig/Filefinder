# Adding a language to File Finder

File Finder's UI text all comes from one file, `app/translations.py`. Adding
a language is normally a **copy-paste-translate** job in that single file -
you don't need to touch any other file for a straightforward left-to-right
language (French, Spanish, German, etc.).

Right-to-left languages (Arabic, Hebrew, Farsi, Urdu...) need one extra
one-line entry (step 3) so the UI mirrors correctly - everything else is
the same.

---

## 1. Pick a language code

Use a short lowercase code for the language - normally its
[ISO 639-1](https://en.wikipedia.org/wiki/List_of_ISO_639_language_codes)
code: `fr` (French), `es` (Spanish), `de` (German), `he` (Hebrew), etc.
This code is what gets saved to the user's settings, so keep it short and
don't reuse an existing one.

## 2. Add a translation block in `translations`

Open `app/translations.py`. Near the top you'll find:

```python
translations = {
    "en": {
        "app_title": "File Finder - fast file search",
        ...
    },
    "ar": {
        ...
    },
}
```

Add a new `"<code>": { ... }` block, using the **same keys** as `"en"`
(copy the whole `"en"` block and translate just the values on the right).
Do not rename, remove, or reorder the keys - they're what the rest of the
app looks up by (e.g. `tr.get("search_btn", "Search")`), and any key you
skip will silently fall back to its English text instead of breaking.

```python
translations = {
    "en": {
        ...
    },
    "ar": {
        ...
    },
    "fr": {
        "app_title": "File Finder - recherche rapide de fichiers",
        "search_label": "Rechercher :",
        "mode_contains": "Contient",
        "mode_wildcard": "Caract\u00e8res g\u00e9n\u00e9riques (*, ?)",
        "mode_regex": "Expression r\u00e9guli\u00e8re",
        "search_btn": "Rechercher",
        "stop_btn": "Arr\u00eater",
        # ... continue for every key in the "en" block ...
    },
}
```

The full list of keys currently used by the app (grouped by where they
appear) is:

| Group | Keys |
|---|---|
| Window title | `app_title` |
| Search row | `search_label`, `search_placeholder`, `mode_contains`, `mode_wildcard`, `mode_regex`, `search_btn`, `stop_btn` |
| Look in row | `look_in_label`, `browse_btn`, `include_subfolders`, `use_index`, `rebuild_index`, `show_preview` |
| Filters box | `filters_title`, `match_case`, `whole_words`, `accents`, `modified_label`, `date_any_time`, `date_today`, `date_past_7`, `date_past_30`, `date_this_year`, `date_custom_range`, `from_label`, `to_label`, `file_type_label`, `min_label`, `max_label`, `ext_all_files`, `ext_documents`, `ext_images`, `ext_music`, `ext_video`, `ext_archives`, `ext_executables`, `names_containing`, `all_words`, `exact_phrase`, `any_word`, `no_words`, `no_words_placeholder` |
| Options box | `options_title`, `clear_history`, `history_size_label`, `language_label`, `choose_font`, `default_btn`, `about_btn` |
| Results table headers | `col_name`, `col_folder`, `col_size`, `col_type`, `col_date_modified` |
| Status bar | `status_ready` |
| Preview pane | `preview_title`, `preview_select_file`, `preview_file_not_found` |
| Right-click context menu | `menu_open`, `menu_open_folder`, `menu_copy_path`, `menu_copy_name`, `menu_delete` |
| System tray menu | `tray_show`, `tray_exit` |

**Tip:** you can write the translated text as a plain Unicode string
(e.g. `"Rechercher :"`) directly in the file - `app/translations.py` is
kept in plain UTF-8, so no `\uXXXX` escaping is needed. If you ever need
a pure-ASCII copy of the file (e.g. for a tool in your pipeline that
can't handle non-ASCII source), see **"Converting to/from ASCII"** below.

## 3. Add a display name in `LANGUAGE_NAMES`

Just below `translations`, add an entry so the language shows up with its
own native name in the Language dropdown (Options box):

```python
LANGUAGE_NAMES = {
    "en": "English",
    "ar": "\u0627\u0644\u0639\u0631\u0628\u064a\u0629",
    "fr": "Fran\u00e7ais",
}
```

## 4. Right-to-left languages only: add an entry in `LANGUAGE_DIRECTION`

If (and only if) the language reads right-to-left (Arabic, Hebrew, Farsi,
Urdu, etc.), add it here too so the whole UI mirrors correctly (labels and
buttons swap sides, text - including what you type into the Search and
"No words" boxes - aligns to the right):

```python
LANGUAGE_DIRECTION = {
    "en": "ltr",
    "ar": "rtl",
    "he": "rtl",   # example: Hebrew
}
```

Left-to-right languages don't need an entry here - anything missing
defaults to `"ltr"` automatically.

## 5. That's it - test it

No other file needs to change. `app/main_window.py` builds the Language
dropdown directly from `translations.keys()`, so a new block automatically
appears there the next time File Finder starts.

To test:

1. Run File Finder (`python main.py`).
2. Open **Options** and pick your new language from the **Language**
   dropdown.
3. Check that every label, button, checkbox, group title, table header,
   right-click menu, and the system tray menu switch to the new language
   immediately (no restart needed).
4. If it's a right-to-left language, check that the whole window mirrors
   (labels/buttons swap sides) and that typing into the Search box and
   the "No words" box aligns to the right.
5. Close and reopen File Finder - the language you picked should still be
   selected (it's remembered automatically).

## Notes for translators

- Keep placeholders and punctuation that carry meaning for the app
  itself - e.g. `no_words_placeholder` mentions `"exact phrase"` with
  quotation marks because quoting text in that box is a real feature
  (it excludes that exact phrase); translate the wording but keep the
  quotes.
- If a key is left untranslated (or the whole language block has a typo
  in a key name), the app simply falls back to the English default given
  in the `tr.get(key, "English default")` call at that spot in the code -
  it will never crash or show a blank label.
- A handful of dynamic, runtime-generated messages (e.g. "Searching in
  %s...", byte-count/progress text in the status bar) are not yet wired
  through `translations.py` and will keep appearing in English regardless
  of the selected language.

## Converting to/from ASCII

`app/translations.py` is kept as plain UTF-8 (real characters) so it's
easy to read and correct in any text editor - this is the file File
Finder actually imports and runs, and normally the only one you need to
touch.

If some tool in your pipeline (an old editor, a linter, a packaging step)
needs a pure-ASCII version instead, `tools/translations_codec.py` converts
between the two forms - both are exactly equivalent Python source, since
Python decodes `\uXXXX` escapes automatically while parsing a file:

```bash
# UTF-8 -> ASCII (escapes every non-ASCII character to \uXXXX)
python tools/translations_codec.py to-ascii

# ASCII -> UTF-8 (turns \uXXXX escapes back into real characters)
python tools/translations_codec.py to-utf8
```

Both commands edit `app/translations.py` in place by default (writing a
timestamped `.bak` copy first) - pass `--in`/`--out` to read or write a
different file instead, e.g. to preview the result without touching the
original:

```bash
python tools/translations_codec.py to-ascii --out /tmp/preview.py
```

Run `python tools/translations_codec.py --help` for the full list of
options.

