# LitRes Reader — user guide

[Русская версия](../ru/user-guide.md)

LitRes Reader is a Linux and Windows app for the books and audiobooks you bought on
[LitRes](https://www.litres.ru). It downloads them and opens them in a built-in reader and audio
player. It also opens your own books and articles (EPUB, FB2, MOBI, PDF) straight from folders on
disk. The look follows GNOME; light and dark themes follow the system. The interface is available
in Russian and English.

## Contents

- [Installation](#installation)
- [Signing in to LitRes](#signing-in-to-litres)
- [Library](#library)
- [Your own books and articles](#your-own-books-and-articles)
- [Reading](#reading)
- [Audiobooks](#audiobooks)
- [Continue reading and auto-resume](#continue-reading-and-auto-resume)
- [Book graph](#book-graph)
- [Reading statistics](#reading-statistics)
- [Settings](#settings)
- [Backups](#backups)
- [Singularity](#singularity)
- [LitRes and VPN (Linux)](#litres-and-vpn-linux)
- [Where data is stored](#where-data-is-stored)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Limitations](#limitations)

## Installation

### Linux (Fedora, Ubuntu/Debian, Arch)

```
bash install.sh              # install or update
bash install.sh --uninstall  # remove
```

The app is installed for the current user. `sudo` is requested only if system libraries are
missing (Python 3.10+, venv, libraries for Qt and Chromium). The app lives in
`~/.local/opt/litres-reader`, the command is `litres-reader`, and "LitRes Reader" appears in the
app menu; EPUB, FB2 and MOBI files open with it.

### Windows 10/11

Double-click `install.cmd` (or run
`powershell -ExecutionPolicy Bypass -File windows\install.ps1`).

No administrator rights are needed. If Python 3.10+ is not found, the installer gets Python 3.12
via winget. The app lives in `%LOCALAPPDATA%\Programs\LitresReader`, shortcuts go to the Start menu
and the desktop, and EPUB, FB2 and MOBI are added to "Open with" (default apps are not changed).
Uninstall via "Settings → Apps".

The first installation takes a while: PySide6 (Qt with the built-in Chromium) is about 600 MB.

## Signing in to LitRes

Menu → "Sign in to LitRes". The LitRes website opens — sign in as usual: with a password, an SMS
code or a social account. The app never sees or stores your password; after you sign in it uses
the session of its built-in browser. "Sign out of LitRes" (in the menu or in Settings →
Integrations) erases the session; downloaded books and progress stay.

## Library

After you sign in, the books from your account load automatically. Refresh with F5 or the button
at the top left; while the window is open the library also refreshes by itself (every 15 minutes
by default). Search by title and author with Ctrl+F.

**Filters** above the list:

- **Status** — All, Reading, Unread, Read. The numbers on the buttons count the books of the
  selected source and subfolder.
- **Source** — All, LitRes (with Books and Audiobooks under it) and My books and articles (with
  the sections of your folders under it).
- **Subfolder** — for LitRes, your LitRes folders (and No folder); for your own books, the folders
  on disk inside the section. Choosing a folder also shows the books in its subfolders.
- **Sort by** — recent, as on LitRes, title, author, series, progress, purchase date.

**Book card.** Click a cover — the book is downloaded (EPUB, otherwise FB2 or MOBI) and opened.
A long press or right click opens a menu: read or listen, mark as read, LitRes folders, download
again, open on the website, next in the series, show the file, remove from this device. The cover
shows progress, series and number; when you finish a book, the app offers the next one in the
series.

**LitRes folders:** book menu → "Folders…". Changes are sent to LitRes right away, or on the next
sync if you are offline.

**Download all books:** menu → "Download all books…" (or Settings → General). Choose books only or
books together with audiobooks. Books are downloaded one at a time with progress in the header;
stop with the same menu item. At the end you see a summary; books that failed and the reasons go to
the log.

## Your own books and articles

The app finds EPUB, FB2, MOBI and PDF files in folders by itself. By default these are three
folders in Documents:

| Folder | Section |
|---|---|
| `Documents/Books/others` | Other books |
| `Documents/articles` | Articles |
| `Documents/trainings` | Trainings and presentations |

Set up folders in Settings → General → Folders: "Add folder…" (the app asks for a section name),
"Rename…", "Remove", "Rescan" (F5 rescans too). The section is shown on cards and as its own item
in the Source filter; subfolders appear in the Subfolder filter.

Files open in place: the app doesn't copy, rename or delete them. The reading position is saved;
a PDF's cover is its first page.

## Reading

- **Turning pages:** tap the left or right third of the page, swipe, arrow keys, PageUp/PageDown,
  Space. Tapping the middle of the page hides and shows the bars for distraction-free reading
  (the chapter and percent stay in the page corners).
- **Bars:** at the top — Back, Contents, Text appearance, auto page turn, read aloud and full screen;
  at the bottom — a slider through the book. Clicking the slider jumps right to that place.
- **Text appearance** ("Aa" button): font size, theme (auto, light, sepia, dark, black), font, line
  spacing, margins, line width, two pages in landscape, justified text.
- **Gestures:** pinch or Ctrl+wheel changes the font size, swipe up opens the contents, swipe down
  hides or shows the bars.
- **Auto page turn:** turns the page every N seconds (5–120 s). Turning a page by hand restarts
  the countdown.
- **Read aloud:** reads from the current place, highlights the sentence and turns pages and chapters
  by itself. Uses the system voice (Linux — speech-dispatcher, Windows — SAPI). For a more natural
  Russian voice on Linux, install RHVoice (`sudo dnf install rhvoice speech-dispatcher-rhvoice`
  or similar).
- **PDF** opens right in the app; pages are shown as they are, without reflowing the text.
- F11 — full screen, Esc — leave full screen or go back.

## Audiobooks

Audiobooks have a headphones badge. The app downloads an M4B file or an MP3 archive and opens the
player.

- Chapters come from the markers inside the M4B (for MP3 — one file per chapter): a chapter list
  with start times, previous and next chapter; the slider and time are within the chapter.
- Skip back 15 and forward 30 seconds; speed from 0.75× to 2× without changing the voice pitch.
- Sleep timer: after N minutes or "At the end of the chapter".
- Going back to the library doesn't stop the sound; a button in the header returns to the player.
- Space — pause, arrow keys — seek.

## Continue reading and auto-resume

- **The Continue reading panel** on the right of the library shows the latest started books — read
  in the app or on your phone or the LitRes website.
- **On startup** the app opens the last text book at the place where you stopped — the most recent
  of the started and downloaded books, including reading on LitRes. Audiobooks don't start by
  themselves. Turn this off in the menu or in Settings → General.
- **Position from LitRes:** if you read or listened further on LitRes, the app jumps there by itself;
  the notification has an Undo button.
- A finished book is marked as read on LitRes too.

## Book graph

Menu → "Book graph" or Ctrl+G. The graph works like the one in Obsidian: books and tags are nodes,
and each book–tag link is an edge.

- Tags: LitRes genres and tags, your LitRes folders, series, authors, topics of your own books and
  articles. Turn tag kinds on in the panel on the left; it also has search and an All / LitRes /
  Mine filter.
- Hovering highlights links, clicking a tag selects its books, clicking a book opens it. Wheel or
  pinch to zoom, drag to pan and to move nodes.
- Book colour: grey — not started, accent — reading, green — read.
- LitRes genres and tags load in the background after a sync (once per book). Layout and loading
  progress are shown at the top and under the window title.

## Reading statistics

Menu → "Reading statistics". Minutes today and this week, day streak, finished books, a two-week
chart and the books you spent the most time on.

Reading on your phone or the LitRes website counts too: on sync, the progress gained is converted
into time (text — about 1300 characters per minute based on the book's length, audio — by duration)
and recorded for the day you read. That part of a bar is lighter on the chart. Change the reading
speed used for this estimate in Settings → Advanced.

## Settings

Menu → "Settings" or Ctrl+,. Changes apply immediately.

| Tab | What's there |
|---|---|
| **General** | interface language (system default, Русский, English — after restart); open the last book on startup; downloaded only; download all books; folders (downloaded LitRes books, your folders and sections); statistics |
| **Reading** | text appearance, read aloud, auto page turn, audiobook speed |
| **Integrations** | LitRes (sign in and out) and Singularity |
| **Backups** | see [Backups](#backups) |
| **Advanced** | how often to refresh the library from LitRes and "Refresh now"; reading speed for estimating phone reading; verbose log; data, settings and cache folders; reset settings |

"Reset settings" returns text appearance, reading, refresh and log settings to defaults; folders,
the LitRes sign-in and the library are kept.

## Backups

Settings → Backups.

- **What's in a backup:** settings, the library (folders, marks, paths to downloaded books), reading
  positions and bookmarks, statistics, Singularity settings. Books, covers and the LitRes sign-in
  are not included. The Singularity token is included only if "Include the Singularity token" is on.
- **When:** with the "Back up" button and automatically — daily or weekly (weekly by default). Old
  backups beyond the set number are deleted.
- **Where:** `Documents/Backups/litres-reader` by default; you can change the folder. If your
  Documents folder syncs to the cloud, the backups end up there too.
- **Restore:** from the list of recent backups or from a file (for example, from another computer).
  Before restoring, the current data is backed up separately, and the app restarts. The books and
  backup folders stay as they are on this computer.
- Backup files are accessible only to your user account.

## Singularity

Settings → Integrations → Singularity → "Set up…". Paste an API token from your
[SingularityApp account](https://me.singularity-app.com) ("API access", with access to tasks,
projects and habits) and choose what to sync:

- **"Reading" tasks** — started books become tasks in the "Книги" project; a finished book closes
  its task.
- **Progress in the task** — percent and current chapter in the task note.
- **"Want to read"** — unread books become tasks in a separate project; a started book moves to
  "Книги" as the same task.
- **Daily reading** — the "Чтение N минут" habit is checked automatically once you reach N minutes
  of reading or listening in a day.

Sync runs after the LitRes sync, when you mark a book as read and every couple of minutes while you
read. The app finds its own tasks by `externalId`, so there are no duplicates. Project and habit
names in Singularity are always in Russian, so switching the interface language doesn't create
duplicates. The token is stored only on this computer.

## LitRes and VPN (Linux)

LitRes doesn't open through a foreign VPN. The scripts in `vpn-bypass/` send LitRes traffic directly
over the regular connection and everything else through the VPN. If `vpn-killswitch` is installed,
they add an exception for LitRes addresses only.

```
sudo bash vpn-bypass/install.sh           # install
sudo bash vpn-bypass/install.sh --remove  # remove (and restore the original kill switch)
```

## Where data is stored

| What | Linux | Windows |
|---|---|---|
| Books, covers, library, progress | `~/.local/share/litres-reader/` | `%LOCALAPPDATA%\litres-reader\` |
| LitRes session | `~/.local/share/litres-reader/webengine/` | `%LOCALAPPDATA%\litres-reader\webengine\` |
| Settings, Singularity token | `~/.config/litres-reader/` | `%APPDATA%\litres-reader\` |
| Cache (service icons) | `~/.cache/litres-reader/` | `%LOCALAPPDATA%\litres-reader\cache\` |

You can change the folder for downloaded books in Settings → General → Folders. Data files are
created with owner-only access. Downloaded books and progress remain after uninstalling the app.

## Keyboard shortcuts

| Keys | Action |
|---|---|
| F5, Ctrl+R | refresh the library from LitRes |
| Ctrl+F | search |
| Ctrl+O | open a file |
| Ctrl+G | book graph |
| Ctrl+, | settings |
| Alt+← | back |
| F11 | full screen |
| ←/→, PageUp/PageDown, Space | turn pages in the reader |
| Esc | leave full screen or go back |
| Space, ←/→ | pause and seek in the player |

## Limitations

- LitRes has no public API. The app uses the same endpoints as the website; if LitRes changes them,
  the book list or downloads will stop working.
- DRM-protected books and books available only for online reading on the website won't open.
- The exact reading position is not written back to LitRes — only the "read" mark.
- There is no automatic hyphenation: the built-in Chromium ships without hyphenation dictionaries.
- PDFs are shown page by page as they are; the font size of a PDF can't be changed.
