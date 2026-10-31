"""Unit tests for the setup restore claim, using the in-memory store (issue #499)."""
import time

import pytest

from restore_progress import ProgressStore


@pytest.fixture
def store():
    return ProgressStore()


def test_second_claim_is_refused_until_released(store):
    assert store.claim('key') is True
    assert store.claim('key') is False

    store.release('key')

    assert store.claim('key') is True


def test_claim_is_visible_to_read(store):
    assert store.read('key') is None

    store.claim('key')

    assert store.read('key') is not None


def test_expired_claim_can_be_taken_again(store, monkeypatch):
    store.claim('key')
    real_monotonic = time.monotonic
    monkeypatch.setattr(time, 'monotonic', lambda: real_monotonic() + 3601)

    assert store.claim('key') is True
