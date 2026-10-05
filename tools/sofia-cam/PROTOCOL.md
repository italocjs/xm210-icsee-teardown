# Sofia / DVRIP wire protocol

Reverse-engineered notes for the TCP port 34567 protocol used by Xiongmai OEM
cameras and DVRs, and by the XMEye / iCSee apps. Also called "Sofia",
"NetSurveillance", or "dvrip". Enough here to write a client from scratch.

Everything below is confirmed against three live cameras (two `IPC_XM210_X2-WR-T_S38`
running `V5.08.R02.000999WP`, one `XM530V200_X2C-WQ_8M` running `V5.00.R02.000807B4`).

## Transport

- Plain TCP, default port 34567 (`TCPPort` in `NetWork.NetCommon`).
- One request, one or more responses, same socket.
- The camera drops an idle session after roughly 30 s. Send a keepalive
  (msg 1006) every 20 s to hold a monitor stream open.
- A camera accepts only a few concurrent sessions. The XMEye cloud link, the
  phone app on live view, and your client all count. Expect drops under
  contention and reconnect.

## Packet header (20 bytes, little-endian)

```
struct  <BB2xII2BHI>

offset  size  field         notes
0       1     0xff          magic
1       1     0x00          version
2       2     --            padding (zero)
4       4     session id    0 until login, then echo the value the camera returns
8       4     sequence      client increments by 1 per send; camera echoes
12      1     total packets usually 0
13      1     current pkt   usually 0
14      2     message id    see table
16      4     data length   length of the body that follows
```

Body: the JSON object, UTF-8, followed by `"\n\x00"` (newline then a NUL). When
reading, split on the first `\x00` and parse what precedes it.

Numeric fields that are conceptually addresses or masks come back as
little-endian hex strings, e.g. `"HostIP": "0x0A01A8C0"` is `10.1.168.192`
byte-reversed, i.e. `192.168.1.10`.

## Message IDs

| ID   | Name            | Direction | Purpose                                  |
|------|-----------------|-----------|------------------------------------------|
| 1000 | LOGIN_REQ2      | c -> s    | authenticate                             |
| 1001 | LOGIN_RSP       | s -> c    | login reply                              |
| 1006 | KEEPALIVE_REQ   | c -> s    | session keepalive                        |
| 1020 | SYSINFO_REQ     | c -> s    | `{"Name":"SystemInfo"}` -> hw / fw / serial |
| 1040 | CONFIG_SET      | c -> s    | write one config node                    |
| 1042 | CONFIG_GET      | c -> s    | read one config node                     |
| 1360 | ABILITY_GET     | c -> s    | `{"Name":"SystemFunction"}` capability map |
| 1410 | MONITOR_REQ     | c -> s    | OPMonitor `Start`                        |
| 1412 | MONITOR_DATA    | s -> c    | media payload                            |
| 1413 | MONITOR_CLAIM   | c -> s    | OPMonitor `Claim` (also seen as data id) |
| 1414 | MONITOR_DATA    | s -> c    | media payload                            |
| 1415 | MONITOR_DATA    | s -> c    | media payload                            |
| 1450 | SYSMANAGER_REQ  | c -> s    | OPMachine, e.g. `Reboot`                 |

Media arrives on ids 1412 / 1413 / 1414 / 1415 depending on firmware, so treat
all four as "monitor data".

## Login

Request:

```json
{"EncryptType":"MD5","LoginType":"DVRIP-Web","UserName":"admin","PassWord":"<hash>"}
```

`PassWord` is Xiongmai's own 8-character hash, not a normal MD5:

```python
import hashlib
def xm_md5(password: str) -> str:
    d = hashlib.md5(password.encode()).digest()
    out = []
    for i in range(8):
        n = (d[2*i] + d[2*i+1]) % 62
        if   n < 10: out.append(chr(ord('0') + n))
        elif n < 36: out.append(chr(ord('A') + n - 10))
        else:        out.append(chr(ord('a') + n - 36))
    return "".join(out)
# xm_md5("password123") -> "sY6ww5dO"
# xm_md5("")            -> "tlJwpbo6"   (blank password)
```

Reply:

```json
{"SessionID":"0x00000046","AliveInterval":30,"ChannelNum":1,
 "DeviceType ":"IPC","Ret":100,"AdminToken":"..."}
```

