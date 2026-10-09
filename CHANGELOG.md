# Changelog

All notable changes to Muninhall (called LitRes Reader / «Читалка ЛитРес» before 0.16 and Shelfwise in 0.16). The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- New default app icon: the letter "M" formed by two raven wings (SVG and a multi-size `.ico`).

### Added
- Settings → **Appearance** tab:
  - interface theme (system, light, dark) and accent color (system or the GNOME palette), applied
    immediately;
  - app icon: nine icons to choose from (wings "M" — the default, the raven in the hall, raven and the
    moon, flight at sunset, Huginn and Muninn, rune stone, the hall, raven quill, raven's eye); changes the
    window icon and, for an installed app on Linux, the app menu icon;
  - keyboard shortcuts for refresh, search, open file, graph, statistics, settings, full screen and
    back; conflicts are pointed out; "Reset shortcuts" restores the defaults.

### Fixed
- Linux installer: the user icon cache was not refreshed (no `index.theme` in `~/.local/share/icons/hicolor`),
  so a stale cache hid the new app icon; the cache is now rebuilt with `gtk-update-icon-cache -f -t`.

## [0.17.0] — 2026-10-09

### Changed
- **Renamed to Muninhall** — "the hall of Muninn", Odin's raven of memory — because the name Shelfwise
  is already taken. Package and command `muninhall` (`litres-reader` stays as an alias; `shelfwise` is
  removed), app ID `io.github.arvino_t.Muninhall`, data folders `muninhall`, default backup folder
  `Documents/Backups/muninhall`, backup files `muninhall-backup-…`, GitHub repository
  `arvino-t/muninhall`, environment variables `MUNINHALL_DEBUG` / `MUNINHALL_LANG` (the Shelfwise and
  LitRes Reader ones still work).
- Data, backups and the backup folder of both previous versions (Shelfwise and «Читалка ЛитРес») are
  migrated on first start; the installers remove both previous installations.

## [0.16.0] — 2026-10-09

### Changed
- **Renamed to Shelfwise** (formerly LitRes Reader / «Читалка ЛитРес»): app name, package and command
  `shelfwise` (the `litres-reader` command stays as an alias), app ID `io.github.arvino_t.Shelfwise`,
  data folders `~/.local/share/shelfwise`, `~/.config/shelfwise`, `~/.cache/shelfwise` (Windows:
  `%LOCALAPPDATA%\shelfwise`, `%APPDATA%\shelfwise`), default backup folder `Documents/Backups/shelfwise`,
  backup files `shelfwise-backup-…`, the GitHub repository `arvino-t/shelfwise`. Environment variables
  `SHELFWISE_DEBUG` and `SHELFWISE_LANG` (the old `LITREADER_*` still work).
- On first start Shelfwise moves the old version's data (library, positions, settings, LitRes session,
  backup folder) into its folders; if the old version is still open, it asks you to close it first.
  Old backups are listed and can be restored. The installers remove the old version's shortcut, icon,
  menu entry and program files.
- New app icon: a bookshelf in the GNOME style instead of the LitRes logo (SVG for Linux, a
  multi-size `.ico` for Windows).
- About: describes the app as your own library manager with LitRes as a pluggable library, shows the
  number of libraries and books, credits pdf.js, d3-force and Adwaita, and has an "Open on GitHub"
  button; Settings → Advanced → About shows the icon, a "More…" button and a link to the docs.

## [0.15.0] — 2026-10-09

The app is now a manager for **your own library**: you add libraries (folders on disk), read and
organize them, and browse them together as one big library. LitRes becomes a pluggable commercial
library. The interface stays the same — "Source" is now the name of a library.

### Added
- **Libraries**: a registry of libraries (`libraries` setting) replaces `localFolders`; existing
  folders and LitRes are migrated automatically on first start.
- A library's data (read marks, reading positions, graph state) is stored in its own folder,
  `<root>/.library/`, keyed by the path inside the library — it travels with the books (cloud sync,
  another computer). Data of your books is moved there from the app's shared files on first start.
- Settings → **Libraries** tab: your libraries (folder, book count, Rename, Remove from the app) and
  LitRes (sign in/out, books folder, Disconnect); "Add library…" adds a folder library or connects
  LitRes. The Folders group moved here from General.
- **Graph per library:** a library selector in the graph header (All libraries, LitRes, each of your
  libraries), defaulting to the library chosen in the Source filter; graph state is kept per library.
- **Backups per library:** a library selector on the Backups tab; an "All libraries" backup (also the
  automatic one) holds settings, statistics, Singularity and every library's data; a library backup
  holds only its marks, positions and graph. Retention is counted per library; restoring one library
  doesn't touch the others.
- **Statistics by library:** a library selector in the statistics window; reading time is also
  recorded per library (earlier time is attributed to LitRes when only LitRes books were read).
