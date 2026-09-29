#!/usr/bin/env bash
# Ставит зависимости (Fedora или Ubuntu) и добавляет «Читалку ЛитРес» в меню приложений.
# Запуск: bash ~/litres-reader/install.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ID=ru.local.LitresReader

. /etc/os-release
if [[ "$ID" == fedora || "${ID_LIKE:-}" == *fedora* ]]; then
    sudo dnf install -y python3-gobject gtk4 libadwaita webkitgtk6.0 hyphen-ru
elif [[ "$ID" == ubuntu || "${ID_LIKE:-}" == *ubuntu* || "$ID" == debian ]]; then
    sudo apt-get update
    sudo apt-get install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0 hyphen-ru
else
    echo "Неизвестная система ($ID): поставьте вручную PyGObject, GTK 4, libadwaita, WebKitGTK 6.0" >&2
fi

mkdir -p ~/.local/bin ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
ln -sf "$DIR/litres_reader.py" ~/.local/bin/litres-reader
chmod +x "$DIR/litres_reader.py"
cp "$DIR/data/$APP_ID.svg" ~/.local/share/icons/hicolor/scalable/apps/

cat > ~/.local/share/applications/$APP_ID.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Читалка ЛитРес
GenericName=Чтение электронных книг
Comment=Книги, купленные на ЛитРес, и файлы EPUB/FB2
Exec=python3 $DIR/litres_reader.py %F
Icon=$APP_ID
Terminal=false
Categories=Office;Viewer;Literature;GTK;
Keywords=книги;литрес;litres;epub;fb2;читалка;
MimeType=application/epub+zip;application/x-fictionbook+xml;application/x-zip-compressed-fb2;application/x-mobipocket-ebook;
StartupWMClass=$APP_ID
DBusActivatable=false
EOF

update-desktop-database ~/.local/share/applications 2>/dev/null || true
gtk-update-icon-cache -q ~/.local/share/icons/hicolor 2>/dev/null || true
echo "Готово: «Читалка ЛитРес» появилась в меню приложений."
