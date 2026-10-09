"""Английский перевод интерфейса: русский текст → английский (см. i18n.py)."""

EN_PLURAL = {
    "книга": ("book", "books"),
    "аудиокнига": ("audiobook", "audiobooks"),
    "минута": ("minute", "minutes"),
    "день": ("day", "days"),
}

EN = {
    # --- приложение и библиотека
    "Библиотека": "Library",
    "Вход в ЛитРес не выполнен": "Not signed in to LitRes",
    "Обновить список книг с ЛитРес (F5)": "Refresh books from LitRes (F5)",
    "Вернуться к плееру": "Back to the player",
    "Меню": "Menu",
    "Открыть файл…": "Open file…",
    "Скачать все книги…": "Download all books…",
    "Только скачанные": "Downloaded only",
    "Открывать последнюю текстовую книгу при запуске": "Open the last text book on startup",
    "Войти в ЛитРес": "Sign in to LitRes",
    "Настройки… (Ctrl+,)": "Settings… (Ctrl+,)",
    "Статистика чтения": "Reading statistics",
    "Граф книг (Ctrl+G)": "Book graph (Ctrl+G)",
    "О приложении": "About",
    "Поиск (Ctrl+F)": "Search (Ctrl+F)",
    "Название или автор": "Title or author",
    "Папка на ЛитРес": "LitRes folder",
    "Сортировка": "Sort by",
    "Подкаталог": "Subfolder",
    "Все подкаталоги": "All subfolders",
    "Папка на диске": "Folder on disk",
    "Источник": "Source",
    "Вход в ЛитРес": "Sign in to LitRes",
    "Пароль вводится на сайте ЛитРес": "You enter your password on the LitRes website",
    "Назад": "Back",
    "Обновить страницу": "Reload page",
    "Выйти из ЛитРес?": "Sign out of LitRes?",
    "<b>Выйти из ЛитРес?</b>": "<b>Sign out of LitRes?</b>",
    "Скачанные книги и закладки останутся на этом компьютере.":
        "Downloaded books and bookmarks stay on this computer.",
    "Отмена": "Cancel",
    "Выйти": "Sign out",
    "Скачать все книги?": "Download all books?",
    "<b>Скачать все книги на компьютер?</b>": "<b>Download all books to this computer?</b>",
    "Остановить скачивание книг": "Stop downloading books",
    "Папки": "Folders",
    "Закрыть": "Close",
    "Изменения сразу отправляются на ЛитРес": "Changes are sent to LitRes right away",
    "Новая папка — введите название и нажмите Enter": "New folder — type a name and press Enter",
    "Папка для книг (сейчас: {0})": "Books folder (current: {0})",
    "Папка со своими книгами и статьями": "Folder with your own books and articles",
    "Открыть книгу": "Open book",
    "Электронные книги ({0})": "E-books ({0})",
    "Книги, прогресс и ежедневное чтение — в планировщике SingularityApp.<br>Токен создаётся в "
    "<a href='https://me.singularity-app.com'>личном кабинете</a> → «Доступ к API» "
    "(нужен доступ к задачам, проектам и привычкам).":
        "Books, progress and daily reading in the SingularityApp planner.<br>Create a token in your "
        "<a href='https://me.singularity-app.com'>account</a> → “API access” "
        "(needs access to tasks, projects and habits).",
    "API-токен Singularity": "Singularity API token",
    "Отключить": "Disconnect",
    "Проверить и синхронизировать": "Check and sync",
    "<h3>{0}</h3><p>Версия {1}</p>": "<h3>{0}</h3><p>Version {1}</p>",
    "Книг пока нет": "No books yet",
    "Открыть файл с компьютера": "Open a file from this computer",
    "Скачиваю книги: {0} из {1}": "Downloading books: {0} of {1}",
    "Книга дочитана — отмечена прочитанной": "Book finished — marked as read",
    "{0}. Следующая в серии: «{1}»": "{0}. Next in the series: “{1}”",
    "Сначала войдите в ЛитРес": "Sign in to LitRes first",
    "Скачивание останавливается…": "Stopping downloads…",
    "Все книги ЛитРес уже скачаны": "All LitRes books are already downloaded",
    ".\nПапка: {0}\nКниги скачиваются по одной; остановить можно в меню.":
        ".\nFolder: {0}\nBooks are downloaded one at a time; you can stop from the menu.",
    "Книги ({0})": "Books ({0})",
    "Всё, с аудио ({0})": "Everything, with audio ({0})",
    "Скачано {0} из {1}": "Downloaded {0} of {1}",
    ", не удалось: {0} (список — в журнале)": ", failed: {0} (list in the log)",
    "вход в ЛитРес не выполнен": "not signed in to LitRes",
    "Снять отметку «Прочитано»": "Unmark as read",
    "Отметить прочитанной": "Mark as read",
    "Папки…": "Folders…",
    "Следующая в серии: {0}": "Next in the series: {0}",
    "Показать файл в папке": "Show file in folder",
    "Папок пока нет — создайте первую ниже": "No folders yet — create the first one below",
    "Продолжаю с места на ЛитРес — {0}%": "Continuing from the LitRes position — {0}%",
    "Аудиокнига прослушана — отмечена прочитанной": "Audiobook finished — marked as read",
    "Своих книг и статей: {0}": "Your own books and articles: {0}",
    "Статьи": "Articles",
    "Другие книги": "Other books",
    "Тренинги и презентации": "Trainings and presentations",
    "Раздел": "Section",
    "Название раздела для папки\n{0}": "Section name for the folder\n{0}",
    "Эта папка уже добавлена": "This folder is already added",
    "Задачи «Читаю»": "“Reading” tasks",
    "Начатые книги — задачи в проекте «Книги», дочитанные закрываются":
        "Started books become tasks in the “Книги” project; finished ones are closed",
    "Прогресс в задаче": "Progress in the task",
    "Процент и текущая глава в заметке задачи": "Percent and current chapter in the task note",
    "«Хочу прочитать»": "“Want to read”",
    "Непрочитанные книги — задачи в отдельном проекте": "Unread books become tasks in a separate project",
    "Ежедневное чтение": "Daily reading",
    "Привычка отмечается сама, когда за день набралось N минут":
        "The habit is checked automatically once you reach N minutes a day",
    "Цель чтения в день, минут": "Daily reading goal, minutes",
    "Сегодня прочитано и прослушано: {0} мин": "Read and listened today: {0} min",
    "Проверяю токен…": "Checking the token…",
    "Синхронизация с Singularity отключена": "Singularity sync is turned off",
    "Ошибка воспроизведения: {0}": "Playback error: {0}",
    "Все папки": "All folders",
    "Без папки": "No folder",
    "Вы вошли в ЛитРес": "Signed in to LitRes",
    "Выйти из ЛитРес": "Sign out of LitRes",
    "Не удалось изменить папку на ЛитРес — повторю при синхронизации":
        "Couldn't change the folder on LitRes — will retry on the next sync",
    ". Не получено: ": ". Not received: ",
    "«Читаю сейчас»": "“Reading now”",
    "папки": "folders",
    "Книг в аккаунте: {0}": "Books in the account: {0}",
    "Не удалось обновить отметку на ЛитРес — повторю при синхронизации":
        "Couldn't update the mark on LitRes — will retry on the next sync",
    "Открыть": "Open",
    "Не удалось получить файлы книги (код {0})": "Couldn't get the book files (code {0})",
    "У этой книги нет формата для чтения (возможно, только онлайн-чтение)":
        "This book has no downloadable format (it may be online-only)",
    "Книга защищена DRM — она может не открыться": "The book is DRM-protected — it may not open",
    "Не скачано: {0} {1}": "Not downloaded: {0} {1}",
    " — остановлено": " — stopped",
    "Слушать": "Listen",
    "Читать": "Read",
    "Скачать заново": "Download again",
    "Скачать": "Download",
    "Открыть на сайте ЛитРес": "Open on the LitRes website",
    "Удалить с устройства": "Remove from this device",
    "Чтобы создать папку, войдите в ЛитРес": "Sign in to LitRes to create a folder",
    "В аудиокниге не найдено звуковых файлов": "No audio files found in the audiobook",
    "Вернуть": "Undo",
    "Не удалось открыть файл: {0}": "Couldn't open the file: {0}",
    "Книги теперь в {0}. Перенесено: {1}, не удалось: {2} — ": "Books are now in {0}. Moved: {1}, failed: {2} — ",
    "Книги теперь в {0}": "Books are now in {0}",
    "Вставьте токен": "Paste the token",
    "Данные восстановлены из резервной копии": "Data restored from the backup",
    "ЛитРес: {0}": "LitRes: {0}",
    "ЛитРес: вход выполнен": "LitRes: signed in",
    "Сессия ЛитРес истекла — войдите снова": "LitRes session expired — sign in again",
    "Не удалось получить список книг (код {0})": "Couldn't get the book list (code {0})",
    "Для этой аудиокниги доступны только отдельные главы — пока не поддерживается":
        "Only separate chapters are available for this audiobook — not supported yet",
    "ЛитРес не отдал файл книги ({0})": "LitRes didn't return the book file ({0})",
    " и {0} {1} (аудиокниги большие — сотни мегабайт каждая)":
        " and {0} {1} (audiobooks are large — hundreds of megabytes each)",
    "Не удалось создать папку на ЛитРес": "Couldn't create the folder on LitRes",
    " — перенесено файлов: {0}": " — files moved: {0}",
    "Вы вышли из ЛитРес": "Signed out of LitRes",
    "папка «{0}»": "folder “{0}”",
    "; синхронизирую…": "; syncing…",
    "Не удалось распаковать аудиокнигу: {0}": "Couldn't unpack the audiobook: {0}",
    "неверный ответ": "invalid response",

    # --- резервные копии (backup.py)
    "это не резервная копия Muninhall": "this is not a Muninhall backup",
    "в копии нет данных": "the backup has no data",
    "это не резервная копия Muninhall ({0})": "this is not a Muninhall backup ({0})",
    "{0}: слишком большой файл": "{0}: file is too large",
    "{0}: повреждён": "{0}: damaged",

    # --- фильтры и сортировка (core.py)
    "Все": "All",
    "Читаю": "Reading",
    "Не читал": "Unread",
    "Прочитано": "Read",
    "Недавние": "Recent",
    "Как на ЛитРес": "As on LitRes",
    "По названию": "By title",
    "По автору": "By author",
    "По сериям": "By series",
    "По прогрессу": "By progress",
    "По дате покупки": "By purchase date",
    "Аудиокниги": "Audiobooks",
    "Глава {0}": "Chapter {0}",
    "{0}: в новой папке уже есть файл с таким именем": "{0}: a file with this name already exists in the new folder",

    # --- граф (graph.py, graph.js, graph.html)
    "Жанры": "Genres",
    "Мои папки на ЛитРес": "My LitRes folders",
    "Темы своих книг и статей": "Topics of my books and articles",
    "Серии": "Series",
    "Теги ЛитРес": "LitRes tags",
    "Авторы": "Authors",
    "Граф книг": "Book graph",
    "Загружаю жанры и теги с ЛитРес: {0} из {1}": "Loading genres and tags from LitRes: {0} of {1}",
    "строю граф…": "building the graph…",
    "жанры с ЛитРес: {0} из {1}": "genres from LitRes: {0} of {1}",
    "{0} книг · {1} тегов": "{0} books · {1} tags",
    "прочитано {0}%": "{0}% read",
    "{0} · книг: {1}": "{0} · books: {1}",
    "Раскладка графа — {0}%": "Graph layout — {0}%",
    "Строю граф…": "Building the graph…",
    "Найти книгу или тег": "Find a book or tag",
    "Книги": "Books",
    "Мои": "Mine",
    "Связи": "Links",
    "Тег — от": "Tag — at least",
    "книг": "books",
    "Книги без связей": "Books without links",
    "Показать всё": "Show all",
    "Нет связей для выбранных фильтров": "No links for the selected filters",

    # --- ЛитРес (litres.py)
    "Папка {0}": "Folder {0}",
    "прервано": "interrupted",

    # --- плеер (player.py)
    "{0}% книги": "{0}% of the book",
    "Главы": "Chapters",
    "Таймер сна": "Sleep timer",
    "Предыдущая глава": "Previous chapter",
    "Назад на 15 секунд": "Back 15 seconds",
    "Слушать / пауза (пробел)": "Play / pause (Space)",
    "Вперёд на 30 секунд": "Forward 30 seconds",
    "Следующая глава": "Next chapter",
    "Скорость": "Speed",
    "Остановлю через {0} мин": "Stopping in {0} min",
    "Таймер сна: воспроизведение остановлено": "Sleep timer: playback stopped",
    "Аудиокнига": "Audiobook",
    "Таймер сна выключен": "Sleep timer off",
    "Остановлю в конце главы": "Stopping at the end of the chapter",
    "Выключить таймер": "Turn off the timer",
    "В конце главы": "At the end of the chapter",
    "Через {0} мин": "In {0} min",

    # --- читалка (reader.py, reader.js)
    "Во весь экран (F11)": "Full screen (F11)",
    "Вид текста": "Text appearance",
    "Оглавление": "Contents",
    "Автолистание": "Auto page turn",
    "Читать вслух": "Read aloud",
    "Меньше": "Smaller",
    "Больше": "Larger",
    "Размер шрифта": "Font size",
    "Шрифт": "Font",
    "Межстрочный интервал": "Line spacing",
    "Поля, %": "Margins, %",
    "Ширина строки": "Line width",
    "Скорость чтения вслух": "Read-aloud speed",
    "Автолистание, секунд": "Auto page turn, seconds",
    "Тема": "Theme",
    "Авто": "Auto",
    "Светлая": "Light",
    "Сепия": "Sepia",
    "Тёмная": "Dark",
    "Чёрная": "Black",
    "Как в книге": "As in the book",
    "С засечками": "Serif",
    "Без засечек": "Sans serif",
    "Две страницы в горизонтальном положении": "Two pages in landscape",
    "Выравнивать по ширине": "Justify text",
    "Переносы слов": "Hyphenation",
    "Автолистание: страница каждые {0} с": "Auto page turn: a page every {0} s",
    "Чтение вслух недоступно: {0}": "Read aloud is unavailable: {0}",
    "Размер шрифта: {0}": "Font size: {0}",
    "Чтение вслух: книга дочитана до конца": "Read aloud: reached the end of the book",
    "Не удалось открыть книгу: {0}": "Couldn't open the book: {0}",
    "Открываю книгу…": "Opening the book…",
    "Не удалось прочитать файл ({0})": "Couldn't read the file ({0})",

    # --- настройки (settings.py)
    "Как в системе": "System default",
    "Общие": "General",
    "Чтение": "Reading",
    "Интеграции": "Integrations",
    "Резервные копии": "Backups",
    "Дополнительно": "Advanced",
    "Выключено": "Off",
    "Раз в день": "Daily",
    "Раз в неделю": "Weekly",
    "сегодня": "today",
    "Настройки": "Settings",
    "Язык": "Language",
    "Язык интерфейса": "Interface language",
    "Применяется после перезапуска": "Applies after restart",
    "Запуск и библиотека": "Startup and library",
    "Самую свежую из начатых и скачанных — с учётом чтения на телефоне":
        "The most recent of the started and downloaded books, including reading on your phone",
    "Показывать только скачанные книги": "Show downloaded books only",
    "Скачать все книги": "Download all books",
    "Скачать…": "Download…",
    "Все купленные книги ЛитРес — в папку для скачанных книг": "All purchased LitRes books, to the downloads folder",
    "Переименовать…": "Rename…",
    "Изменить…": "Change…",
    "Статистика": "Statistics",
    "Минуты по дням, серия дней подряд, дочитанные книги": "Minutes per day, day streak, finished books",
    "Поля": "Margins",
    "Чтение вслух и автолистание": "Read aloud and auto page turn",
    "Автолистание — страница каждые": "Auto page turn — a page every",
    "Скорость воспроизведения": "Playback speed",
    "Без изменения высоты голоса": "Without changing the voice pitch",
    "Сервисы": "Services",
    "Сторонние сервисы, с которыми работает приложение.": "Third-party services the app works with.",
    "ЛитРес": "LitRes",
    "Настроить…": "Set up…",
    "Задачи «Читаю», прогресс в заметках, привычка ежедневного чтения":
        "“Reading” tasks, progress in notes, daily reading habit",
    "Создать копию сейчас": "Back up now",
    "Создать": "Back up",
    "Создавать автоматически": "Back up automatically",
    "Хранить копий": "Backups to keep",
    "Папка для копий": "Backup folder",
    "Сохранять токен Singularity": "Include the Singularity token",
    "Без него после восстановления на другом компьютере Singularity придётся подключить заново. "
    "Токен даёт доступ к вашим задачам — храните такие копии бережно":
        "Without it you'll need to reconnect Singularity after restoring on another computer. "
        "The token gives access to your tasks — keep such backups safe",
    "Восстановление": "Restore",
    "Перед восстановлением текущие данные тоже сохраняются в копию. Папки книг и копий остаются как "
    "на этом компьютере. Приложение перезапустится.":
        "Before restoring, the current data is also backed up. The books and backup folders stay as they are "
        "on this computer. The app will restart.",
    "Синхронизация с ЛитРес": "LitRes sync",
    "Обновлять библиотеку с ЛитРес каждые": "Refresh the library from LitRes every",
    " мин": " min",
    "Пока окно открыто; 0 — только при запуске и по F5": "While the window is open; 0 — only on startup and with F5",
    "Обновить сейчас": "Refresh now",
    "Обновить": "Refresh",
    "То же, что F5": "Same as F5",
    "Скорость чтения для оценки чтения на телефоне": "Reading speed for estimating phone reading",
    " зн/мин": " chars/min",
    "По ней прирост процента на ЛитРес переводится в минуты (аудио — по длительности)":
        "Used to convert progress gained on LitRes into minutes (audio uses its duration)",
    "Журнал": "Log",
    "Подробный журнал": "Verbose log",
    "Запросы к ЛитРес, скачивания, сообщения страниц — в поток ошибок (терминал, журнал системы). "
    "Инструменты разработчика в читалке — по правой кнопке мыши.":
        "LitRes requests, downloads and page messages go to stderr (terminal, system journal). "
        "Developer tools in the reader open with a right click.",
    "Данные приложения": "App data",
    "Сбросить настройки": "Reset settings",
    "Сбросить…": "Reset…",
    "Вид текста, чтение, обновление, журнал. Папки, вход и библиотека не меняются":
        "Text appearance, reading, refresh, log. Folders, sign-in and library are kept",
    "Обновить список": "Rescan",
    "Восстановить из файла": "Restore from file",
    "Выбрать…": "Choose…",
    "Например, копия с другого компьютера": "For example, a backup from another computer",
    "Папка для резервных копий": "Backup folder",
    "Резервная копия": "Backup",
    "Резервные копии (*.zip)": "Backups (*.zip)",
    "Восстановить из копии?": "Restore from backup?",
    "<b>Восстановить данные из копии ({0})?</b>": "<b>Restore data from the backup ({0})?</b>",
    "Копия версии {0}. Библиотека, место чтения, статистика и настройки заменятся данными из копии; "
    "текущие сначала сохранятся в отдельную копию. Приложение перезапустится.":
        "Backup from version {0}. The library, reading positions, statistics and settings will be replaced "
        "with the backup; the current data is backed up first. The app will restart.",
    "Восстановить и перезапустить": "Restore and restart",
    "Сбросить настройки?": "Reset settings?",
    "<b>Сбросить настройки?</b>": "<b>Reset settings?</b>",
    "Вид текста, чтение вслух, аудио, обновление с ЛитРес и журнал вернутся к исходным. "
    "Папки, вход в ЛитРес и библиотека не изменятся.":
        "Text appearance, read aloud, audio, LitRes refresh and log return to defaults. "
        "Folders, the LitRes sign-in and the library won't change.",
    "Сбросить": "Reset",
    "Настройки сброшены": "Settings reset",
    "Данные": "Data",
    "Библиотека, прогресс, статистика, обложки": "Library, progress, statistics, covers",
    "Кэш": "Cache",
    "Можно удалить — приложение создаст заново": "Safe to delete — the app recreates it",
    "Открыть папку": "Open folder",
    "Убрать": "Remove",
    "Последняя: ": "Last: ",
    "Копий ещё не было": "No backups yet",
    "Восстановить": "Restore",
    "{0:.0f} КБ": "{0:.0f} KB",
    " · перед восстановлением": " · before restore",
    "И ещё {0} — в папке для копий": "{0} more in the backup folder",
    "Копия создана: {0}": "Backup created: {0}",
    "Не удалось создать копию — подробности в журнале": "Couldn't create a backup — see the log",
    "Восстановление отменено": "Restore cancelled",
    "Не удалось сохранить текущие данные в копию — подробности в журнале.":
        "Couldn't back up the current data — see the log.",
    "Войти": "Sign in",
    "Вход выполнен: {0}": "Signed in: {0}",
    "{0:g} с": "{0:g} s",
    "В папке пока нет копий": "No backups in the folder yet",
    "Не удалось восстановить": "Couldn't restore",
    "Вход выполнен": "Signed in",
    "Вход не выполнен": "Not signed in",
    "обычная": "normal",

    # --- Singularity (singularity.py)
    "Токен работает": "The token works",
    "Синхронизировано с Singularity {0:%H:%M}": "Synced with Singularity at {0:%H:%M}",
    "не удалось создать проект «Книги» в Singularity": "couldn't create the “Книги” project in Singularity",
    "не удалось создать привычку в Singularity": "couldn't create the habit in Singularity",
    "не удалось получить привычки ({0})": "couldn't get habits ({0})",
    "Токен не подходит — создайте новый с доступом к задачам, проектам и привычкам":
        "The token doesn't work — create a new one with access to tasks, projects and habits",
    "не удалось получить задачи Singularity ({0})": "couldn't get Singularity tasks ({0})",
    "не записано задач: {0}": "tasks not saved: {0}",
    "не удалось отметить привычку ({0})": "couldn't check the habit ({0})",
    "Сервер Singularity недоступен ({0}). Если включён VPN — нужен обход (см. vpn-bypass).":
        "The Singularity server is unreachable ({0}). If a VPN is on, it needs a bypass (see vpn-bypass).",
    "Ошибка Singularity: код {0}": "Singularity error: code {0}",
    "не удалось создать проект «Хочу прочитать» в Singularity":
        "couldn't create the “Хочу прочитать” project in Singularity",
    "нет связи": "no connection",

    # --- статистика (stats.py)
    "\nиз них на телефоне ~{0}": "\nof them on the phone ~{0}",
    "{0} сегодня{1}": "{0} today{1}",
    "{0} за неделю{1}": "{0} this week{1}",
    "{0} подряд": "{0} in a row",
    "дочитано в этом месяце · всего {0}": "finished this month · {0} total",
    "Последние две недели, минут в день": "Last two weeks, minutes per day",
    "Светлая часть столбика — чтение на телефоне или сайте ЛитРес. Оценка по приросту процента: "
    "текст — ~1300 знаков в минуту, аудио — по длительности.":
        "The lighter part of a bar is reading on the phone or the LitRes website. Estimated from progress "
        "gained: text at ~1300 characters per minute, audio by duration.",
    "Больше всего времени": "Most time spent",
    "Пока пусто — статистика копится, пока вы читаете и слушаете.":
        "Nothing yet — statistics build up as you read and listen.",
    "аудио": "audio",
    "{0} ч {1} мин": "{0} h {1} min",
    "{0} мин": "{0} min",

    # --- карточки и панели (widgets.py)
    "Не скачана — нажмите, чтобы скачать": "Not downloaded — click to download",
    "Продолжить чтение": "Continue reading",
    "Свернуть": "Minimize",
    "Развернуть": "Maximize",
    "Новая": "New",
    "Прослушано": "Listened",

    # --- библиотеки
    "Библиотеки": "Libraries",
    "Библиотека": "Library",
    "Все библиотеки": "All libraries",
    "Библиотек: {0} · книг: {1}": "Libraries: {0} · books: {1}",
    "Добавить библиотеку…": "Add library…",
    "Добавить папку с книгами…": "Add a folder with books…",
    "Добавьте папку со своими книгами, подключите ЛитРес\nили откройте файл EPUB/FB2.":
        "Add a folder with your books, connect LitRes\nor open an EPUB/FB2 file.",
    "Книг во всех библиотеках": "Books in all libraries",
    "Книги: {0}": "Books: {0}",
    "книг: {0}": "books: {0}",
    "ЛитРес — купленные книги": "LitRes — purchased books",
    "Обновить список книг (F5)": "Refresh the book list (F5)",
    "Отключить ЛитРес?": "Disconnect LitRes?",
    "<b>Отключить библиотеку ЛитРес?</b>": "<b>Disconnect the LitRes library?</b>",
    "Книги ЛитРес пропадут из программы. Скачанные файлы, отметки и вход сохранятся — "
    "библиотеку можно подключить снова.":
        "LitRes books will disappear from the app. Downloaded files, marks and the sign-in are kept — "
        "you can connect the library again.",
    "Папка для книг…": "Books folder…",
    "Своя библиотека — папка на диске: её подпапки видны в фильтре «Подкаталог», данные (отметки, "
    "место чтения) хранятся в ней же, в скрытой папке .library. Файлы открываются на месте, "
    "приложение их не копирует и не удаляет. ЛитРес — подключаемая библиотека купленных книг.":
        "Your own library is a folder on disk: its subfolders appear in the Subfolder filter, and its data "
        "(marks, reading positions) is stored inside it, in the hidden .library folder. Files open in place; "
        "the app doesn't copy or delete them. LitRes is a pluggable library of purchased books.",
    "Своя библиотека — папка на диске…": "Your own library — a folder on disk…",
    "Убрать из программы — файлы и данные в папке останутся": "Remove from the app — files and data in the folder stay",

    # --- резервные копии по библиотекам
    "Копия «Все библиотеки» — настройки, статистика, Singularity и данные всех библиотек; копия одной "
    "библиотеки — её отметки, место чтения и граф. Книги и обложки в копию не входят, вход в ЛитРес — "
    "тоже. Папку с копиями удобно держать в облаке.":
        "An \"All libraries\" backup holds settings, statistics, Singularity and the data of every library; "
        "a single-library backup holds its marks, reading positions and graph. Books, covers and the LitRes "
        "sign-in are not included. Keeping the backup folder in the cloud is handy.",
    "К ней относятся «Создать» и список копий ниже": "\"Back up\" and the list of backups below apply to it",
    "Копию всех библиотек — при запуске и пока приложение открыто":
        "An all-libraries backup — on startup and while the app is open",
    "У каждой библиотеки; более старые удаляются": "Per library; older ones are deleted",
    "Это копия библиотеки, которой нет в программе. Добавьте библиотеку и повторите.":
        "This is a backup of a library that isn't in the app. Add the library and try again.",
    "Отметки, место чтения и граф библиотеки «{0}» заменятся данными из копии; текущие сначала "
    "сохранятся в отдельную копию. Приложение перезапустится.":
        "Marks, reading positions and the graph of the \"{0}\" library will be replaced with the backup; "
        "the current data is backed up first. The app will restart.",

    # --- о приложении
    "Своя библиотека книг и статей: создавайте, читайте, организуйте и обслуживайте её. Библиотеки — "
    "папки на диске; у каждой свой граф и свои резервные копии, а все вместе они просматриваются как "
    "одна большая.<br><br>ЛитРес — подключаемая библиотека купленных книг и аудиокниг; вход выполняется "
    "на сайте ЛитРес, приложение не хранит пароль.":
        "Your own library of books and articles: build it, read it, organize it and look after it. Libraries "
        "are folders on disk; each has its own graph and backups, and together they can be browsed as one "
        "big library.<br><br>LitRes is a pluggable library of purchased books and audiobooks; you sign in on "
        "the LitRes website, and the app doesn't store your password.",
    "Лицензия MIT. Движок чтения — foliate-js (MIT), PDF — pdf.js (Apache 2.0), граф — d3-force (ISC), "
    "значки — Adwaita.":
        "MIT License. Reading engine: foliate-js (MIT), PDF: pdf.js (Apache 2.0), graph: d3-force (ISC), "
        "icons: Adwaita.",
    "Документация и исходный код: {0}": "Documentation and source code: {0}",
    "Открыть на GitHub": "Open on GitHub",
    "Подробнее…": "More…",
    "версия {0} · своя библиотека книг и статей; ЛитРес — подключаемая библиотека":
        "version {0} · your own library of books and articles; LitRes is a pluggable library",
    "Документация и исходный код": "Documentation and source code",
    "Закройте прежнюю версию приложения («Читалка ЛитРес» или Shelfwise) и запустите Muninhall снова: "
    "её данные перенесутся.":
        "Close the previous version of the app (\"Читалка ЛитРес\" or Shelfwise) and start Muninhall again: "
        "its data will be moved over.",

    # --- внешний вид и горячие клавиши
    "Внешний вид": "Appearance",
    "Оформление": "Style",
    "Тема интерфейса": "Interface theme",
    "Светлая или тёмная — независимо от системы": "Light or dark — regardless of the system",
    "Цвет акцента": "Accent color",
    "Системный": "System",
    "Синий": "Blue",
    "Бирюзовый": "Teal",
    "Зелёный": "Green",
    "Жёлтый": "Yellow",
    "Оранжевый": "Orange",
    "Красный": "Red",
    "Розовый": "Pink",
    "Фиолетовый": "Purple",
    "Сланцевый": "Slate",
    "Значок приложения": "App icon",
    "Значок окна и ярлыка в меню приложений.": "The icon of the window and the app menu entry.",
    "Значок": "Icon",
    "Ворон в чертоге": "Raven in the hall",
    "Ворон на луне": "Raven and the moon",
    "Полёт на закате": "Flight at sunset",
    "Хугин и Мунин": "Huginn and Muninn",
    "Рунный камень": "Rune stone",
    "Чертог": "The hall",
    "Перо ворона": "Raven quill",
    "Глаз ворона": "Raven's eye",
    "Крылья-«М»": "Wings \"M\"",
    "Горячие клавиши": "Keyboard shortcuts",
    "Щёлкните поле и нажмите новое сочетание; Backspace — убрать.":
        "Click a field and press a new shortcut; Backspace removes it.",
    "Обновить библиотеку": "Refresh the library",
    "Поиск": "Search",
    "Открыть файл": "Open file",
    "Во весь экран": "Full screen",
    "Также: {0}": "Also: {0}",
    "Совпадает с: {0}": "Same as: {0}",
    "По умолчанию: {0}": "Default: {0}",
    "Сбросить клавиши": "Reset shortcuts",
    "Все сочетания по умолчанию": "All shortcuts to defaults",
    "Нажмите сочетание": "Press a shortcut",
}
