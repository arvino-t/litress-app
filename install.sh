#!/usr/bin/env bash
# Установка Shelfwise на Linux (для текущего пользователя, без root —
# sudo нужен только для системных библиотек, если их нет).
#
#   bash install.sh              — установить или обновить
#   bash install.sh --uninstall  — удалить (книги и настройки остаются)
#
# Что делает:
#   - ставит системные зависимости (Python 3.10+, venv, библиотеки для Qt/Chromium);
#   - создаёт своё окружение Python в ~/.local/opt/shelfwise и ставит туда приложение с PySide6;
#   - команда shelfwise в ~/.local/bin (и прежняя litres-reader — ссылкой на неё);
#   - ярлык в меню приложений, значок, открытие файлов EPUB/FB2/MOBI;
#   - убирает установку прежней «Читалки ЛитРес» (её данные Shelfwise перенесёт сам при запуске).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
APP_ID=io.github.arvino_t.Shelfwise
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$HOME/.local/opt/shelfwise"
BIN="$HOME/.local/bin/shelfwise"
DESKTOP="$PREFIX/applications/$APP_ID.desktop"
ICON="$PREFIX/icons/hicolor/scalable/apps/$APP_ID.svg"
MIME="$PREFIX/mime/packages/$APP_ID.xml"
# прежняя «Читалка ЛитРес»
OLD_ID=ru.local.LitresReader
OLD_DIR="$HOME/.local/opt/litres-reader"
OLD_BIN="$HOME/.local/bin/litres-reader"

remove_old_install() {
    rm -f "$PREFIX/applications/$OLD_ID.desktop" "$PREFIX/icons/hicolor/scalable/apps/$OLD_ID.svg" \
          "$PREFIX/mime/packages/$OLD_ID.xml"
    if [[ -d "$OLD_DIR" ]]; then
        if pgrep -f "^$OLD_DIR/venv/" >/dev/null 2>&1; then
            echo "  прежняя версия сейчас открыта — её файлы в $OLD_DIR удалятся при следующей установке"
        else
            rm -rf "$OLD_DIR"
        fi
    fi
}

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
    echo "Запустите без sudo — приложение ставится для текущего пользователя." >&2
    exit 1
fi

refresh_caches() {
    update-desktop-database "$PREFIX/applications" 2>/dev/null || true
    update-mime-database "$PREFIX/mime" 2>/dev/null || true
    gtk-update-icon-cache -q "$PREFIX/icons/hicolor" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    step "Удаляю Shelfwise"
    rm -rf "$APP_DIR"
    rm -f "$BIN" "$OLD_BIN" "$DESKTOP" "$ICON" "$MIME"
    remove_old_install
    refresh_caches
    echo "Готово. Книги и настройки остались в ~/.local/share/shelfwise и ~/.config/shelfwise,"
    echo "данные своих библиотек — в их папках (.library). Удалите их вручную, если они больше не нужны."
    exit 0
fi

# ---------------------------------------------------------------- зависимости
step "Системные зависимости"
. /etc/os-release
if [[ "$ID" == fedora || "${ID_LIKE:-}" == *fedora* || "${ID_LIKE:-}" == *rhel* ]]; then
    PKGS=(python3 python3-pip xcb-util-cursor nss libxkbcommon-x11)
    missing=()
    for p in "${PKGS[@]}"; do rpm -q "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
        sudo dnf install -y "${missing[@]}"
    fi
elif [[ "$ID" == ubuntu || "$ID" == debian || "${ID_LIKE:-}" == *debian* || "${ID_LIKE:-}" == *ubuntu* ]]; then
    PKGS=(python3 python3-venv python3-pip libxcb-cursor0 libnss3 libxkbcommon-x11-0 libegl1)
    missing=()
    for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
    if ((${#missing[@]})); then
        sudo apt-get update
        sudo apt-get install -y "${missing[@]}"
    fi
elif [[ "$ID" == arch || "${ID_LIKE:-}" == *arch* ]]; then
    sudo pacman -S --needed --noconfirm python python-pip xcb-util-cursor nss libxkbcommon-x11
else
    echo "Неизвестный дистрибутив ($ID): нужен Python 3.10+ с модулем venv." >&2
fi

PY=$(command -v python3 || true)
if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Нужен Python 3.10 или новее." >&2
    exit 1
fi

# ---------------------------------------------------------------- приложение
step "Окружение Python и приложение (PySide6 весит около 600 МБ — скачивание займёт время)"
if [[ ! -x "$APP_DIR/venv/bin/python" ]]; then
    "$PY" -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/python" -m pip install --upgrade --quiet pip
"$APP_DIR/venv/bin/python" -m pip install --upgrade --quiet "$SRC"
# Свежий код ставим всегда, даже если номер версии не менялся
"$APP_DIR/venv/bin/python" -m pip install --quiet --force-reinstall --no-deps "$SRC"
echo "  установлено: $("$APP_DIR/venv/bin/python" -c 'import shelfwise; print(shelfwise.__version__)')"

mkdir -p "$(dirname "$BIN")"
rm -f "$BIN"
cat > "$BIN" <<EOF
#!/bin/sh
exec "$APP_DIR/venv/bin/shelfwise" "\$@"
EOF
chmod +x "$BIN"
rm -f "$OLD_BIN" && ln -s "$BIN" "$OLD_BIN"      # прежняя команда — ссылка на новую
remove_old_install

# ---------------------------------------------------------------- интеграция с рабочим столом
step "Ярлык, значок и типы файлов"
mkdir -p "$(dirname "$DESKTOP")" "$(dirname "$ICON")" "$(dirname "$MIME")"
cp "$SRC/shelfwise/data/$APP_ID.svg" "$ICON"

cat > "$MIME" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-fictionbook+xml">
    <comment>Книга FictionBook</comment>
    <glob pattern="*.fb2"/>
  </mime-type>
  <mime-type type="application/x-zip-compressed-fb2">
    <comment>Книга FictionBook (сжатая)</comment>
    <glob pattern="*.fb2.zip"/>
    <glob pattern="*.fbz"/>
  </mime-type>
</mime-info>
EOF

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Shelfwise
GenericName=Своя библиотека книг
GenericName[en]=Personal library
Comment=Своя библиотека книг и статей: читать, организовывать, обслуживать; ЛитРес — подключаемая библиотека
Comment[en]=Build, read and organize your own library of books and articles; LitRes as a pluggable library
Exec=$BIN %F
Icon=$APP_ID
Terminal=false
Categories=Office;Viewer;GTK;Qt;
Keywords=книги;библиотека;статьи;литрес;litres;epub;fb2;pdf;аудиокниги;читалка;library;books;
MimeType=application/epub+zip;application/x-fictionbook+xml;application/x-zip-compressed-fb2;application/x-mobipocket-ebook;
StartupWMClass=shelfwise
EOF
refresh_caches

step "Готово"
echo "Shelfwise есть в меню приложений; из терминала — shelfwise."
echo "Удалить: bash $SRC/install.sh --uninstall"
