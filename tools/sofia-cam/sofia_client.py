"""
sofia_client - talk to Xiongmai / Sofia / DVRIP IP cameras over TCP 34567.

This is the proprietary protocol behind the XMEye and iCSee apps. Many recent
white-label cameras (firmware family V5.08.R02.000999WP and similar) ship with
RTSP and ONVIF stripped out, so port 34567 is the only way in.

Pure standard library, Python 3.9+.

Two jobs:
  - control: login, read/write config, read the ability map, reboot
  - video: claim the live monitor stream and de-frame it into Annex-B H.264/H.265

Wire format
-----------
Request/response header is 20 bytes, little-endian:

    struct  <BB2xII2BHI>
    offset  field
    0       0xff        magic
    1       0x00        version
    2..3    padding
    4..7    session id  (int32, echoed back after login)
    8..11   sequence    (int32, we increment per send)
    12      total pkts
    13      current pkt
    14..15  message id  (int16)
    16..19  data length (int32)

Body is the JSON payload followed by "\n\x00".

Media container (inside monitor-data messages)
----------------------------------------------
Each sub-packet starts with 00 00 01 <type>:

    type   meaning        header bytes   payload length field (LE)
    0xFC   video I-frame  16             header[12:16]
    0xFD   video P-frame  8              header[4:8]
    0xFA   audio          8              header[6:8]  (uint16)
    0xFE   info/extended  8              header[4:8]
    0xF9   info/extended  8              header[4:8]
    0xF8   info/extended  8              header[4:8]

The I-frame header also carries codec/fps/size:
    header[4]      codec   1=MPEG4  2=H.264  3=H.265
    header[5]      fps
    header[6]      width  / 8
    header[7]      height / 8
    header[8:12]   timestamp ms (LE)
    header[12:16]  payload length (LE)

Copy payload bytes verbatim. Never scan inside a payload for the next marker,
compressed video contains false 00 00 01 sequences. Use the length field to hop.

A fresh stream often starts mid-GOP (P-frames before the first I-frame). ffmpeg
logs "non-existing PPS 0 referenced / no frame!" until the first IDR arrives.
That is expected and harmless.
"""

from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
from typing import Callable, Optional

HEADER = struct.Struct("<BB2xII2BHI")

# message ids
MSG_LOGIN = 1000
MSG_KEEPALIVE = 1006
MSG_SYSINFO = 1020
MSG_CONFIG_SET = 1040
MSG_CONFIG_GET = 1042
MSG_ABILITY_GET = 1360
MSG_MONITOR_START = 1410
MSG_MONITOR_CLAIM = 1413
MSG_OPMACHINE = 1450
MSG_MONITOR_DATA = (1412, 1413, 1414, 1415)

CODEC_BY_ID = {1: "MPEG4", 2: "H.264", 3: "H.265"}
FFMPEG_FMT = {"H.264": "h264", "H.265": "hevc", "MPEG4": "m4v"}

# Ret codes seen in the field
RET_OK = 100
RET_OK_ALT = 515            # login: "user already logged in on another session" but usable
RET_UNKNOWN_NAME = 102      # CONFIG_GET on a name this firmware does not have


class SofiaError(Exception):
    pass


class SofiaAuthError(SofiaError):
    pass