- **Singularity by library:** choose whose books become tasks ("Want to read" stays LitRes-only).
- User guide in Russian and English in `docs/ru/` and `docs/en/`.
- Test suite (`tests/`, pytest): library model, folder scanning and stores, migration, backups,
  graph scope, statistics, Singularity filter, translation coverage, package data.

### Changed
- The Source filter lists libraries: All, LitRes (Books, Audiobooks) and each of your libraries;
  Subfolder shows the folders of the selected library.
- LitRes is optional: when disconnected, its books, sign-in, sync and "Download all" disappear from the
  app (data and session are kept); F5 then rescans your folders.
- LitRes is a connector (`litres_connector.py`): sign-in, sync, downloads, LitRes folders, the position
  from the phone and genre loading moved out of the main window class.
- Project documentation (README, CHANGELOG, TODO) and GitHub texts are in English.

### Fixed
- Backups made within the same second could be pruned in the wrong order, deleting the newest one.
- Switching the graph between libraries carried over the previous library's filters.

## [0.14.0] — 2026-10-09

### Added
- Sections for your own folders: when adding a folder you give it a section name ("Articles",
  "Lectures"…). The section is shown on cards instead of the folder name and as its own item in
  the library filter ("— Articles"); you can rename it in Settings. Default folders are "Other
  books", "Articles" and "Trainings and presentations"; folders added earlier use the folder name.

### Changed
- The library filter is grouped by source: "LitRes" (with "Books" and "Audiobooks" under it) and
  "My books and articles" (with the sections of your folders under it). The "LitRes" item shows
  books and audiobooks together.
- Library filters — status, Source, Subfolder, Sort by — have captions above them. Subfolder
  depends on the source: your LitRes folders for LitRes, folders on disk inside the section for
  your own books (nested ones too; choosing a folder also shows its subfolders). The subfolder
  choice is remembered separately for LitRes and for your own books.
- The counters on the status buttons ("All · N", "Reading · N"…) count the books of the selected
  source and subfolder (and "Downloaded only") instead of the whole library.

## [0.13.0] — 2026-10-09

### Added
- Download all books at once: menu → "Download all books…". Choose books only or books together
  with audiobooks. Books are downloaded one at a time with progress in the header; stop with the
  same menu item; a summary at the end, and books that failed go to the log.
- Settings are split into tabs: General, Reading, Integrations, Backups and Advanced; the last
  opened tab is remembered.
- Third-party service icons (LitRes, Singularity) on the Integrations tab: from the system icon
  theme if the app is installed, otherwise the site's favicon (downloaded once and cached).
- Advanced tab: LitRes refresh interval and "Refresh now", reading speed for estimating phone
  reading, verbose log without a restart (same as `LITREADER_DEBUG=1`), data, settings and cache
  folders, reset settings (folders, sign-in and library are kept).
- Backups tab: back up on demand and automatically (daily or weekly, weekly by default), how many
  to keep, backup folder (`Documents/Backups/litres-reader` by default), restore from the list of
  recent backups or from a file. Before restoring, the current data is backed up separately; the
  app restarts and moves the files in place before reading its data. A backup contains settings,
  the library, reading positions, statistics and Singularity settings; the Singularity token only
  if enabled. Backups are owner-only (0600).
- English interface: Settings → General → Interface language (system default, Russian, English),
  applied after a restart — with a Restart button right in the notification. The app, reader,
  player, graph, statistics and settings are translated; texts sent to Singularity (project names,
  habits, notes) stay in Russian so that switching the language doesn't create duplicates there.
  For development: `LITREADER_LANG=en|ru`.

### Changed
- The selected button in segmented toggles is now highlighted.

## [0.12.0] — 2026-10-09

### Added
- Statistics include reading on the phone and the LitRes website: on sync, the progress gained is
  converted into time (text by book length, about 1300 characters per minute; audio by duration)
  and recorded for the day of reading, at most 4 hours per sync. Books finished on the phone count
  as finished; the statistics window shows "of them on the phone", and that part of a chart bar is
  lighter.
- Settings page (menu, Ctrl+,): startup and library, folders, text appearance, read aloud and auto
  page turn, audio, statistics, account and Singularity, about. Changes apply immediately; the app
  menu is shorter.
- New settings: how often to refresh the library from LitRes (0 — off) and the reading speed for
  estimating phone reading.
- Graph: "Building the graph… / Layout — N%" and "Loading genres from LitRes: N of M" indicators on
  the page and under the window title.

### Changed
- The graph builds in 2–3 seconds instead of 15+ (about 530 nodes): several layout steps per frame
  and one redraw per frame.
- JavaScript errors in the reader and graph are always logged, not only in debug mode.

### Fixed
- In the installed 0.11.0 the graph kept "building" forever ("d3 is not defined") and PDFs didn't
  open: the `web/vendor` and `web/foliate/vendor/pdfjs` folders were missing from the package.

## [0.11.0] — 2026-10-08

