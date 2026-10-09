"""Переименования «Читалка ЛитРес» → Shelfwise → Muninhall: перенос данных и старые резервные копии."""
import json
import zipfile

from muninhall import backup, core


def test_old_data_moves_to_new_dirs(clean_data):
    old_data, old_config, old_cache = core._dirs("litres-reader")
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
    assert listed == [new, old] and new.name.startswith("muninhall-backup-")
    assert backup.scope_of(old) == "all"
    backup.stage_restore(old)
    backup.apply_pending()
    assert core.load_json(core.PROGRESS_FILE, {})["1"]["fraction"] == 0.4


def test_default_backup_dir_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "default_dir", lambda: tmp_path / "Backups" / "muninhall")
    (tmp_path / "Backups" / "litres-reader").mkdir(parents=True)
    (tmp_path / "Backups" / "litres-reader" / "x.zip").write_text("x")
    backup.migrate_default_dir()
    assert (tmp_path / "Backups" / "muninhall" / "x.zip").exists()


def test_shelfwise_data_also_moves(clean_data):
    core.LIBRARY_FILE.unlink(missing_ok=True)
    old_data = core._dirs("shelfwise")[0]
    old_data.mkdir(parents=True, exist_ok=True)
    (old_data / "library.json").write_text(json.dumps({"books": {"7": {"id": "7"}}}))
    assert core.migration_needed()
    core.migrate_old_dirs()
    assert json.loads(core.LIBRARY_FILE.read_text())["books"]["7"]["id"] == "7"


def test_backups_from_both_old_names(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "default_dir", lambda: tmp_path / "Backups" / "muninhall")
    for name in ("shelfwise", "litres-reader"):
        (tmp_path / "Backups" / name).mkdir(parents=True)
        (tmp_path / "Backups" / name / f"{name}-backup-2026-10-0{len(name) % 9}_120000.zip").write_text("x")
    backup.migrate_default_dir()
    names = sorted(p.name for p in (tmp_path / "Backups" / "muninhall").iterdir())
    assert len(names) == 2 and not (tmp_path / "Backups" / "shelfwise").exists()
