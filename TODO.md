# TODO

Ideas for the next versions, most useful first. Finished items move to [CHANGELOG.md](CHANGELOG.md).
Reviewed: 2026-10-09 (after 0.18.0).

## Check first
- [ ] **LitRes with a real session after the connector move (0.15) and the lazy Chromium (0.18):**
  sign-in, F5 sync, downloading one book and "Download all", LitRes folders, the position from the phone.
  Covered by smoke tests only without a signed-in account.
- [ ] **Installers on real machines:** `Muninhall-Setup-*.exe` on Windows 10/11 (install, file
  associations, uninstall, restart after a restore in the frozen build) and `Muninhall.flatpak` on Linux
  (data shared with the native install, LitRes sign-in inside the sandbox).

## Refactoring towards SOLID
Behaviour doesn't change; every step — tests plus a full flow run on the installed build. Numbers are from
the review after 1.0.0. Step 3 prepares new connectors (OPDS).
- [ ] **1. Shared widgets (duplication):** `LibraryScopeCombo` — the "All libraries + list" selector built
  three times (graph, statistics, backups) plus the Source filter → library mapping done twice;
  `BoxedList` — the Adwaita boxed-list rows assembled by hand in statistics, Singularity and LitRes folders
  (settings have `group()`/`row()`); `confirm()` — the Cancel + destructive-button dialog repeated 4 times.
- [ ] **2. A `Settings` class (DIP):** typed properties and a `changed` signal instead of the raw dict read
  by string keys in 10 modules and manual `save_settings()` calls. Move module-level state into objects:
  accent/theme overrides in `style`, `_books_dir` and `DEBUG` in `core`, `widgets.THUMBS_DIR` (set by
  `App`), the reader's web profile, the settings page's network manager.
- [ ] **3. `LibrarySource` interface (OCP, SRP):** `FolderLibrary` and `LitresLibrary` implement id, name,
  scanning/sync, subfolders for the filter, graph tags, backup files and capabilities, replacing the
  `kind == "litres"` / `"folder"` checks spread over app, library, settings, graph, statistics and backups.
- [ ] **4. Split `Library` (`core.py`, 27 methods):** a store (books, progress, `.library/` files), the
  folder scanner, the LitRes merge (into the connector) and reading statistics.
- [ ] **5. Real components instead of mixins (SRP, ISP):** `LibraryPage` as a widget with explicit
  dependencies (library model, settings, notifications) instead of a mixin sharing `App` state; settings
  tabs as separate classes (`SettingsPage` is 753 lines, `build()` 171); give `LitresConnector` (27 `App`
  attributes) and the settings page (32) narrow interfaces instead of the whole `App`; move the LitRes
  folders dialog out of the connector.
- [ ] **6. Long methods:** `PlayerPage.__init__` (137 lines), `singularity.show_dialog` (122),
  `LitresConnector.download_book` (92) and `sync` (82), `ReaderPage._build_settings` (87) and `_on_message`
  (72), `App.__init__` (93) and `main` (78).

## Reader — first priority
- [ ] **Highlights and notes exported to Obsidian.** Select a quote, add a comment; quotes are collected
  on the book's page in the wiki with links back to the place in the book. foliate-js can already draw
  highlights (overlayer).
  - **"Obsidian vault" setting**: choose the vault folder (`~/Documents` by default), check that it has
    `CLAUDE.md` / `wiki/` following Karpathy's LLM Wiki layout;
  - notes go to the wiki layer; sources (`Books/`, `articles/`, `trainings/`) are never touched;
  - a separate file per book, `wiki/highlights/<Book>.md` (not the `wiki/sources/…` card: cards with
    `status: indexed` are rebuilt by `build_index.py`); frontmatter per the schema: `type: highlights`,
    `title`, `sources: [[sources/<Book>]]`, `created`, `updated`;
  - a link to the highlights page in the source card; an entry in `wiki/log.md` in the
    `## [YYYY-MM-DD] highlights | <Book>` format (append only);
  - each quote: text, comment, chapter, link to the place in the book (`litreader://` with a CFI);
  - highlights of your own books are stored in the library's `.library/` (they travel with the folder);
  - export right away or with a "To Obsidian" button; edits made in Obsidian are not overwritten.
- [ ] **Full-text search in a book** with jumping to results — foliate-js has it, needs a UI.
- [ ] **Bookmarks** — several marked places in a book, not only the last one (stored in `.library/`
  for your own books).
- [ ] **Dictionary and translation of the selected word** — for books and articles in English.
- [ ] **Read aloud in the Flatpak** — QtTextToSpeech needs speech-dispatcher (`libspeechd` and the host
  socket); today it is unavailable there.

## Libraries
- [ ] **More pluggable libraries:** OPDS catalogs (Calibre server, public catalogs) and other stores as
  connectors next to LitRes (`litres_connector.py` is the pattern).
- [ ] **Conflicting `.library` copies** — when a library folder is edited on two computers, cloud sync
  (rclone) leaves conflict copies; merge them (positions — latest wins, marks and bookmarks — union).
- [ ] **Library metadata from files:** title, authors and cover from EPUB/FB2 metadata instead of the file
  name (PDF covers already come from the first page).
- [ ] **Rework the backup logic** — per-library backups are done. Still to revisit: restoring one library
  without a restart, automatic backups per library, how backups relate to cloud sync.
- [ ] **Sync app-level data with the cloud** — your libraries' data already travels with their folders
  (`.library/`); what's left is LitRes data, statistics and settings. Google Drive (`appDataFolder`) or
  Yandex Disk (`app:/`), OAuth in the browser, token in the keyring or 0600; merging: positions — latest
  wins, statistics — per day with the maximum; works offline.
- [ ] **New books by favourite authors and series**: "the next book in the series is out" with a link to
  buy it on LitRes.
- [ ] **Download new LitRes purchases automatically**; how much space downloaded books take; removing
  downloaded finished books.

## Statistics and habit
- [ ] **Weekly and yearly goals** ("24 books a year") in addition to the daily one; monthly and yearly
  summaries; an estimate of when you'll finish the current book at your pace.
- [ ] **Evening reminder to read** if the daily goal isn't reached.

## Appearance and convenience
- [ ] **Menu and tooltip labels follow custom shortcuts** — "Book graph (Ctrl+G)", "Search (Ctrl+F)" still
  show the defaults after a shortcut is changed.
- [ ] **App icon choice on Windows** — today it changes only the window icon; the Start menu and desktop
  shortcuts keep the installer's icon.
- [ ] **Tablet mode**: large page-turn zones, volume keys to turn pages, rotation without losing the place.
- [ ] **A note on a finished book** when marking it as read: a rating and a couple of lines that go to the
  book's card in the wiki.

## Performance
- [ ] **First start after an update** rebuilds the cover thumbnail cache (~3.5 s once); stale thumbnails
  of removed covers are never deleted — prune `<cache>/thumbs`.
- [ ] **Graph and reader pages** each create their own QtWebEngine view; reuse one profile/process where
  possible to save memory.

## Distribution
- [ ] **Flathub** — submit the Flatpak (metainfo screenshots, release notes in metainfo per version).
- [ ] **Windows code signing** — the unsigned installer triggers a SmartScreen warning.
- [ ] **Update check** — tell the user when a newer release is on GitHub.
