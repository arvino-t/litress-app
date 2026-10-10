# TODO

Ideas for the next versions, most useful first. Finished items move to [CHANGELOG.md](CHANGELOG.md).
Reviewed: 2026-10-10 (after 1.1.0).

## Check first
- [ ] **LitRes with a real session after the connector move (0.15), the lazy Chromium (0.18) and the
  sync/download split (1.1):** sign-in, F5 sync, downloading one book and "Download all", LitRes folders,
  the position from the phone. Sync and download logic are tested against a fake server
  (`tests/test_litres_connector.py`); the real site and the web view are not.
- [ ] **Installers on real machines:** `Muninhall-Setup-*.exe` on Windows 10/11 (install, file
  associations, uninstall, restart after a restore in the frozen build) and `Muninhall.flatpak` on Linux
  (data shared with the native install, LitRes sign-in inside the sandbox).

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
  connectors next to LitRes (a new `LibrarySource` subclass in `libraries.KINDS`; `litres_connector.py` is the pattern for sync).
- [ ] **Conflicting `.library` copies** — when a library folder is edited on two computers, cloud sync
  (rclone) leaves conflict copies; merge them (positions — latest wins, marks and bookmarks — union).
- [ ] **Library metadata from files:** books in library folders are titled by the file name (recomputed on
  every scan); read title, authors and cover from EPUB/FB2 metadata during the scan. PDF covers already
  come from the first page; a file opened with "Open file" already takes title and author from the book.
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
- [ ] **Narrow window mode is unreachable:** the window's minimum width is 1025 px (header and filter bar
  size hints), so the "Continue reading" panel, which hides below 900 px, never hides; let the filter bar
  wrap or shrink so the window can get narrower (tablet portrait).
- [ ] **Menu and tooltip labels follow custom shortcuts** — "Book graph (Ctrl+G)", "Search (Ctrl+F)" still
  show the defaults after a shortcut is changed.
- [ ] **App icon choice on Windows** — today it changes only the window icon; the Start menu and desktop
  shortcuts keep the installer's icon.
- [ ] **Tablet mode**: large page-turn zones, volume keys to turn pages, rotation without losing the place.
- [ ] **A note on a finished book** when marking it as read: a rating and a couple of lines that go to the
  book's card in the wiki.

## Performance
- [ ] **Stale cover thumbnails** are never deleted — prune `<cache>/thumbs` of covers that no longer exist
  (the cache is rebuilt once after an update, ~3.5 s).

## Distribution
- [ ] **Flathub** — submit the Flatpak; metainfo still lacks screenshots, and release notes there are
  written for 1.0.0 and 1.1.0 only.
- [ ] **Windows code signing** — the unsigned installer triggers a SmartScreen warning.
- [ ] **Update check** — tell the user when a newer release is on GitHub.