class SofiaCamera:
    def __init__(self, host: str, user: str, password: str,
                 port: int = 34567, timeout: float = 10.0):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.session = 0
        self.seq = 0
        self.login_reply: dict = {}

    # -- connection ---------------------------------------------------------

    def connect(self) -> "SofiaCamera":
        self.sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock.settimeout(self.timeout)
        self.login()
        return self

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self) -> "SofiaCamera":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- framing ----------------------------------------------------------

    def _send(self, msgid: int, payload: dict) -> None:
        body = (json.dumps(payload) + "\n").encode("utf-8") + b"\x00"
        head = HEADER.pack(0xFF, 0x00, self.session, self.seq, 0, 0, msgid, len(body))
        self.sock.sendall(head + body)
        self.seq += 1

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise SofiaError("camera closed the connection")
            buf += chunk
        return bytes(buf)

    def _recv(self) -> tuple[int, bytes]:
        head = self._read_exact(HEADER.size)
        _, _, session, _seq, _tot, _cur, msgid, length = HEADER.unpack(head)
        self.session = session
        body = self._read_exact(length) if length else b""
        return msgid, body

    def _recv_json(self) -> dict:
        _, body = self._recv()
        text = body.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"_raw": text}

    def _call(self, msgid: int, payload: dict) -> dict:
        self._send(msgid, payload)
        return self._recv_json()

    def _sid(self) -> str:
        return "0x%08X" % self.session

    # -- control --------------------------------------------------------

    def login(self) -> dict:
        reply = self._call(MSG_LOGIN, {
            "EncryptType": "MD5",
            "LoginType": "DVRIP-Web",
            "UserName": self.user,
            "PassWord": xm_md5(self.password),
        })
        ret = reply.get("Ret")
        if ret not in (RET_OK, RET_OK_ALT):
            raise SofiaAuthError(f"login failed (Ret={ret}): {reply}")
        self.session = int(reply["SessionID"], 0)
        self.login_reply = reply
        return reply

    def keepalive(self) -> None:
        self._send(MSG_KEEPALIVE, {"Name": "KeepAlive", "SessionID": self._sid()})

    def system_info(self) -> dict:
        r = self._call(MSG_SYSINFO, {"Name": "SystemInfo", "SessionID": self._sid()})
        return r.get("SystemInfo", r)

    def get_config(self, name: str) -> dict:
        r = self._call(MSG_CONFIG_GET, {"Name": name, "SessionID": self._sid()})
        if r.get("Ret") == RET_UNKNOWN_NAME:
            raise SofiaError(f"config name not supported by this firmware: {name}")
        if r.get("Ret") not in (RET_OK, None):
            raise SofiaError(f"get_config {name} failed: {r}")
        return r.get(name, r)

    def set_config(self, name: str, value: dict) -> dict:
        r = self._call(MSG_CONFIG_SET, {
            "Name": name, "SessionID": self._sid(), name: value,
        })
        if r.get("Ret") != RET_OK:
            raise SofiaError(f"set_config {name} failed: {r}")
        return r

    def ability(self, name: str = "SystemFunction") -> dict:
        r = self._call(MSG_ABILITY_GET, {"Name": name, "SessionID": self._sid()})
        return r.get(name, r)

    def reboot(self) -> dict:
        """Reboot the camera. Callers must gate this behind explicit user consent."""
        return self._call(MSG_OPMACHINE, {
            "Name": "OPMachine", "SessionID": self._sid(),
            "OPMachine": {"Action": "Reboot", "Parameter": {"secDelay": 1}},
        })

    # -- probing helpers ------------------------------------------------

    def fingerprint(self) -> dict:
        """One dict summarising the camera. Every field is best-effort."""
        out: dict = {
            "host": self.host,
            "channels": self.login_reply.get("ChannelNum"),
            "device_type": str(self.login_reply.get("DeviceType ", "")).strip() or None,
        }
        try:
            si = self.system_info()
            out["hardware"] = si.get("HardWare")
            out["software_version"] = si.get("SoftWareVersion")
            out["build_time"] = si.get("BuildTime")
            out["serial"] = si.get("SerialNo")
        except SofiaError:
            pass
        try:
            nc = self.get_config("NetWork.NetCommon")
            out["mac"] = nc.get("MAC")
            out["http_port"] = nc.get("HttpPort")
            out["tcp_port"] = nc.get("TCPPort")
        except SofiaError:
            pass
        try:
            enc = self.get_config("Simplify.Encode")
            if isinstance(enc, list) and enc:
                main = enc[0].get("MainFormat", {}).get("Video", {})
                extra = enc[0].get("ExtraFormat", {}).get("Video", {})
                out["encode_main"] = _sum_video(main)
                out["encode_sub"] = _sum_video(extra)
        except SofiaError:
            pass
        try:
            fn = self.ability("SystemFunction")
            net = fn.get("NetServerFunction", {}) if isinstance(fn, dict) else {}
            other = fn.get("OtherFunction", {}) if isinstance(fn, dict) else {}
            out["ability_has_rtsp"] = bool(
                net.get("NetRTSP") or other.get("SupportRTSP")
            )
            out["ability_has_onvif"] = bool(
                net.get("NetOnvif") or other.get("SupportONVIF")
            )
            out["ability_h265x"] = bool(other.get("SupportShowH265X"))
        except SofiaError:
            pass
        return out

    # -- video --------------------------------------------------------

    def _monitor_params(self, channel: int, substream: bool) -> dict:
        return {
            "Channel": channel,
            "CombinMode": "NONE",
            "StreamType": "Extra" if substream else "Main",
            "TransMode": "TCP",
        }

    def start_monitor(self, channel: int = 0, substream: bool = False) -> None:
        params = self._monitor_params(channel, substream)
        self._send(MSG_MONITOR_CLAIM, {
            "Name": "OPMonitor", "SessionID": self._sid(),
            "OPMonitor": {"Action": "Claim", "Parameter": params},
        })
        self._recv()  # claim reply
        self._send(MSG_MONITOR_START, {
            "Name": "OPMonitor", "SessionID": self._sid(),
            "OPMonitor": {"Action": "Start", "Parameter": params},
        })

    def stream_elementary(
        self,
        write: Callable[[bytes], None],
        channel: int = 0,
        substream: bool = False,
        duration: float = 0.0,
        keepalive: float = 20.0,
        on_meta: Optional[Callable[[dict], None]] = None,
    ) -> int:
        """
        Pull the live monitor stream, de-frame it, hand Annex-B bytes to write().
        Returns total elementary bytes written. Runs until duration (0 = forever)
        or the socket drops (raises SofiaError, let the caller reconnect).
        """
        self.start_monitor(channel, substream)
        buf = bytearray()
        total = 0
        started = time.time()
        last_ka = started
        meta_sent = False

        def sink(payload: bytes) -> None:
            nonlocal total
            total += len(payload)
            write(payload)

        while True:
            if duration and time.time() - started >= duration:
                return total
            if time.time() - last_ka > keepalive:
                self.keepalive()
                last_ka = time.time()
            msgid, body = self._recv()
            if msgid not in MSG_MONITOR_DATA:
                continue
            buf += body
            if on_meta is not None and not meta_sent:
                meta = _peek_iframe_meta(buf)
                if meta:
                    on_meta(meta)
                    meta_sent = True
            used = deframe(buf, sink)
            del buf[:used]


