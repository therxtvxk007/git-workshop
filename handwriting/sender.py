"""Streaming G-code to a GRBL controller over USB serial.

Uses the character-counting protocol: keep GRBL's 128-byte receive buffer as
full as possible without overflowing it, so motion never stutters mid-letter.
Simple send-and-wait works but produces visibly jerky curves.

``pyserial`` is an optional dependency — everything else in this package works
without it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

RX_BUFFER_SIZE = 128


class SerialUnavailable(RuntimeError):
    pass


def _open_serial(port: str, baud: int, timeout: float = 0.25):
    try:
        import serial  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise SerialUnavailable(
            "pyserial is required to talk to the machine. Install it with:\n"
            "    pip install 'handwriting-machine[serial]'\n"
            "You can still generate G-code and send it with any other sender."
        ) from exc
    return serial.Serial(port, baud, timeout=timeout)


def clean_lines(text: str) -> Iterator[str]:
    """Strip comments and blanks; GRBL does not need them and they cost buffer."""
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if line:
            yield line


@dataclass
class SendResult:
    lines_sent: int
    seconds: float
    errors: list[str]


def list_ports() -> list[str]:
    """Best-effort list of candidate serial ports."""
    try:
        from serial.tools import list_ports as _lp  # type: ignore[import-not-found]
    except ImportError:
        return []
    return [p.device for p in _lp.comports()]


def send(
    gcode: str,
    port: str,
    baud: int = 115200,
    on_progress: Callable[[int, int, str], None] | None = None,
    wake_delay: float = 2.0,
) -> SendResult:
    """Stream ``gcode`` to a GRBL device on ``port``.

    Blocks until the machine has acknowledged every line.
    """
    lines = list(clean_lines(gcode))
    total = len(lines)
    errors: list[str] = []

    ser = _open_serial(port, baud)
    started = time.time()
    try:
        # Opening the port resets most Arduino boards; wait for the banner.
        ser.write(b"\r\n\r\n")
        time.sleep(wake_delay)
        ser.reset_input_buffer()

        pending: list[int] = []      # byte lengths of unacknowledged lines
        sent = 0

        for index, line in enumerate(lines):
            payload = (line + "\n").encode("ascii", errors="ignore")

            # Wait until this line fits in GRBL's receive buffer.
            while sum(pending) + len(payload) >= RX_BUFFER_SIZE:
                _drain(ser, pending, errors)

            ser.write(payload)
            pending.append(len(payload))
            sent += 1
            if on_progress:
                on_progress(index + 1, total, line)

        # Wait for the tail of the queue to be acknowledged.
        while pending:
            _drain(ser, pending, errors)
    finally:
        ser.close()

    return SendResult(lines_sent=sent, seconds=time.time() - started, errors=errors)


def _drain(ser, pending: list[int], errors: list[str]) -> None:
    """Consume one response from GRBL and release its buffer slot."""
    response = ser.readline().decode("ascii", errors="replace").strip()
    if not response:
        return
    if response.startswith("ok"):
        if pending:
            pending.pop(0)
    elif response.startswith("error") or response.startswith("ALARM"):
        errors.append(response)
        if pending:
            pending.pop(0)
    # Anything else (startup banner, status reports) is informational.
