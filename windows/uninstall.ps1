# Удаление Shelfwise (запускается из «Установка и удаление программ»).
# Книги и настройки в %LOCALAPPDATA%\shelfwise и %APPDATA%\shelfwise остаются,
# данные своих библиотек — в их папках (.library).
$ErrorActionPreference = 'SilentlyContinue'

$AppDir  = Join-Path $env:LOCALAPPDATA 'Programs\Shelfwise'
$AppName = 'Shelfwise'
$ProgId  = 'Shelfwise.Book'

Get-Process shelfwise -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($lnk in @(
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$AppName.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk"))) {
    Remove-Item -Force $lnk
}

$Classes = 'HKCU:\Software\Classes'
Remove-Item -Recurse -Force "$Classes\$ProgId"
foreach ($ext in @('.epub', '.fb2', '.fbz', '.mobi', '.azw3')) {
    Remove-ItemProperty -Path "$Classes\$ext\OpenWithProgids" -Name $ProgId
}
Remove-Item -Recurse -Force 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Shelfwise'

# Папку с программой удаляем после выхода из этого скрипта (он лежит в ней же)
Start-Process -WindowStyle Hidden cmd.exe -ArgumentList "/c timeout /t 2 /nobreak >nul & rmdir /s /q `"$AppDir`""

Write-Host "«$AppName» удалена. Книги и настройки остались в $env:LOCALAPPDATA\shelfwise и $env:APPDATA\shelfwise."
