"""Installer checks must reject lost records instead of silently recreating them."""
import json
import sqlite3

import pytest

from desktop.native_smoke import check_preserved_data


def test_installer_check_detects_lost_or_rebound_state(tmp_path):
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'smoke-installation'}))
    (tmp_path / 'smoke-checkpoint.json').write_text(json.dumps({'installation_id': 'smoke-installation', 'project_id': -42}))
    with sqlite3.connect(tmp_path / 'projects.db') as db:
        db.execute('CREATE TABLE projects (freelancer_id INTEGER, title TEXT)')
        db.execute('INSERT INTO projects VALUES (?, ?)', (-42, 'Portable Python task'))
    assert check_preserved_data(tmp_path)['project_id'] == -42
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'replacement-installation'}))
    with pytest.raises(AssertionError):
        check_preserved_data(tmp_path)
    (tmp_path / 'config.json').write_text(json.dumps({'installation_id': 'smoke-installation'}))
    with sqlite3.connect(tmp_path / 'projects.db') as db:
        db.execute('DELETE FROM projects')
    with pytest.raises(AssertionError):
        check_preserved_data(tmp_path)


def test_missing_data_is_not_created_by_uninstall_check(tmp_path):
    with pytest.raises(FileNotFoundError):
        check_preserved_data(tmp_path)
    assert list(tmp_path.iterdir()) == []