# -- module functions ---------------------------------------------------

def xm_md5(password: str) -> str:
    """Xiongmai's 8-char password hash: md5, then fold each byte pair into base62."""
    digest = hashlib.md5(password.encode("utf-8")).digest()
    out = []
    for i in range(8):
        n = (digest[2 * i] + digest[2 * i + 1]) % 62
        if n < 10:
            out.append(chr(ord("0") + n))
        elif n < 36:
            out.append(chr(ord("A") + n - 10))
        else:
            out.append(chr(ord("a") + n - 36))
    return "".join(out)


def deframe(buf: bytearray, write: Callable[[bytes], None]) -> int:
    """
    Consume whole media sub-packets from buf, pass video payloads to write().
    Returns the number of bytes consumed (caller trims the buffer by that much).
    Leaves a trailing partial packet in place for the next call.
    """
    i = 0
    n = len(buf)
    while n - i >= 8:
        if buf[i] != 0x00 or buf[i + 1] != 0x00 or buf[i + 2] != 0x01:
            i += 1
            continue
        t = buf[i + 3]
        if t == 0xFC:                       # video I-frame
            if n - i < 16:
                break
            length = int.from_bytes(buf[i + 12:i + 16], "little")
            hdr = 16
        elif t == 0xFD:                     # video P-frame
            length = int.from_bytes(buf[i + 4:i + 8], "little")
            hdr = 8
        elif t == 0xFA:                     # audio
            length = int.from_bytes(buf[i + 6:i + 8], "little")
            hdr = 8
        elif t in (0xFE, 0xF9, 0xF8):       # info / extended
            length = int.from_bytes(buf[i + 4:i + 8], "little")
            hdr = 8
        else:
            i += 1
            continue
        if n - i < hdr + length:
            break                          # rest of this packet has not arrived
        if t in (0xFC, 0xFD):
            write(bytes(buf[i + hdr:i + hdr + length]))
        i += hdr + length
    return i


def _peek_iframe_meta(buf: bytes) -> Optional[dict]:
    """Find the first I-frame header in buf and read codec/fps/size from it."""
    idx = buf.find(b"\x00\x00\x01\xfc")
    if idx < 0 or len(buf) < idx + 16:
        return None
    h = buf[idx:idx + 16]
    return {
        "codec": CODEC_BY_ID.get(h[4], f"unknown(0x{h[4]:02x})"),
        "codec_id": h[4],
        "fps": h[5],
        "width": h[6] * 8,
        "height": h[7] * 8,
    }


def _sum_video(v: dict) -> Optional[str]:
    if not v:
        return None
    return "{res} {codec} {rc} {br}kbps {fps}fps".format(
        res=v.get("Resolution", "?"),
        codec=v.get("Compression", "?"),
        rc=v.get("BitRateControl", "?"),
        br=v.get("BitRate", "?"),
        fps=v.get("FPS", "?"),
    )


def port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False
