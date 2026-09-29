#!/bin/bash
# Устанавливает обход VPN для ЛитРес (нужен sudo).
#   sudo bash ~/litres-reader/vpn-bypass/install.sh            — установить
#   sudo bash ~/litres-reader/vpn-bypass/install.sh --remove   — удалить
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Запустите через sudo: sudo bash $0" >&2
    exit 1
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
BIN=/usr/local/sbin/litres-vpn-bypass
HOOK=/etc/NetworkManager/dispatcher.d/90-litres-vpn-bypass
UNIT=/etc/systemd/system/litres-vpn-bypass

KS=/usr/local/bin/vpn-killswitch
KS_BACKUP=/usr/local/bin/vpn-killswitch.before-litres

if [[ "${1:-}" == "--remove" ]]; then
    systemctl disable --now litres-vpn-bypass.timer 2>/dev/null || true
    rm -f "$BIN" "$HOOK" "$UNIT.service" "$UNIT.timer" /etc/vpn-killswitch/bypass
    rm -rf /var/lib/litres-vpn-bypass
    sed -i '/# litres-vpn-bypass$/d' /etc/hosts
    systemctl daemon-reload
    ip -4 route flush proto 247 2>/dev/null || true
    if [[ -f "$KS_BACKUP" ]]; then
        mv -f "$KS_BACKUP" "$KS"
        # Пересоздаём таблицу исходной версией (без исключений) одной транзакцией
        if pgrep -x openvpn >/dev/null; then
            "$KS" on
        fi
        echo "Kill switch возвращён к исходной версии."
    fi
    echo "Обход VPN для ЛитРес удалён."
    exit 0
fi

install -m 0755 "$DIR/litres-vpn-bypass" "$BIN"

# Kill switch: добавляем список исключений (bypass), остальное без изменений
if [[ -f "$KS" ]]; then
    [[ -f "$KS_BACKUP" ]] || cp -a "$KS" "$KS_BACKUP"
    install -m 0755 "$DIR/vpn-killswitch" "$KS"
    command -v restorecon >/dev/null && restorecon -F "$KS" || true
fi

# NetworkManager вызывает этот хук при подключении/отключении VPN и смене сети
cat > "$HOOK" <<EOF
#!/bin/sh
case "\$2" in
    up|down|vpn-up|vpn-down|dhcp4-change|connectivity-change) exec $BIN ;;
esac
EOF
chmod 0755 "$HOOK"

# Раз в 5 минут обновляем адреса доменов ЛитРес
cat > "$UNIT.service" <<EOF
[Unit]
Description=Маршруты к ЛитРес мимо VPN
After=network-online.target

[Service]
Type=oneshot
ExecStart=$BIN
EOF
cat > "$UNIT.timer" <<EOF
[Unit]
Description=Обновление маршрутов к ЛитРес мимо VPN

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

command -v restorecon >/dev/null && restorecon -F "$BIN" "$HOOK" "$UNIT.service" "$UNIT.timer" || true
systemctl daemon-reload
systemctl enable --now litres-vpn-bypass.timer
"$BIN"   # маршруты и файл исключений /etc/vpn-killswitch/bypass

# Пересоздаём таблицу файрвола уже со списком исключений — одной транзакцией nft,
# без момента, когда трафик идёт мимо VPN. Службу не перезапускаем: при остановке
# она выключает kill switch, а новый скрипт она и так вызывает по пути.
if [[ -f "$KS" ]] && pgrep -x openvpn >/dev/null; then
    "$KS" on
fi

echo "Готово. Маршруты к ЛитРес:"
ip -4 route show proto 247
echo
echo "Проверка: $(ip -4 route get 193.26.19.133 | head -1)"
