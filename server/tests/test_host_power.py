"""Unit tests for holding and handing over host power requests (#726).

These use the in-memory store and a temporary request directory, so they need
no Docker stack and never touch a real host. A request made while a backup is
running can't be timed reliably through the API, so it is covered here.
"""
import os
import time
from types import SimpleNamespace

import pytest

import host_power

pytestmark = pytest.mark.unit


@pytest.fixture
def sent(monkeypatch):
    """Notifications sent when a held request goes ahead. They need the
    database, so they're recorded instead."""
    sent = []
    monkeypatch.setattr(
        'notification_utils.create_notification',
        lambda **kwargs: sent.append(kwargs) or True,
    )
    return sent


@pytest.fixture
def request_dir(tmp_path, monkeypatch, sent):
    monkeypatch.setenv('HOST_POWER_CONTROL', 'true')
    monkeypatch.setenv('HOST_CONTROL_DIR', str(tmp_path))
    monkeypatch.setattr(host_power, '_store', host_power.Store())
    return tmp_path


ADMIN = SimpleNamespace(id=1, username='admin')


def _notify_list():
    calls = []
    return calls, lambda subject, message: calls.append((subject, message))


def _request_file(directory):
    path = directory / host_power.REQUEST_FILENAME
    return path.read_text() if path.exists() else None


class TestEnabled:
    def test_off_without_env_setting(self, request_dir, monkeypatch):
        monkeypatch.setenv('HOST_POWER_CONTROL', 'false')
        assert host_power.is_enabled() is False

    def test_off_without_directory(self, request_dir, monkeypatch):
        monkeypatch.setenv('HOST_CONTROL_DIR', str(request_dir / 'missing'))
        assert host_power.is_enabled() is False

    @pytest.mark.skipif(os.name != 'posix' or os.geteuid() == 0, reason='root can write anywhere')
    def test_off_when_directory_not_writable(self, request_dir):
        request_dir.chmod(0o500)
        try:
            assert host_power.is_enabled() is False
        finally:
            request_dir.chmod(0o700)

    def test_on_with_setting_and_directory(self, request_dir):
        assert host_power.is_enabled() is True


class TestRequest:
    def test_writes_exact_action_when_idle(self, request_dir):
        calls, notify = _notify_list()
        held, waiting_for = host_power.request_action('reboot', ADMIN, '192.0.2.1', notify)

        assert (held, waiting_for) == (False, [])
        assert _request_file(request_dir) == 'reboot'
        assert host_power.pending_request() is None
        assert host_power.requested_action() == 'reboot'
        assert '192.0.2.1' in calls[0][1]
        # Only the request file is left behind, no temporary files.
        assert os.listdir(request_dir) == ['request']

    def test_poweroff(self, request_dir):
        host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)
        assert _request_file(request_dir) == 'poweroff'

    def test_unknown_action_rejected(self, request_dir):
        with pytest.raises(ValueError):
            host_power.request_action('rm -rf /', ADMIN, '192.0.2.1', lambda *a: None)
        assert _request_file(request_dir) is None

    def test_second_request_refused_until_host_acts(self, request_dir):
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        with pytest.raises(host_power.RequestRefused):
            host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)
        assert _request_file(request_dir) == 'reboot'

        # The host deletes the file when it acts.
        (request_dir / 'request').unlink()
        host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)
        assert _request_file(request_dir) == 'poweroff'

    def test_simultaneous_request_does_not_replace_the_first(self, request_dir, monkeypatch):
        """Two requests can both pass the file check before either writes."""
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        monkeypatch.setattr(host_power, 'requested_action', lambda: None)

        with pytest.raises(host_power.RequestRefused):
            host_power.request_action('poweroff', ADMIN, '192.0.2.2', lambda *a: None)

        assert _request_file(request_dir) == 'reboot'
        assert os.listdir(request_dir) == ['request']
        assert host_power.pending_request() is None

    def test_unrecognised_file_reported(self, request_dir):
        (request_dir / 'request').write_text('something else')
        assert host_power.requested_action() == 'unknown'


