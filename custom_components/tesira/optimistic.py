"""Optimistic local state for a level that's written to the Tesira and
confirmed asynchronously via subscription pushes.

Without this, a level entity only changes state when the device's push
arrives (up to one subscribe throttle period later). Rapid volume
up/down presses then compute their next value from a stale state and
appear to get "stuck", and pushes from earlier in a burst snap the value
backwards mid-ramp.

Instead:
  * A write updates the displayed value immediately ("local feedback").
  * Writes are coalesced latest-wins: while one `set level` is in flight,
    further writes just replace the pending target rather than queueing
    a command each behind the client's single-command lock.
  * Pushes received while writes are in flight, or within a short settle
    window after the last one, are recorded but not displayed, so they
    can't drag the value back to an intermediate step.
  * Once the settle window passes, the device's last pushed value is
    adopted if it differs, so HA always converges on what the DSP has.
  * If a write fails, the displayed value reverts to the device's.

Deliberately free of Home Assistant imports so it can be unit tested.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

DEFAULT_SETTLE_SECONDS = 1.0


class OptimisticLevel:
    def __init__(
        self,
        send: Callable[[float], Awaitable[None]],
        on_change: Callable[[], None],
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
    ) -> None:
        self._send = send
        self._on_change = on_change
        self._settle_seconds = settle_seconds
        self.value: float | None = None  # what HA should display
        self.device_value: float | None = None  # last value pushed by the device
        self._pending: float | None = None
        self._sending = False
        self._hold_until = 0.0
        self._reconcile_handle: asyncio.TimerHandle | None = None

    @property
    def _holding(self) -> bool:
        return self._sending or time.monotonic() < self._hold_until

    def handle_push(self, value: float) -> None:
        """Record a value pushed by the device, displaying it unless a
        local write is in flight or still settling.
        """
        self.device_value = value
        if self._holding:
            return
        self._set_value(value)

    async def async_set(self, value: float) -> None:
        """Display `value` immediately and write it to the device.

        If a write is already in flight this returns straight away; the
        in-flight writer picks up the newest target when it finishes.
        Raises whatever `send` raises, after reverting to the device value.
        """
        self._set_value(value)
        self._pending = value
        if self._sending:
            return

        self._sending = True
        self._cancel_reconcile()
        try:
            while self._pending is not None:
                target = self._pending
                self._pending = None
                await self._send(target)
        except BaseException:
            self._pending = None
            self._sending = False
            self._hold_until = 0.0
            if self.device_value is not None:
                self._set_value(self.device_value)
            raise
        self._sending = False
        self._hold_until = time.monotonic() + self._settle_seconds
        self._reconcile_handle = asyncio.get_running_loop().call_later(
            self._settle_seconds, self._reconcile
        )

    def cancel(self) -> None:
        """Drop any scheduled reconcile (call when the entity is removed)."""
        self._cancel_reconcile()

    def _reconcile(self) -> None:
        self._reconcile_handle = None
        if self._holding:
            return  # a newer write started; it schedules its own reconcile
        if self.device_value is not None:
            self._set_value(self.device_value)

    def _cancel_reconcile(self) -> None:
        if self._reconcile_handle is not None:
            self._reconcile_handle.cancel()
            self._reconcile_handle = None

    def _set_value(self, value: float) -> None:
        if value == self.value:
            return
        self.value = value
        self._on_change()
