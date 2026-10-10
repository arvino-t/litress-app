#!/usr/bin/env bash
# Сценарии на установленной сборке с КОПИЕЙ ваших данных во временном профиле:
#   bash install.sh && bash tools/flow_check.sh
# Настоящие настройки, данные и папки библиотек не меняются.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
py="${MUNINHALL_PY:-$HOME/.local/opt/muninhall/venv/bin/python}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/muninhall-flow.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp"/{home,data,config,cache,stores}
cp -a "$HOME/.local/share/muninhall" "$tmp/data/" 2>/dev/null || true
cp -a "$HOME/.config/muninhall" "$tmp/config/" 2>/dev/null || true
cp -a "$HOME/.cache/muninhall" "$tmp/cache/" 2>/dev/null || true
cfg="$tmp/config/muninhall/settings.json"
if [ -f "$cfg" ]; then
    python3 - "$cfg" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); d.update(openLastBook=False, libraryStatus="all"); json.dump(d, open(p, "w"))
PY
fi
cd "$tmp"
HOME="$tmp/home" XDG_DATA_HOME="$tmp/data" XDG_CONFIG_HOME="$tmp/config" XDG_CACHE_HOME="$tmp/cache" \
    QT_QPA_PLATFORM=offscreen timeout 120 "$py" -I "$here/flow_check.py" "$tmp/stores" 2>&1 \
    | grep -E "^(ok|FAIL|uncaught|EXC|  )|Traceback|^\s+File" | grep -v Vulkan