class TestHeldDuringWork:
    def test_held_while_backup_runs_then_released(self, request_dir, sent):
        key = host_power.start_work('backup')
        calls, notify = _notify_list()

        held, waiting_for = host_power.request_action('reboot', ADMIN, '192.0.2.1', notify)

        assert (held, waiting_for) == (True, ['backup'])
        assert _request_file(request_dir) is None
        pending = host_power.pending_request()
        assert pending['action'] == 'reboot'
        assert pending['username'] == 'admin'
        assert pending['waiting_for'] == ['backup']
        assert 'when it finishes' in calls[0][1]

        host_power.finish_work(key)

        assert _request_file(request_dir) == 'reboot'
        assert host_power.pending_request() is None
        assert len(sent) == 1 and sent[0]['for_admins'] is True

    def test_waits_for_every_running_job(self, request_dir):
        backup = host_power.start_work('backup')
        restore = host_power.start_work('restore')
        host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)

        host_power.finish_work(backup)
        assert _request_file(request_dir) is None
        assert host_power.pending_request()['waiting_for'] == ['restore']

        host_power.finish_work(restore)
        assert _request_file(request_dir) == 'poweroff'

    def test_released_when_wrapped_function_fails(self, request_dir):
        @host_power.holds_host_power('backup')
        def failing_backup():
            assert host_power.running_work() == ['backup']
            host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
            raise RuntimeError('mysqldump failed')

        with pytest.raises(RuntimeError):
            failing_backup()

        assert host_power.running_work() == []
        assert _request_file(request_dir) == 'reboot'

    def test_second_request_refused_while_held(self, request_dir):
        host_power.start_work('backup')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        with pytest.raises(host_power.RequestRefused):
            host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)

    def test_cancel_clears_held_request(self, request_dir):
        key = host_power.start_work('restore')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)

        assert host_power.cancel(ADMIN, '192.0.2.1') == 'reboot'
        host_power.finish_work(key)

        assert _request_file(request_dir) is None
        assert host_power.cancel(ADMIN, '192.0.2.1') is None

    def test_cancel_removes_request_host_has_not_acted_on(self, request_dir):
        host_power.request_action('poweroff', ADMIN, '192.0.2.1', lambda *a: None)
        assert host_power.cancel(ADMIN, '192.0.2.1') == 'poweroff'
        assert _request_file(request_dir) is None

    def test_held_request_expires(self, request_dir, monkeypatch):
        key = host_power.start_work('backup')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        real_monotonic = time.monotonic
        monkeypatch.setattr(
            time, 'monotonic', lambda: real_monotonic() + host_power.PENDING_TTL_SECONDS + 1
        )
        # The running entry outlives the held request.
        assert host_power.running_work() == ['backup']
        assert host_power.pending_request() is None

        host_power.finish_work(key)
        assert _request_file(request_dir) is None

    def test_not_written_if_feature_turned_off_meanwhile(self, request_dir, monkeypatch):
        key = host_power.start_work('backup')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        monkeypatch.setenv('HOST_POWER_CONTROL', 'false')

        host_power.finish_work(key)

        assert _request_file(request_dir) is None
        assert host_power.pending_request() is None

    def test_work_from_stopped_process_is_forgotten(self, request_dir, monkeypatch):
        host_power.start_work('backup')
        monkeypatch.setattr(host_power, '_process_is_alive', lambda owner: False)
        assert host_power.running_work() == []


class TestStartup:
    def test_clears_held_request_when_nothing_runs(self, request_dir):
        key = host_power.start_work('backup')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)
        host_power._store.delete(key)  # the process running it died

        host_power.clear_on_startup()

        assert host_power.pending_request() is None
        assert _request_file(request_dir) is None

    def test_keeps_held_request_while_work_runs(self, request_dir):
        host_power.start_work('backup')
        host_power.request_action('reboot', ADMIN, '192.0.2.1', lambda *a: None)

        host_power.clear_on_startup()

        assert host_power.pending_request()['action'] == 'reboot'


def test_describe_work():
    assert host_power.describe_work(['backup']) == 'A backup is running.'
    assert host_power.describe_work(['backup', 'backup']) == 'A backup is running.'
    assert host_power.describe_work(['backup', 'restore']) == 'A backup and a restore are running.'
