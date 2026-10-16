"""Exercise OS locks across real processes, including Windows byte-range locks."""
import subprocess
import sys
from pathlib import Path

import common


CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from common import FileLock
lock = FileLock(sys.argv[2])
try:
    print(lock.acquire(blocking=sys.argv[3] == 'blocking'), flush=True)
finally:
    lock.release()
"""


def command(path, blocking=False):
    return [sys.executable, '-c', CHILD, str(Path(common.__file__).parent), str(path),
            'blocking' if blocking else 'nonblocking']


def test_other_process_cannot_acquire_until_owner_releases(tmp_path):
    path = tmp_path / 'directory with spaces' / 'pipeline.lock'
    lock = common.FileLock(path)
    assert lock.acquire()
    try:
        result = subprocess.run(command(path), capture_output=True, text=True, timeout=10, check=True)
        assert result.stdout.strip() == 'False'
        assert lock.fd is not None
    finally:
        lock.release()
    assert lock.fd is None
    result = subprocess.run(command(path), capture_output=True, text=True, timeout=10, check=True)
    assert result.stdout.strip() == 'True'


def test_blocking_acquisition_waits_for_other_process(tmp_path):
    path = tmp_path / 'pipeline.lock'
    lock = common.FileLock(path)
    assert lock.acquire()
    child = subprocess.Popen(command(path, blocking=True), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            child.communicate(timeout=0.3)
        except subprocess.TimeoutExpired:
            pass
        else:
            raise AssertionError('Blocking lock did not wait for owner')
        lock.release()
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
        assert stdout.strip() == 'True'
    finally:
        lock.release()
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=10)


def test_scheduler_named_timezones_are_available():
    from zoneinfo import ZoneInfo
    import scheduler

    for name in ('UTC', 'Asia/Shanghai', 'America/New_York'):
        assert ZoneInfo(name).key == name
        assert 0 <= scheduler._get_local_hour(name) <= 23
