"""Переименование «Читалка ЛитРес» → Shelfwise: перенос данных и старые резервные копии."""
import json
import zipfile

from shelfwise import backup, core


def test_old_data_moves_to_new_dirs(clean_data):
    old_data, old_config, old_cache = core._dirs(core.OLD_SLUG)
    for d in (old_data, old_config, old_cache):
        d.mkdir(parents=True, exist_ok=True)
    (old_data / "library.json").write_text(json.dumps({"books": {"1": {"id": "1"}}}))
    (old_data / "webengine").mkdir(exist_ok=True)
    (old_data / "webengine" / "Cookies").write_text("session")
    (old_config / "settings.json").write_text(json.dumps({"fontSize": 30}))
    assert core.migration_needed()
    moved = core.migrate_old_dirs()
    assert moved
    assert json.loads(core.LIBRARY_FILE.read_text())["books"]["1"]["id"] == "1"
    assert (core.DATA_DIR / "webengine" / "Cookies").read_text() == "session"      # вход в ЛитРес сохранён
    assert json.loads(core.CONFIG_FILE.read_text())["fontSize"] == 30
    assert not core.migration_needed()
    assert core.migrate_old_dirs() == []                                          # повторно — ничего


def test_old_backups_listed_and_restorable(clean_data, tmp_path):
    folder = tmp_path / "bk"
    folder.mkdir()
    old = folder / "litres-reader-backup-2026-10-01_120000.zip"
    with zipfile.ZipFile(old, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "litres-reader", "version": "0.14.0"}))
        z.writestr("progress.json", json.dumps({"1": {"fraction": 0.4}}))
    new = backup.create({"backupDir": str(folder)})
    listed = [p for p, _when in backup.list_backups(folder)]
    assert listed == [new, old] and new.name.startswith("shelfwise-backup-")
    backup.stage_restore(old)
    backup.apply_pending()
    assert core.load_json(core.PROGRESS_FILE, {})["1"]["fraction"] == 0.4


def test_default_backup_dir_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "default_dir", lambda: tmp_path / "Backups" / "shelfwise")
    (tmp_path / "Backups" / "litres-reader").mkdir(parents=True)
    (tmp_path / "Backups" / "litres-reader" / "x.zip").write_text("x")
    backup.migrate_default_dir()
    assert (tmp_path / "Backups" / "shelfwise" / "x.zip").exists()
