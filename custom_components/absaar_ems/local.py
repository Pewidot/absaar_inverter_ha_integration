"""Local (cloud-free) mode for Absaar/GT800TL inverters.

The inverter's WiFi datalogger normally pushes data to the vendor cloud via a
raw TCP connection. In local mode this integration runs that TCP server itself:
the datalogger is pointed at the Home Assistant host and the integration
decodes the proprietary protocol directly. No cloud account, no tokens, no
stale morning data.

Protocol (reverse engineered): frames start with magic 0xEA91, byte 4-5 hold
the payload length (big endian, excluding the 6 byte header). The datalogger
sends a LOGIN frame (19 bytes) on connect; we answer with a query frame and it
replies with a 164 byte DATA frame containing the measurements at fixed
offsets. We re-query every poll_delay seconds.
"""
import asyncio
import logging
import re
import socket
import struct
import time
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

import homeassistant.util.dt as dt_util
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

MAGIC = bytes.fromhex("ea91")
DATA_LEN = 164
LOGIN_LEN = 19
QUERY_SUFFIX = bytes.fromhex("000000000000000811040000003c8bf2")
# Anything larger than this in the length field is a corrupt frame.
MAX_FRAME_LEN = 1024

# The datalogger's WiFi link is often weak: HTTP responses break off midway
# and the TCP tunnel drops and reconnects. Retry HTTP reads, and keep entities
# available for a grace period so quick reconnects don't flap them.
HTTP_ATTEMPTS = 3
HTTP_RETRY_WAIT = 10
OFFLINE_GRACE = 90

# offset in the DATA frame -> (key, divisor)
FIELDS = {
    44: ("pv1_voltage", 10),
    46: ("pv2_voltage", 10),
    52: ("ac_voltage", 10),
    58: ("pv1_current", 10),
    60: ("pv2_current", 10),
    # uint16 / 10 -> wraps at 6553.5 kWh; the register on the wire is only
    # 16 bit as far as known.
    66: ("total_energy", 10),
    68: ("ac_frequency", 100),
    78: ("pv1_power", 1),
    82: ("pv2_power", 1),
    90: ("ac_power", 1),
}

IP_SETTING_RE = re.compile(r'var net_setting_ip\s*=\s*"([^"]+)"')