Note the trailing space in `"DeviceType "`, it is really in the JSON key.
Parse `SessionID` with `int(x, 0)` and put it in the header of every later
request. Also send it inside the body as `"SessionID":"0x%08X"`.

## Ret codes

| Ret | Meaning                                                        |
|-----|--------------------------------------------------------------- |
| 100 | OK                                                            |
| 102 | OK-ish / unknown config name. `CONFIG_GET` on a `Name` this firmware does not implement returns `{"Ret":102}` with no data. Treat as "not supported". |
| 106 | wrong user or password                                        |
| 515 | already logged in elsewhere; the session is still usable      |

## CONFIG_GET (1042)

Request: `{"Name":"NetWork.NetCommon","SessionID":"0x00000046"}`

Reply echoes `Name` and nests the data under the same key:

```json
{"Ret":100,"Name":"NetWork.NetCommon","SessionID":"0x00000046",
 "NetWork.NetCommon":{
   "GateWay":"0x0101A8C0","HostIP":"0x0A01A8C0","HostName":"LocalHost",
   "HttpPort":80,"MAC":"00:11:22:33:44:55","MonMode":"TCP","SSLPort":8443,
   "Submask":"0x00FFFFFF","TCPMaxConn":10,"TCPPort":34567,
   "TransferPlan":"Quality","UDPPort":34568,"UseHSDownLoad":false}}
```

### Config nodes seen

| Name                     | Contents |
|--------------------------|----------|
| `NetWork.NetCommon`      | IP, gateway, mask, MAC, HTTP/TCP/UDP/SSL ports |
| `NetWork.NetDHCP`        | per-interface DHCP enable (`eth0`..`eth3`) |
| `NetWork.NetDNS`         | primary / spare DNS as hex |
| `NetWork.NetIPFilter`    | allow / deny lists |
| `NetWork.NetRTSP`        | `{"Enable":bool,"Port":554,"Session":2,"AuthorizeMode":0}` — **absent on the 999WP firmware**, `CONFIG_GET` returns Ret 102. `CONFIG_SET` is accepted and persists but no RTSP daemon starts, so it has no effect. |
| `NetWork.OnVif`          | `{"Enable":bool,"Port":8899,"PwdCheck":bool}` — same story, inert on 999WP |
| `Simplify.Encode`        | list, one per channel, with `MainFormat` and `ExtraFormat` (see below) |
| `General`                | machine name, auto-reboot schedule, locale, DST |
| `Detect.MotionDetect`    | list, one per channel; regions, sensitivity, event handlers |
| `Uart.PTZ`               | PTZ serial config, protocol name |

`General.System` and several `OPTimeQuery`-style names return Ret 102 on the
999WP build. Do not rely on them; use `SYSINFO_REQ` (1020) for hw / fw / serial.

### Simplify.Encode shape

```json
[{"MainFormat":{"Video":{"Compression":"H.264","Resolution":"1080P","FPS":10,
   "BitRate":1024,"BitRateControl":"VBR","GOP":4,"Quality":3},
   "AudioEnable":true,"VideoEnable":true},
  "ExtraFormat":{"Video":{"Compression":"H.264","Resolution":"QVGA","FPS":10,
   "BitRate":512,"BitRateControl":"VBR"},"AudioEnable":true,"VideoEnable":true}}]
```

`Compression` is `"H.264"` or `"H.265"`. `Resolution` is a label
(`1080P`, `720P`, `D1`, `QVGA`, ...). This is where you learn the sub-stream
size before pulling it.

## SYSINFO_REQ (1020)

Request: `{"Name":"SystemInfo","SessionID":"..."}`

```json
{"SystemInfo":{
  "HardWare":"IPC_XM210_X2-WR-T_S38","HardWareVersion":"1.0",
  "SoftWareVersion":"V5.08.R02.000999WP.00000.140f24.0000000",
  "BuildTime":"2026-04-23 14:51:13","SerialNo":"0000000000000000000a",
  "Pid":"A9A056383235C00S","VideoInChannel":1,"AudioInChannel":1,
  "ExtraChannel":0,"DeviceRunTime":"0x0000047f"}}
```

## ABILITY_GET (1360)

Request: `{"Name":"SystemFunction","SessionID":"..."}`. Returns a nested map of
booleans grouped under `AlarmFunction`, `CommFunction`, `EncodeFunction`,
`NetServerFunction`, `OtherFunction`, `PreviewFunction`, `TipShow`.

Useful keys:

