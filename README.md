# LitRes Reader

A desktop app for Linux and Windows to build, read and organize **your own library** of e-books and
articles, and to look after it with extra features. A library is a folder on disk (EPUB, FB2, MOBI,
PDF); you can add several and browse them together as one big library. Each library keeps its data
(marks, reading positions, graph) inside its folder, has its own graph and its own backups.
[LitRes](https://www.litres.ru) is a pluggable commercial library: the app signs in on the LitRes
website in a built-in browser and downloads purchased books and audiobooks. Books open in a built-in
reader and audiobook player (M4B, MP3). The UI follows GNOME's libadwaita style on both systems and
is available in Russian and English.

**User guide:** [English](docs/en/user-guide.md) · [Русский](docs/ru/user-guide.md)

## Features

- **Libraries** — named folder libraries with subfolder filtering; files are opened in place, data
  lives in `<library>/.library/` and travels with the folder (e.g. via cloud sync).
- **LitRes (optional)** — purchased books and audiobooks, LitRes folders, "read" marks synced both
  ways, download one book or all of them at once; can be disconnected.
- **Reader** — page turning by tap, swipe and keys; themes, fonts and layout; contents; gestures;
  auto page turn; read aloud with sentence highlighting; PDF via pdf.js.
- **Audiobook player** — M4B chapters, speed 0.75–2× without pitch change, sleep timer, background
  playback.
- **Continue reading** — resumes the last book on startup and picks up the position from your phone
  or the LitRes website.
- **Book graph** — an Obsidian-style graph of books and tags (genres, folders, series, authors,
  topics), per library or for all of them.
- **Reading statistics** — minutes per day, streaks, finished books, including reading on the phone;
  for all libraries or one.
- **Backups** — manual and scheduled backups for all libraries or one; restore from a list or a file.
- **Singularity integration** — "Reading" tasks, progress notes and a daily reading habit in
  [SingularityApp](https://singularity-app.com).

## Installation

### Linux (Fedora, Ubuntu/Debian, Arch)

```
bash install.sh              # install or update
bash install.sh --uninstall  # remove
```

Installs for the current user into `~/.local/opt/litres-reader` (a venv with PySide6), adds the
`litres-reader` command, a menu entry and file associations. `sudo` is requested only for missing
system libraries.

### Windows 10/11

Double-click `install.cmd` (or `powershell -ExecutionPolicy Bypass -File windows\install.ps1`).
No administrator rights needed; Python 3.12 is installed via winget if Python 3.10+ is missing.

See the user guide for details. The first installation downloads PySide6 (~600 MB).

## Development

### Run from source

```
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/litres-reader
```

Requires Python 3.10+ and `PySide6>=6.10,<6.12` (Qt 6 with QtWebEngine).

### Tests

```
.venv/bin/pip install -e .[dev]
.venv/bin/python -m pytest
```

The tests use the source tree and a temporary data directory (never your real data). They cover
the library model and folder scanning, library stores and migration, backups (all and per library),
the graph scope, per-library statistics, the Singularity filter, translation coverage and package data.

Environment variables:

| Variable | Effect |
|---|---|
| `LITREADER_DEBUG=1` | verbose log: LitRes requests, downloads, page messages; DevTools via right click in the reader |
| `LITREADER_LANG=en\|ru` | force the interface language |

### Project layout

| Path | Contents |
|---|---|
| `litres_reader/app.py` | main window, library page and filters, own libraries, dialogs, app startup |
| `litres_reader/core.py` | paths, default settings, the `Library` model (books, progress, statistics, per-library stores) |
| `litres_reader/libraries.py` | the registry of libraries (`libraries` setting) and its migration |
| `litres_reader/litres_connector.py` | the LitRes connector: sign-in, sync, downloads, LitRes folders, remote position |
| `litres_reader/litres.py` | LitRes session and API inside the built-in Chromium (QtWebEngine) |
| `litres_reader/reader.py` | reader page (foliate-js in QtWebEngine), `litreader://` scheme |
| `litres_reader/player.py` | audiobook player (QtMultimedia), M4B chapter parsing |
| `litres_reader/settings.py` | settings page (tabs: General, Reading, Integrations, Backups, Advanced) |
| `litres_reader/backup.py` | backup archives (all libraries or one) and two-step restore |
| `litres_reader/graph.py` | book graph data and page |
| `litres_reader/stats.py` | reading statistics dialog |
| `litres_reader/singularity.py` | SingularityApp sync |
| `litres_reader/i18n.py`, `i18n_en.py` | translations: `tr()` with Russian source strings as keys, English dictionary |
| `litres_reader/widgets.py`, `style.py` | libadwaita-style widgets and stylesheet |
| `litres_reader/web/` | reader and graph pages, `litres-hook.js` (passes API headers from the LitRes site; doesn't touch passwords or forms) |
| `litres_reader/web/foliate/` | [foliate-js](https://github.com/johnfactotum/foliate-js) rendering engine (MIT) with pdf.js |
| `litres_reader/web/vendor/` | d3-force, d3-quadtree, d3-dispatch, d3-timer (ISC) for the graph |
| `litres_reader/data/sym/` | Adwaita symbolic icons (CC-BY-SA 3.0 / LGPLv3) |
| `install.sh`, `install.cmd`, `windows/` | installers |
| `vpn-bypass/` | Linux scripts to reach LitRes directly while a VPN is on |
| `docs/en/`, `docs/ru/` | user guide in English and Russian |
| `tests/` | pytest suite |

### Translations

UI strings are written in Russian and wrapped in `tr()`: `tr("Скачано {0} из {1}", done, total)`.
The English text for each string lives in `litres_reader/i18n_en.py`; plurals use `plural()`.
Strings for the web pages are listed in `WEB_KEYS` in `i18n.py` and passed to the page with its data.
When adding a string, add its English translation too — a missing one falls back to Russian.

### Packaging note

Every asset folder must be listed in `[tool.setuptools.package-data]` in `pyproject.toml`.
Test features against the installed package (`bash install.sh`), not only the source tree.

### Releases

Bump the version in `pyproject.toml` and `litres_reader/__init__.py`, move the "Unreleased"
section of [CHANGELOG.md](CHANGELOG.md) under the new version, tag `vX.Y.Z` and publish a GitHub
release with that section as notes. Planned work is in [TODO.md](TODO.md).

## Security

- Scripts inside books are not executed (page CSP); external images and fonts from books are not
  loaded.
- Links from books open in the system only for `http`, `https` and `mailto`.
- LitRes API calls run in an isolated JavaScript world of the litres.ru page; responses carry a
  random session token so site scripts can't forge them.
- PDFs are rendered by pdf.js with `eval` disabled; book files are served only by a one-time token
  of the open book.
- Data files (library, progress, settings, tokens, backups) are created with 0600 permissions.

## Limitations

- LitRes has no public API; the app uses the same endpoints as the website (some were found by the
  [bookvault](https://github.com/mavrovde/bookvault) project). If LitRes changes them, the book
  list or downloads will break.
- DRM-protected and online-only books don't open.
- Only the "read" mark is written back to LitRes, not the exact position.
- No automatic hyphenation: QtWebEngine ships without hyphenation dictionaries.

## License

MIT.
