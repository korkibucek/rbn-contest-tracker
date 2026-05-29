"""Feed sources: the live RBN telnet aggregator, and a file replay for testing.

Both expose ``lines()`` -- an iterator of decoded text lines (without trailing
newlines). The telnet feed handles login and reconnects with exponential
backoff; it never raises out of ``lines()`` for transient network errors.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Iterator

log = logging.getLogger("rbn.feed")

RBN_HOST = "telnet.reversebeacon.net"
RBN_PORT = 7000
LOGIN_TIMEOUT = 10.0  # seconds to wait for a recognisable login prompt
RECONNECT_BACKOFF = [2, 4, 8, 16, 30]  # seconds; last value repeats

# Substrings that indicate the server is asking for our callsign.
_PROMPT_HINTS = ("call", "login", "please enter", "your call")


class TelnetFeed:
    """Streams raw spot lines from the RBN telnet aggregator."""

    def __init__(self, callsign: str, host: str = RBN_HOST, port: int = RBN_PORT,
                 connect_timeout: float = 15.0) -> None:
        self.callsign = callsign.strip().upper()
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self._stop = False
        self.connected = False  # True between successful login and disconnect

    def stop(self) -> None:
        self._stop = True

    # --- connection helpers ---
    def _connect(self) -> socket.socket:
        # Prefer IPv4 then IPv6; some sandboxes lack IPv6.
        last_err: Exception | None = None
        for family in (socket.AF_INET, socket.AF_INET6):
            try:
                infos = socket.getaddrinfo(self.host, self.port, family,
                                           socket.SOCK_STREAM)
            except socket.gaierror as exc:
                last_err = exc
                continue
            for info in infos:
                af, socktype, proto, _canon, sockaddr = info
                try:
                    s = socket.socket(af, socktype, proto)
                    s.settimeout(self.connect_timeout)
                    s.connect(sockaddr)
                    return s
                except OSError as exc:
                    last_err = exc
                    continue
        raise OSError(f"could not connect to {self.host}:{self.port}: {last_err}")

    def _login(self, sock: socket.socket) -> None:
        """Wait (up to LOGIN_TIMEOUT) for a call prompt, then send our call."""
        sock.settimeout(1.0)
        deadline = time.monotonic() + LOGIN_TIMEOUT
        buf = ""
        prompted = False
        while time.monotonic() < deadline:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk.decode("latin-1", errors="replace")
            low = buf.lower()
            if any(h in low for h in _PROMPT_HINTS):
                prompted = True
                break
        if not prompted:
            log.warning("no login prompt within %.0fs; sending callsign anyway",
                        LOGIN_TIMEOUT)
        sock.sendall((self.callsign + "\r\n").encode("ascii", errors="replace"))
        log.info("sent login callsign %s", self.callsign)

    # --- main line iterator ---
    def lines(self) -> Iterator[str]:
        attempt = 0
        while not self._stop:
            try:
                log.info("connecting to %s:%d ...", self.host, self.port)
                sock = self._connect()
                self._login(sock)
                self.connected = True
                attempt = 0  # reset backoff on a successful connect+login
                sock.settimeout(120.0)
                yield from self._read_lines(sock)
            except (OSError, socket.timeout) as exc:
                log.warning("feed connection error: %s", exc)
            finally:
                self.connected = False
                try:
                    sock.close()  # type: ignore[has-type]
                except Exception:
                    pass
            if self._stop:
                break
            delay = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log.info("reconnecting in %ds (attempt %d)", delay, attempt)
            time.sleep(delay)

    def _read_lines(self, sock: socket.socket) -> Iterator[str]:
        buf = b""
        while not self._stop:
            try:
                chunk = sock.recv(8192)
            except socket.timeout:
                # No data for a while; keep the socket and keep waiting.
                continue
            if not chunk:
                raise OSError("connection closed by server")
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                yield raw.decode("latin-1", errors="replace").rstrip("\r")


class ReplayFeed:
    """Replays raw spot lines from a file -- used for testing without the net."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def lines(self) -> Iterator[str]:
        with open(self.path, "r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                if self._stop:
                    break
                yield raw.rstrip("\r\n")
