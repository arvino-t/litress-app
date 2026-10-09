# Установка Shelfwise на Windows 10/11 (для текущего пользователя, без прав администратора).
#
#   Двойной щелчок по install.cmd — или в PowerShell:
#   powershell -ExecutionPolicy Bypass -File windows\install.ps1
#
# Что делает:
#   - при необходимости ставит Python 3.12 через winget;
#   - создаёт своё окружение Python в %LOCALAPPDATA%\Programs\Shelfwise и ставит туда приложение с PySide6;
#   - ярлыки в меню «Пуск» и на рабочем столе;
#   - пункт «Открыть с помощью» для EPUB/FB2/MOBI;
#   - запись в «Установка и удаление программ» (там же удаление);
#   - убирает установку прежней «Читалки ЛитРес» (её данные Shelfwise перенесёт сам при запуске).
$ErrorActionPreference = 'Stop'

$Src      = Split-Path -Parent $PSScriptRoot
$AppDir   = Join-Path $env:LOCALAPPDATA 'Programs\Shelfwise'
$Venv     = Join-Path $AppDir 'venv'
$Exe      = Join-Path $Venv 'Scripts\shelfwise.exe'
$Icon     = Join-Path $AppDir 'shelfwise.ico'
$AppName  = 'Shelfwise'
$ProgId   = 'Shelfwise.Book'
$UninstKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Shelfwise'
# прежняя «Читалка ЛитРес»
$OldDir    = Join-Path $env:LOCALAPPDATA 'Programs\LitresReader'
$OldName   = 'Читалка ЛитРес'
$OldProgId = 'LitresReader.Book'
$OldKey    = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LitresReader'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# ---------------------------------------------------------------- Python
function Find-Python {
    foreach ($cmd in @('py -3', 'python', 'python3')) {
        $parts = $cmd.Split(' ')
        $exe = Get-Command $parts[0] -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $pyArgs = @($parts[1..($parts.Length)] | Where-Object { $_ }) + @('-c', 'import sys; print(sys.version_info >= (3, 10)); print(sys.executable)')
        try {
            $out = & $exe.Source @pyArgs 2>$null
            if ($out -and $out[0] -eq 'True') { return $out[1] }
        } catch { }
    }
    return $null
}

Step 'Python'
$Python = Find-Python
if (-not $Python) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host 'Python 3.10+ не найден — ставлю Python 3.12 через winget...'
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $Python = Find-Python
    }
    if (-not $Python) {
        Write-Host 'Не удалось найти или установить Python 3.10+. Поставьте его с https://www.python.org/downloads/ и запустите установку снова.' -ForegroundColor Red
        exit 1
    }
}
Write-Host "  $Python"

# ---------------------------------------------------------------- приложение
Step 'Окружение Python и приложение (PySide6 весит около 600 МБ — скачивание займёт время)'
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    & $Python -m venv $Venv
}
$VPy = Join-Path $Venv 'Scripts\python.exe'
& $VPy -m pip install --upgrade --quiet pip
& $VPy -m pip install --upgrade --quiet $Src
if ($LASTEXITCODE -ne 0) { throw 'pip не смог установить приложение' }
# Свежий код ставим всегда, даже если номер версии не менялся
& $VPy -m pip install --quiet --force-reinstall --no-deps $Src
Copy-Item (Join-Path $Src 'shelfwise\data\shelfwise.ico') $Icon -Force
Copy-Item (Join-Path $PSScriptRoot 'uninstall.ps1') (Join-Path $AppDir 'uninstall.ps1') -Force
$Version = & $VPy -c 'import shelfwise; print(shelfwise.__version__)'
Write-Host "  установлено: $Version"

# ---------------------------------------------------------------- ярлыки
Step 'Ярлыки'
$Shell = New-Object -ComObject WScript.Shell
$Targets = @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk")
)
foreach ($lnk in $Targets) {
    $s = $Shell.CreateShortcut($lnk)
    $s.TargetPath = $Exe
    $s.WorkingDirectory = $AppDir
    $s.IconLocation = "$Icon,0"
    $s.Description = 'Своя библиотека книг и статей; ЛитРес — подключаемая библиотека'
    $s.Save()
    Write-Host "  $lnk"
}

# ---------------------------------------------------------------- типы файлов («Открыть с помощью»)
Step 'Открытие EPUB/FB2/MOBI'
$Classes = 'HKCU:\Software\Classes'
New-Item -Force -Path "$Classes\$ProgId\DefaultIcon" | Out-Null
New-Item -Force -Path "$Classes\$ProgId\shell\open\command" | Out-Null
Set-ItemProperty -Path "$Classes\$ProgId" -Name '(default)' -Value 'Электронная книга'
Set-ItemProperty -Path "$Classes\$ProgId\DefaultIcon" -Name '(default)' -Value "$Icon,0"
Set-ItemProperty -Path "$Classes\$ProgId\shell\open\command" -Name '(default)' -Value "`"$Exe`" `"%1`""
foreach ($ext in @('.epub', '.fb2', '.fbz', '.mobi', '.azw3')) {
    # Добавляем себя в «Открыть с помощью», не отбирая у других программ открытие по умолчанию
    New-Item -Force -Path "$Classes\$ext\OpenWithProgids" | Out-Null
    New-ItemProperty -Force -Path "$Classes\$ext\OpenWithProgids" -Name $ProgId -Value '' -PropertyType String | Out-Null
}

# ---------------------------------------------------------------- «Установка и удаление программ»
Step 'Регистрация в списке программ'
New-Item -Force -Path $UninstKey | Out-Null
$props = @{
    DisplayName     = $AppName
    DisplayVersion  = "$Version"
    DisplayIcon     = "$Icon"
    Publisher       = 'Shelfwise'
    InstallLocation = $AppDir
    UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$AppDir\uninstall.ps1`""
    NoModify        = 1
    NoRepair        = 1
}
foreach ($k in $props.Keys) {
    $type = if ($props[$k] -is [int]) { 'DWord' } else { 'String' }
    New-ItemProperty -Force -Path $UninstKey -Name $k -Value $props[$k] -PropertyType $type | Out-Null
}

# ---------------------------------------------------------------- прежняя «Читалка ЛитРес»
if ((Test-Path $OldDir) -or (Test-Path $OldKey)) {
    Step 'Убираю прежнюю «Читалку ЛитРес»'
    foreach ($lnk in @(
        (Join-Path ([Environment]::GetFolderPath('Programs')) "$OldName.lnk"),
        (Join-Path ([Environment]::GetFolderPath('Desktop')) "$OldName.lnk"))) {
        Remove-Item -Force $lnk -ErrorAction SilentlyContinue
    }
    Remove-Item -Recurse -Force "$Classes\$OldProgId" -ErrorAction SilentlyContinue
    foreach ($ext in @('.epub', '.fb2', '.fbz', '.mobi', '.azw3')) {
        Remove-ItemProperty -Path "$Classes\$ext\OpenWithProgids" -Name $OldProgId -ErrorAction SilentlyContinue
    }
    Remove-Item -Recurse -Force $OldKey -ErrorAction SilentlyContinue
    if (Get-Process litres-reader -ErrorAction SilentlyContinue) {
        Write-Host "  прежняя версия открыта — её папка $OldDir удалится при следующей установке"
    } else {
        Remove-Item -Recurse -Force $OldDir -ErrorAction SilentlyContinue
    }
}

Step 'Готово'
Write-Host "«$AppName» есть в меню «Пуск» и на рабочем столе."
Write-Host 'Удалить: «Параметры» → «Приложения» → «Shelfwise» → «Удалить».'
