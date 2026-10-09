"""Резервные копии: создание, очистка, двухшаговое восстановление, токен Singularity."""
import json
import zipfile

import pytest

from shelfwise import backup, core


@pytest.fixture
def data(clean_data, tmp_path):
    core.save_json(core.LIBRARY_FILE, {"books": {"1": {"id": "1", "title": "A"}}, "order": ["1"]})
    core.save_json(core.PROGRESS_FILE, {"1": {"fraction": 0.3}})
    core.save_json(backup.SINGULARITY_FILE, {"token": "SECRET", "reading": True})
    return {"backupDir": str(tmp_path / "bk"), "backupKeep": 3, "fontSize": 25, "booksDir": "/here"}


def test_create_contains_data_without_token(data):
    path = backup.create(data)
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert {"manifest.json", "settings.json", "library.json", "progress.json", "singularity.json"} <= names
        assert "SECRET" not in z.read("singularity.json").decode()
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_token_included_when_enabled(data):
    path = backup.create({**data, "backupToken": True})
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read("singularity.json"))["token"] == "SECRET"


def test_prune_keeps_newest_even_within_one_second(data):
    for _ in range(5):
        last = backup.create(data)
        kept = [p for p, _when in backup.list_backups(backup.backup_dir(data))]
        assert kept[0] == last and last.exists()                # только что созданная — не удалена
    assert len(kept) == 3 and len(set(kept)) == 3


def test_restore_roundtrip(data):
    path = backup.create(data)
    core.save_json(core.PROGRESS_FILE, {"1": {"fraction": 0.9}})
    core.save_json(core.CONFIG_FILE, {"fontSize": 40, "booksDir": "/local"})
    backup.stage_restore(path)
    assert backup.apply_pending() is True
    assert core.load_json(core.PROGRESS_FILE, {})["1"]["fraction"] == 0.3
    settings = core.load_json(core.CONFIG_FILE, {})
    assert settings["fontSize"] == 25
    assert settings["booksDir"] == "/local"                     # пути этого компьютера сохранены
    assert core.load_json(backup.SINGULARITY_FILE, {})["token"] == "SECRET"   # свой токен остался
    assert backup.apply_pending() is False                      # повторно — нечего применять


def test_rejects_foreign_archive(tmp_path):
    bad = tmp_path / "x.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "other"}))
    with pytest.raises(ValueError):
        backup.stage_restore(bad)


def test_ignores_unknown_paths_in_archive(data, tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("manifest.json", json.dumps({"app": "litres-reader"}))
        z.writestr("../../escape.json", "{}")
        z.writestr("progress.json", json.dumps({"1": {"fraction": 0.1}}))
    backup.stage_restore(evil)
    assert sorted(p.name for p in backup.PENDING_DIR.iterdir()) == ["progress.json"]
    backup.cancel_pending()