| Path                                        | On the 999WP cams |
|---------------------------------------------|-------------------|
| `NetServerFunction.NetDHCP` / `.NetDNS` / `.NetNTP` / `.NetIPFilter` | true |
| `NetServerFunction.NetRTSP`  (only some firmwares expose this key)   | absent |
| `OtherFunction.SupportShowH265X`            | true |
| `EncodeFunction.DoubleStream`               | true |
| `EncodeFunction.SnapStream`                 | true |

There is no `RTSP` or `ONVIF` entry in the ability map on the 999WP build. That
is the firmware telling you those services do not exist, not just that they are
switched off.

## OPMonitor: pulling live video

1. `MONITOR_CLAIM` (1413):

```json
{"Name":"OPMonitor","SessionID":"0x...",
 "OPMonitor":{"Action":"Claim","Parameter":{
   "Channel":0,"CombinMode":"NONE","StreamType":"Main","TransMode":"TCP"}}}
```

Read one reply (`{"Name":"OPMonitor","Ret":100,...}`).

2. `MONITOR_REQ` (1410): same body, `"Action":"Start"`.

3. The camera now pushes media on ids 1412 / 1414 / 1415. Keep sending
   keepalives. `StreamType` is `"Main"` or `"Extra"` (the sub-stream).

To stop cleanly, send `"Action":"Stop"` or just close the socket.

## Media container

Each monitor-data body is a run of sub-packets. A sub-packet starts with the
3-byte start code `00 00 01` followed by a type byte:

| Type | Meaning       | Header bytes | Payload length field |
|------|---------------|--------------|----------------------|
| 0xFC | video I-frame | 16           | header[12:16] LE     |
| 0xFD | video P-frame | 8            | header[4:8]  LE      |
| 0xFA | audio         | 8            | header[6:8]  LE (uint16) |
| 0xFE | info / extended | 8          | header[4:8]  LE      |
| 0xF9 | info / extended | 8          | header[4:8]  LE      |
| 0xF8 | info / extended | 8          | header[4:8]  LE      |

The I-frame header carries stream parameters:

```
header[0:4]    00 00 01 FC
header[4]      codec:  1 = MPEG4, 2 = H.264, 3 = H.265
header[5]      fps
header[6]      width  / 8
header[7]      height / 8
header[8:12]   timestamp, milliseconds, LE
header[12:16]  payload length, LE
```

Example real I-frame header: `00 00 01 fc 02 0a f0 87 07 56 43 6a db d4 00 00`
-> codec 2 (H.264), 10 fps, 0xf0*8 = 1920 wide, 0x87*8 = 1080 high,
payload length 0x0000d4db = 54491 bytes.

### De-framing rules

- The payload of a video packet is raw Annex-B: `00 00 00 01 67 ...` (H.264
  SPS) or `00 00 00 01 40 01 ...` (H.265 VPS). Copy it out byte for byte.
- Use the length field to jump to the next packet. Never scan the payload for
  the next `00 00 01`; compressed video is full of false start codes.
- A packet can be split across two monitor-data messages. Buffer, parse whole
  packets, keep the trailing partial for the next read.
- The stream usually begins mid-GOP: several P-frames before the first I-frame.
  A decoder logs `non-existing PPS 0 referenced` / `no frame!` until the first
  I-frame arrives. Expected, not an error.
- Concatenate the video payloads and you have a valid elementary stream that
  `ffmpeg -f h264` (or `-f hevc`) reads directly.

## OPMachine: reboot (1450)

```json
{"Name":"OPMachine","SessionID":"0x...",
 "OPMachine":{"Action":"Reboot","Parameter":{"secDelay":1}}}
```

The socket closes as the camera goes down. It is back on port 34567 in about
20 to 40 s. Other `Action` values exist (`Shutdown`, factory reset); not
covered here on purpose.

## The 999WP lockdown, in one paragraph

Firmware `V5.08.R02.000999WP` on the `IPC_XM210` board ships without an RTSP
server and without a working ONVIF service. The config keys can be created and
they survive a reboot, but nothing binds port 554 or 8899. A full 1-65535 TCP
scan of such a camera shows only port 34567 open. The `SupportShowH265X`
ability flag is set on this firmware family; some units in it still encode plain
H.264 (confirmed on two `S38` units), so check the actual stream rather than
trusting the flag. The only way to get video off these cameras on the LAN is
the OPMonitor path above.
