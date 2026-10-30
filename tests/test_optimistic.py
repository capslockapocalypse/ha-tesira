"""Unit tests for the optimistic level state (no Home Assistant needed)."""
import asyncio

import pytest

from tesira_under_test.optimistic import OptimisticLevel  # noqa: E402  (registered by conftest.py)

SETTLE = 0.05


class _FakeDevice:
    """Records writes; each write blocks until released, like a real round-trip."""

    def __init__(self) -> None:
        self.sent: list[float] = []
        self.release = asyncio.Event()
        self.release.set()
        self.error: Exception | None = None

    async def send(self, value: float) -> None:
        self.sent.append(value)
        await self.release.wait()
        if self.error is not None:
            raise self.error


def _make(device: _FakeDevice) -> tuple[OptimisticLevel, list[float | None]]:
    seen: list[float | None] = []
    level = OptimisticLevel(device.send, lambda: seen.append(level.value), settle_seconds=SETTLE)
    return level, seen


def test_push_updates_value_when_idle():
    level, seen = _make(_FakeDevice())
    level.handle_push(-20.0)
    assert level.value == -20.0
    assert seen == [-20.0]


def test_set_shows_value_immediately():
    async def run():
        device = _FakeDevice()
        device.release.clear()
        level, _ = _make(device)
        level.handle_push(-20.0)
        task = asyncio.create_task(level.async_set(-19.0))
        await asyncio.sleep(0)
        assert level.value == -19.0  # before the device has acknowledged
        device.release.set()
        await task

    asyncio.run(run())


def test_rapid_sets_coalesce_to_latest():
    async def run():
        device = _FakeDevice()
        device.release.clear()
        level, _ = _make(device)
        level.handle_push(-20.0)
        first = asyncio.create_task(level.async_set(-19.0))
        await asyncio.sleep(0)
        # These arrive while the first write is still in flight.
        await level.async_set(-18.0)
        await level.async_set(-17.0)
        await level.async_set(-16.0)
        assert level.value == -16.0
        device.release.set()
        await first
        assert device.sent == [-19.0, -16.0]

    asyncio.run(run())


def test_stale_push_during_and_after_write_is_ignored_until_settled():
    async def run():
        device = _FakeDevice()
        device.release.clear()
        level, _ = _make(device)
        level.handle_push(-20.0)
        task = asyncio.create_task(level.async_set(-15.0))
        await asyncio.sleep(0)
        level.handle_push(-18.0)  # intermediate value from a ramp
        assert level.value == -15.0
        device.release.set()
        await task
        level.handle_push(-17.0)  # still within settle window
        assert level.value == -15.0
        level.handle_push(-15.0)
        await asyncio.sleep(SETTLE * 2)
        assert level.value == -15.0

    asyncio.run(run())


def test_reconciles_to_device_value_after_settle():
    async def run():
        device = _FakeDevice()
        level, _ = _make(device)
        level.handle_push(-20.0)
        await level.async_set(-15.5)
        level.handle_push(-15.0)  # device rounded / clamped the write
        assert level.value == -15.5
        await asyncio.sleep(SETTLE * 2)
        assert level.value == -15.0

    asyncio.run(run())


def test_push_after_settle_is_displayed():
    async def run():
        level, _ = _make(_FakeDevice())
        level.handle_push(-20.0)
        await level.async_set(-15.0)
        await asyncio.sleep(SETTLE * 2)
        level.handle_push(-30.0)  # changed on the Tesira itself
        assert level.value == -30.0

    asyncio.run(run())


def test_failed_write_reverts_to_device_value():
    async def run():
        device = _FakeDevice()
        device.error = RuntimeError("boom")
        level, _ = _make(device)
        level.handle_push(-20.0)
        with pytest.raises(RuntimeError):
            await level.async_set(-10.0)
        assert level.value == -20.0
        # Not stuck holding: the next push is displayed straight away.
        level.handle_push(-21.0)
        assert level.value == -21.0
        # And writes still work afterwards.
        device.error = None
        await level.async_set(-12.0)
        assert device.sent[-1] == -12.0

    asyncio.run(run())