### Added
- Folder for downloaded books: choose a directory; already downloaded books are moved there.
- Your own books and articles from folders (`Documents/Books/others`, `articles`, `trainings` by
  default): files open in place, a "My books and articles" filter, the folder topic as the caption,
  PDF covers from the first page.
- PDF reading in the app (pdf.js from foliate-js); the position is restored.
- "Continue reading" takes reading on LitRes (phone, website) into account: the last read time and
  chapter come from wherever you read later; finished and merely opened books are not shown.
- While the window is open, the library quietly refreshes from LitRes every 15 minutes.
- On startup the app opens the last text book (started, not finished, downloaded); audiobooks
  don't start by themselves.
- Book graph by tags, like in Obsidian (menu, Ctrl+G): LitRes genres and tags, folders, series,
  authors, topics of your own books; zoom, drag, link highlighting, search, filters.

### Security
- Links from books open in the system only for `http`, `https` and `mailto`.
- LitRes API requests run in an isolated JavaScript world with a random session token: site
  scripts can't forge responses.
- A LitRes book ID is accepted only as digits (it is part of file paths).
- Titles, authors and file names are shown as plain text, not HTML.
- Data files are written with 0600 permissions.
- PySide6 is pinned to `>=6.10,<6.12`.

### Fixed
- Singularity: your own articles don't go to "Want to read".
- "Download" and "Open on the website" in the book menu were shown only when there was a next book
  in the series.

### Known issues
- The graph and PDF reading don't work in the installed package — fixed in 0.12.0.

## [0.10.0] — 2026-09-30

### Added
- Library sorting: recent, as on LitRes, title, author, series, progress, purchase date
  (remembered).
- Series and number on the card; "Next in the series" in the book menu and in the "book finished"
  notification.
- Reading statistics: minutes per day for two weeks, day streak, finished books, books with the
  most time.
- Reader gestures: pinch and Ctrl+wheel change the font size, swipe up opens the contents.
- Auto page turn with an adjustable interval.
- Read aloud with sentence highlighting and page turning.

## [0.9.0] — 2026-09-30

### Added
- "Continue reading" panel on the right of the library: the two latest books being read, with
  chapter, progress and a Read/Listen button; hidden in a narrow window.
- The accent colour comes from the system and updates on the fly.

### Changed
- The VPN bypass help no longer depends on the project folder.

## [0.8.0] — 2026-09-29

### Added
- Singularity sync: "Reading" tasks in the "Книги" project with percent and chapter, a "Want to
  read" list, the "Чтение N минут" habit checked automatically.
- An audiobook resumes playing right away when opened and on startup.
- If a book was read further on LitRes, the app jumps there by itself (with an Undo button).
- Quiet LitRes sync on startup.

### Fixed
- Errors creating "Want to read" in Singularity are shown in the settings window.

## [0.7.0] — 2026-09-29

### Added
- Audiobook chapters from M4B markers; for an MP3 folder, one chapter per file. Chapter list,
  navigation, slider within the chapter, "At the end of the chapter" sleep timer.
- On startup the last book opens at the place where you stopped.
- For audiobooks — an offer to jump to the position listened to on LitRes.

### Changed
- Sliders jump to the clicked point; the time updates live while dragging.
- Installers always install the latest code, even without a version change.

### Fixed
- Reader bars no longer disappear under the page or hide by themselves after 3 seconds.

## [0.6.0] — 2026-09-29

### Changed
- The app was rewritten in Qt 6 (PySide6) and runs on Linux and Windows: LitRes sign-in and API in
  the built-in Chromium, the player on QtMultimedia, a libadwaita-style look.

### Added
- Single app instance, opening files from the system.
- Python package with the `litres-reader` command.
- `install.sh` for Linux; `windows/install.ps1` and `install.cmd` for Windows.

## [0.5.0] — 2026-09-29

### Added
- First version (GTK 4, libadwaita, WebKitGTK 6): LitRes sign-in on the website without storing
  the password, list of purchased books, EPUB/FB2/MOBI download, a reader based on foliate-js.
- "Reading / Unread / Read" filters, by LitRes folder and "No folder".
- Sync of the "read" mark and folders with LitRes.
- Audiobooks: M4B or MP3 archive download, a player with chapters, speed without changing the voice
  pitch and a sleep timer.
- VPN bypass for LitRes (`vpn-bypass/`).

[Unreleased]: https://github.com/arvino-t/muninhall/compare/v0.17.0...HEAD
[0.17.0]: https://github.com/arvino-t/muninhall/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/arvino-t/muninhall/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/arvino-t/muninhall/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/arvino-t/muninhall/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/arvino-t/muninhall/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/arvino-t/muninhall/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/arvino-t/muninhall/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/arvino-t/muninhall/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/arvino-t/muninhall/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/arvino-t/muninhall/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/arvino-t/muninhall/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/arvino-t/muninhall/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/arvino-t/muninhall/releases/tag/v0.5.0
