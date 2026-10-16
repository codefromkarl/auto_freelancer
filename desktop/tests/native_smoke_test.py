"""Installer checks must reject lost records instead of silently recreating them."""
from contextlib import closing
import json
import sqlite3

import pytest

from desktop.native_smoke import check_preserved_data


def test_installer_check_detects_lost_or_rebound_state(tmp_path, monkeypatch):
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'smoke-installation'}))
    (tmp_path / 'smoke-checkpoint.json').write_text(json.dumps({'installation_id': 'smoke-installation', 'project_id': -42}))
    with closing(sqlite3.connect(tmp_path / 'projects.db')) as db, db:
        db.execute('CREATE TABLE projects (freelancer_id INTEGER, title TEXT)')
        db.execute('INSERT INTO projects VALUES (?, ?)', (-42, 'Portable Python task'))
    opened = []
    original = sqlite3.connect

    def tracked(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, 'connect', tracked)
    assert check_preserved_data(tmp_path)['project_id'] == -42
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        opened[0].execute('SELECT 1')
    monkeypatch.setattr(sqlite3, 'connect', original)
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'replacement-installation'}))
    with pytest.raises(AssertionError):
        check_preserved_data(tmp_path)
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'smoke-installation'}))
    with closing(sqlite3.connect(tmp_path / 'projects.db')) as db, db:
        db.execute('DELETE FROM projects')
    with pytest.raises(AssertionError):
        check_preserved_data(tmp_path)


def test_missing_data_is_not_created_by_uninstall_check(tmp_path):
    with pytest.raises(FileNotFoundError):
        check_preserved_data(tmp_path)
    assert list(tmp_path.iterdir()) == []
