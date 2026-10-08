# TODO

Ideas for the next versions, most useful first. Finished items move to [CHANGELOG.md](CHANGELOG.md).

## Refactoring — before the bigger items below
Behaviour doesn't change; after each step, check the installed version.
- [x] **Tests** (before splitting the code): `Library` (merging with LitRes, statuses, percentages),
  backups (create, restore, Singularity token), translation coverage (every `tr()` key is in
  `i18n_en.py`, placeholders match), all `web/` and `data/` files end up in the installed package
  (that is why the graph and PDF were broken in 0.11.0).
- [ ] **Split the `App` class** (`app.py`, ~1300 lines after moving LitRes out; LitRes sync, downloads,
  folders dialog and remote position already live in `litres_connector.py`):
  - `library.py` — the library page: filters, grid, "Continue reading";
  - the Singularity dialog → `singularity.py`, the folders dialog → its own module;
  - `App` keeps the window, navigation and the wiring between parts.
- [ ] **Remove duplication:** theme and font lists (`reader.py` and `settings.py`); the frameless
  dialog boilerplate (statistics, folders, Singularity) → a shared widget in `widgets.py`.
- [x] **Public methods instead of private ones:** settings call `toggle_account`, `download_all`,
  `add/rename/remove_local_folder`.
- [ ] **Small things:** lines longer than 120 characters after the translation wrap, the
  `_books_word` wrapper around `plural`, two `except Exception` blocks to narrow down.

## Reader — first priority
- [ ] **Highlights and notes exported to Obsidian.** Select a quote, add a comment; quotes are
  collected on the book's page in the wiki with links back to the place in the book.
  foliate-js can already draw highlights (overlayer).
  - **"Obsidian vault" setting**: choose the vault folder (`~/Documents` by default), check that it
    has `CLAUDE.md` / `wiki/` following Karpathy's LLM Wiki layout;
  - notes go to the wiki layer; sources (`Books/`, `articles/`, `trainings/`) are never touched;
  - a separate file per book, `wiki/highlights/<Book>.md` (not the `wiki/sources/…` card: cards
    with `status: indexed` are rebuilt by `build_index.py`); frontmatter per the schema:
    `type: highlights`, `title`, `sources: [[sources/<Book>]]`, `created`, `updated`;
  - a link to the highlights page in the source card; an entry in `wiki/log.md` in the
    `## [YYYY-MM-DD] highlights | <Book>` format (append only);
  - each quote: text, comment, chapter, link to the place in the book (`litreader://` with a CFI —
    opens the book in the reader at that place);
  - export right away or with an "To Obsidian" button; edits made in Obsidian are not overwritten.
- [ ] **Full-text search in a book** with jumping to results — foliate-js has it, needs a UI.
- [ ] **Bookmarks** — several marked places in a book, not only the last one.
- [ ] **Dictionary and translation of the selected word** — for books and articles in English.

## Library and sync
- [ ] **Rework the backup logic** (Backups tab, `backup.py`). To revisit: backup contents and
  format, schedule and retention (how many to keep, which to delete), restoring without a restart,
  how it relates to the future cloud sync (so that backups and sync don't duplicate each other).
- [ ] **Sync app data directly with the cloud** — Google Drive or Yandex Disk, chosen and signed in
  to in the app settings (not via the `~/Documents` folder). What to sync: highlights, notes,
  bookmarks, reading positions of your own books and PDFs, statistics and settings, so everything
  moves between computers (Linux and Windows). Today it is stored only locally.
  - OAuth sign-in in the browser, the token stored with 0600 permissions (or in the system keyring);
  - Google Drive — the hidden app folder (`appDataFolder`), Yandex Disk — `app:/` (app folder);
  - conflict merging: reading position — the latest wins, highlights and bookmarks — union,
    statistics — per day with the maximum;
  - sync on startup, when closing a book and every N minutes; works fine offline.
- [ ] **New books by favourite authors and series**: "the next book in the series is out" with a
  link to buy it on LitRes.
- [ ] **Download new purchases automatically**; how much space downloaded books take; removing
  downloaded finished books.

## Statistics and habit
- [ ] **Weekly and yearly goals** ("24 books a year") in addition to the daily one; monthly and
  yearly summaries; an estimate of when you'll finish the current book at your pace.
- [ ] **Evening reminder to read** if the daily goal isn't reached.

## Convenience
- [ ] **Tablet mode**: large page-turn zones, volume keys to turn pages, rotation without losing
  the place.
- [ ] **A note on a finished book** when marking it as read: a rating and a couple of lines that go
  to the book's card in the wiki.