class AbsaarLocalHub:
    """TCP server the inverter datalogger connects to, plus optional IP-keeper."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        port: int,
        serial: str,
        poll_delay: int,
        datalogger_url: str,
        datalogger_username: str,
        datalogger_password: str,
        listener_ip: str,
        ip_check_interval: int,
    ) -> None:
        """Initialize the hub."""
        self._hass = hass
        self._entry_id = entry_id
        self._port = port
        self._poll_delay = max(int(poll_delay), 1)
        url = (datalogger_url or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            url = f"http://{url}"
        self._datalogger_url = url
        self._datalogger_username = datalogger_username
        self._datalogger_password = datalogger_password
        self._listener_ip = (listener_ip or "").strip()
        self._ip_check_interval = max(int(ip_check_interval), 30)

        self.serial = (serial or "").strip()
        self.data: dict[str, float] = {}
        self.online = False
        self.last_seen = None

        self._server: asyncio.Server | None = None
        self._ip_task: asyncio.Task | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._offline_timer = None
        self._check_failures = 0
        self._verified_target: str | None = None

    @property
    def signal(self) -> str:
        """Dispatcher signal name for entity updates."""
        return f"{DOMAIN}_{self._entry_id}_update"

    @property
    def port(self) -> int:
        """TCP port the hub listens on."""
        return self._port

    async def async_start(self) -> None:
        """Start the TCP server and, if configured, the datalogger IP-keeper."""
        self._server = await asyncio.start_server(
            self._handle_client, "0.0.0.0", self._port
        )
        _LOGGER.info("Absaar local mode listening on TCP port %s", self._port)
        if self._datalogger_url:
            self._ip_task = self._hass.loop.create_task(self._ip_check_loop())

    async def async_stop(self) -> None:
        """Stop the server and background tasks."""
        self._cancel_offline_timer()
        if self._ip_task:
            self._ip_task.cancel()
            self._ip_task = None
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    # ── TCP handling ─────────────────────────────────────────────────────────

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("Datalogger connected from %s", peer)

        # The datalogger only ever holds one session; a new connection means
        # the old one is dead, so drop it instead of polling twice in parallel.
        if self._writer is not None:
            self._writer.close()
        self._writer = writer

        buf = b""
        # Generous on purpose: a weak WiFi link may stall for a while without
        # being dead, and TCP retransmits bridge short dropouts.
        timeout = max(self._poll_delay + 30, 60)
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(1024), timeout=timeout)
                except asyncio.TimeoutError:
                    _LOGGER.debug("Datalogger %s timed out", peer)
                    break
                if not chunk:
                    _LOGGER.debug("Datalogger %s disconnected", peer)
                    break
                buf += chunk
                buf = await self._process_buffer(buf, writer)
        except (ConnectionResetError, OSError) as err:
            _LOGGER.debug("Connection error from %s: %s", peer, err)
        finally:
            if self._writer is writer:
                self._writer = None
                # Don't flap entities on a quick reconnect; go offline only
                # if no data arrives within the grace period.
                self._schedule_offline()
            writer.close()

    async def _process_buffer(
        self, buf: bytes, writer: asyncio.StreamWriter
    ) -> bytes:
        """Extract and handle all complete frames in the buffer."""
        while len(buf) >= 6:
            if buf[:2] != MAGIC:
                idx = buf.find(MAGIC)
                buf = buf[idx:] if idx != -1 else b""
                continue

            frame_len = struct.unpack_from(">H", buf, 4)[0] + 6
            if frame_len > MAX_FRAME_LEN:
                # Corrupt length field; resync on the next magic marker.
                buf = buf[2:]
                continue
            if len(buf) < frame_len:
                break

            frame = buf[:frame_len]
            buf = buf[frame_len:]
            cmd = frame[6] if len(frame) > 6 else 0
            subcmd = frame[7] if len(frame) > 7 else 0

            if cmd == 0x01 and subcmd == 0x01 and len(frame) == LOGIN_LEN:
                reported = frame[8:18].decode("ascii", errors="replace").rstrip("\x00")
                if reported:
                    self.serial = reported
                _LOGGER.debug("Login from serial %s, sending query", self.serial)
                writer.write(self._build_query())
                await writer.drain()

            elif cmd == 0x01 and subcmd == 0x02 and len(frame) == DATA_LEN:
                self._handle_data_frame(frame)
                await asyncio.sleep(self._poll_delay)
                writer.write(self._build_query())
                await writer.drain()

            else:
                _LOGGER.debug(
                    "Unknown frame (%s bytes, cmd=%02X sub=%02X)",
                    len(frame), cmd, subcmd,
                )
        return buf

    def _handle_data_frame(self, frame: bytes) -> None:
        serial = frame[8:18].decode("ascii", errors="replace").rstrip("\x00")
        if serial:
            self.serial = serial
        for offset, (key, divisor) in FIELDS.items():
            self.data[key] = struct.unpack_from(">H", frame, offset)[0] / divisor
        self.data["pv_total_power"] = (
            self.data.get("pv1_power", 0) + self.data.get("pv2_power", 0)
        )
        self.last_seen = dt_util.utcnow()
        self._cancel_offline_timer()
        self._set_online(True)
        self._notify()

    def _build_query(self) -> bytes:
        serial_bytes = self.serial.encode("ascii")[:10].ljust(10, b"\x00")
        return MAGIC + b"\x00\x01" + b"\x00\x1c" + b"\x01\x02" + serial_bytes + QUERY_SUFFIX

    @callback
    def _set_online(self, online: bool) -> None:
        if self.online != online:
            self.online = online
            self._notify()

    @callback
    def _schedule_offline(self) -> None:
        self._cancel_offline_timer()
        self._offline_timer = self._hass.loop.call_later(
            OFFLINE_GRACE, self._set_online, False
        )

    @callback
    def _cancel_offline_timer(self) -> None:
        if self._offline_timer is not None:
            self._offline_timer.cancel()
            self._offline_timer = None

    @callback
    def _notify(self) -> None:
        async_dispatcher_send(self._hass, self.signal)

    # ── Datalogger IP-keeper ─────────────────────────────────────────────────
    # Optional: checks the datalogger's web UI and re-points its destination
    # IP at the Home Assistant host if the vendor app or a reset changed it.

    async def _ip_check_loop(self) -> None:
        while True:
            # While the datalogger is connected its target is evidently
            # correct — and the HF-LPT230's tiny web server usually stops
            # answering while its TCP tunnel is busy, so probing it now would
            # only produce noise. Check only while we get no data.
            if self.online:
                _LOGGER.debug("Datalogger connected, skipping IP check")
            else:
                try:
                    await self._hass.async_add_executor_job(
                        self._check_datalogger_target
                    )
                    self._check_failures = 0
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001 - keep the loop alive
                    # A weak WiFi link fails here routinely; warn on the
                    # first failure and then only every tenth, else debug.
                    self._check_failures += 1
                    if self._check_failures == 1 or self._check_failures % 10 == 0:
                        _LOGGER.warning(
                            "Datalogger IP check failed (%s in a row): %s",
                            self._check_failures, err,
                        )
                    else:
                        _LOGGER.debug("Datalogger IP check failed: %s", err)
            await asyncio.sleep(self._ip_check_interval)

    def _check_datalogger_target(self) -> None:
        auth = HTTPBasicAuth(self._datalogger_username, self._datalogger_password)
        # The module's web server is slow and its WiFi link weak: responses
        # time out or break off midway (IncompleteRead). Retry a few times —
        # against a flaky link retries help where longer timeouts cannot.
        resp = None
        last_err = None
        for attempt in range(1, HTTP_ATTEMPTS + 1):
            try:
                resp = requests.get(
                    f"{self._datalogger_url}/port_en.html", auth=auth, timeout=60
                )
                break
            except requests.exceptions.RequestException as err:
                last_err = err
                _LOGGER.debug(
                    "Settings page attempt %s/%s failed: %s",
                    attempt, HTTP_ATTEMPTS, err,
                )
                if attempt < HTTP_ATTEMPTS:
                    time.sleep(HTTP_RETRY_WAIT)
        if resp is None:
            raise last_err
        if resp.status_code != 200:
            _LOGGER.warning(
                "Datalogger settings page returned HTTP %s, skipping IP check",
                resp.status_code,
            )
            return

        match = IP_SETTING_RE.search(resp.text)
        if not match:
            # Never rewrite blindly: an unparseable page (login redirect,
            # firmware variant) must not trigger a reconfigure/restart loop.
            _LOGGER.warning(
                "Could not parse datalogger settings page, skipping IP check"
            )
            return

        target = self._listener_ip or self._detect_listener_ip()
        if not target:
            _LOGGER.warning(
                "Cannot determine own IP for the datalogger, skipping IP check"
            )
            return

        current = match.group(1)
        if current == target:
            if self._verified_target != current:
                self._verified_target = current
                _LOGGER.info(
                    "Datalogger destination verified: %s:%s", current, self._port
                )
            else:
                _LOGGER.debug("Datalogger destination IP is correct (%s)", current)
            return

        self._verified_target = None
        _LOGGER.warning(
            "Datalogger points at %s, re-pointing to %s and restarting it",
            current, target,
        )
        headers = {
            "Referer": f"{self._datalogger_url}/port_en.html",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        requests.post(
            f"{self._datalogger_url}/do_cmd_en.html",
            data={
                "net_setting_pro": "TCP",
                "net_setting_cs": "CLIENT",
                "net_setting_pro_sel": "TCPCLIENT",
                "net_setting_port": str(self._port),
                "net_setting_ip": target,
                "net_setting_to": "300",
            },
            auth=auth, headers=headers, timeout=60,
        )
        time.sleep(2)
        requests.post(
            f"{self._datalogger_url}/do_cmd_en.html",
            data={"HF_PROCESS_CMD": "RESTART"},
            auth=auth, headers=headers, timeout=60,
        )

    def _detect_listener_ip(self) -> str | None:
        """Find the local IP the datalogger can reach us on."""
        host = urlparse(self._datalogger_url).hostname
        if not host:
            return None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((host, 80))
            return sock.getsockname()[0]
        except OSError:
            return None
        finally:
            sock.close()
