---
name: sofia-cam
description: Connect to, fingerprint, configure, and pull video from Xiongmai / Sofia / DVRIP IP cameras over TCP 34567 (the protocol behind XMEye and iCSee). Use when a camera has no working RTSP or ONVIF, when you need firmware / codec / encode details off a cheap white-label camera, or when bridging one into go2rtc / ffmpeg / Frigate.
---

# sofia-cam

Talk to Xiongmai OEM cameras and DVRs on their proprietary port 34567 protocol
("Sofia" / "DVRIP" / "NetSurveillance"). Many recent white-label cameras ship
with RTSP and ONVIF removed, so this is the only way to read their config or
get their video on the LAN.

Wire protocol reference: [PROTOCOL.md](PROTOCOL.md). Repo overview:
[README.md](README.md).

## When to use

- A camera answers on 34567 but not 554 / 8899, or the app has no RTSP toggle.
- You need model, firmware, serial, codec, or encode settings and the camera
  has no web UI.
- You want the live stream in ffmpeg, go2rtc, or Frigate and go2rtc's native
  `dvrip://` source fails (it panics with `unexpected end of JSON input` on the
  `000999WP` firmware branch).
- You need to check or change one config value the app does not expose.

## Safety rules

Read paths never change the camera: `discover`, `info`, `get`, `stream`,
`probe`. Run those freely.

Write paths change or interrupt the camera: `set`, `reboot`. Do not run them
without the owner saying so in the current conversation. A camera reboot is
audible and interrupts recording. This is the
[[feedback_notify_before_device_actions]] rule: state exactly what you want to
do and why, wait for a yes.

`sofia-cam set` prompts for confirmation and prints a before / after diff unless
`--yes` is passed. `sofia-cam reboot` refuses unless
`--i-understand-this-reboots` is passed.

## Credentials

Per-camera username and password. Pass them as CLI args for one-off use. For
anything persistent (a bridge service), read them from the environment or a
file the repo ignores, never commit them. The camera hash (`xm_md5`) is applied
by the client; give it the plain password.

## Setup

Standard library only, Python 3.9+. No install step. `ffmpeg` / `ffprobe`
needed only for the decode / verify examples.

```
git clone <repo> && cd <repo>
./sofia-cam --help
```

## Fingerprint a camera

```
./sofia-cam info 192.168.1.88 <user> <pass>
```

Returns model (`HardWare`), firmware (`SoftWareVersion`), serial, main and sub
encode settings, the ability flags for RTSP / ONVIF / H265X, and a live
codec / resolution / fps read taken from the first I-frame of the stream.

Scan a subnet for cameras:

```
./sofia-cam discover 192.168.1.0/24 --user <user> --pass <pass>
```

Prints one JSON row per host with 34567 open, including whether that credential
logs in.

Check whether standard ports are actually live (not just configured):

```
./sofia-cam probe 192.168.1.88
```

## Read or change config

```
./sofia-cam get 192.168.1.88 <user> <pass> Simplify.Encode
./sofia-cam get 192.168.1.88 <user> <pass> NetWork.NetCommon
```

Config node names and shapes are in [PROTOCOL.md](PROTOCOL.md). A name the
firmware does not implement returns a clean `config name not supported` error
(protocol Ret 102).

Writing (gated, ask first):

```
./sofia-cam set 192.168.1.88 <user> <pass> NetWork.NetRTSP '{"Enable":true,"Port":554,"Session":2,"AuthorizeMode":0}'
```

On the `000999WP` firmware this write is accepted and persists across reboot but
starts no RTSP daemon. It does not give you a working `rtsp://` URL. Do not
expect config changes to unlock RTSP or ONVIF on that firmware; use the stream
bridge instead.

## Get the video into ffmpeg / go2rtc

`sofia-cam stream` writes a clean Annex-B elementary stream to stdout and
reconnects on drop.

Grab a still to eyeball a camera:

```
./sofia-cam stream 192.168.1.236 <user> <pass> --duration 8 --once \
  | ffmpeg -f h264 -i - -ss 3 -update 1 -frames:v 1 out.jpg
```

Use `-f hevc` instead of `-f h264` for an H.265 camera. `sofia-cam info` and the
`stream` stderr line both tell you which.

Republish as RTSP for other consumers:

```
./sofia-cam stream 192.168.1.236 <user> <pass> \
  | ffmpeg -use_wallclock_as_timestamps 1 -f h264 -i - -c copy \
           -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam2
```

`-c copy` throughout, no transcoding. `-use_wallclock_as_timestamps 1` matters:
the XM stream carries no timestamps and downstream recorders stutter without it.

go2rtc source using an `exec` producer, one line in `go2rtc.yaml`:

```yaml
streams:
  cam2:
    - "exec:sh -c '/path/to/sofia-cam stream 192.168.1.236 USER PASS | ffmpeg -use_wallclock_as_timestamps 1 -f h264 -i - -c copy -rtsp_transport tcp -f rtsp {output}'"
```

See [examples/go2rtc.yaml](examples/go2rtc.yaml) for a fuller version with the
sub-stream and an H.265 camera.

## Known per-camera facts (this network)

| Camera | Model | Firmware | Main | Sub |
|--------|-------|----------|------|-----|
| 192.168.1.88  | IPC_XM210_X2-WR-T_S38 | V5.08.R02.000999WP | H.264 1080P 10fps | QVGA H.264 |
| 192.168.1.236 | IPC_XM210_X2-WR-T_S38 | V5.08.R02.000999WP | H.264 1080P 10fps | QVGA H.264 |
| 192.168.1.47  | XM530V200_X2C-WQ_8M   | V5.00.R02.000807B4 | H.265 1080P 12fps | D1 H.265 |

All three: only port 34567 open, no RTSP, no ONVIF.

## Gotchas

- The camera password uses `xm_md5`, not a plain MD5. The client handles it.
- The login reply key is `"DeviceType "` with a trailing space.
- Address fields are byte-reversed little-endian hex (`0x0A01A8C0` = 192.168.1.10).
- A camera holds only a few sessions. Sharing 34567 with the phone app on live
  view can drop your stream; `sofia-cam stream` reconnects with backoff.
- Keep the keepalive going or the camera cuts the stream after ~30 s.
- The stream starts mid-GOP; ignore `non-existing PPS 0` until the first
  I-frame.
