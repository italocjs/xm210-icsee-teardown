# sofia-cam

A small, dependency-free client for Xiongmai OEM IP cameras and DVRs that speak
the proprietary port 34567 protocol, known as **Sofia**, **DVRIP**, or
**NetSurveillance**. This is the protocol behind the XMEye and iCSee apps.

This is the tool used throughout the rest of this repo to talk to the
[`IPC_XM210_X2-WR-T_S38`](../../README.md) camera — fingerprinting it, reading
its config (read-only), and grabbing a snapshot to confirm which physical
unit was being tested. Everything it does over the network is the same
protocol XMEye/iCSee themselves use; it just lets you do it from a terminal
instead of the app.

Recent white-label cameras (firmware family `V5.08.R02.000999WP` and similar)
ship with RTSP and ONVIF stripped out. Port 34567 is then the only way to read
the camera's config or pull its video on the local network. `sofia-cam` does
both.

- Fingerprint a camera: model, firmware, serial, codec, encode settings.
- Scan a subnet for cameras.
- Read and write config nodes.
- Pull the live H.264 / H.265 stream as a clean elementary stream for ffmpeg,
  go2rtc, or Frigate.

Standard library only, Python 3.9+. `ffmpeg` is optional, used by the decode
examples.

## Install

```
git clone https://github.com/italocjs/xm210-icsee-teardown
cd xm210-icsee-teardown/tools/sofia-cam
./sofia-cam --help
```

## Examples

Fingerprint (IP, username and password below are placeholders — use your own
camera's address and credentials):

```
$ ./sofia-cam info 192.168.1.88 admin yourpassword
{
  "hardware": "IPC_XM210_X2-WR-T_S38",
  "software_version": "V5.08.R02.000999WP.00000.140f24.0000000",
  "encode_main": "1080P H.264 VBR 1024kbps 10fps",
  "encode_sub": "QVGA H.264 VBR 512kbps 10fps",
  "ability_has_rtsp": false,
  "live_stream": {"codec": "H.264", "width": 1920, "height": 1080, "fps": 10}
}
```

Discover:

```
$ ./sofia-cam discover 192.168.1.0/24 --user admin --pass yourpassword
{"host": "192.168.1.88", "port_34567": true, "login": "ok", ...}
```

Read a config node:

```
$ ./sofia-cam get 192.168.1.88 admin yourpassword Simplify.Encode
```

Grab a still:

```
$ ./sofia-cam stream 192.168.1.88 admin yourpassword --duration 8 --once \
    | ffmpeg -f h264 -i - -update 1 -frames:v 1 snap.jpg
```

Republish as RTSP (no transcoding):

```
$ ./sofia-cam stream 192.168.1.88 admin yourpassword \
    | ffmpeg -use_wallclock_as_timestamps 1 -f h264 -i - -c copy \
             -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/cam1
```

## Files

| File | What |
|------|------|
| `sofia_client.py` | the library: protocol, de-framer, `SofiaCamera` class |
| `sofia-cam` | the CLI |
| `PROTOCOL.md` | full wire protocol reference, written from packet captures |
| `SKILL.md` | playbook for using this as an agent/LLM-assistant skill |
| `examples/go2rtc.yaml` | go2rtc source config for H.264 and H.265 cameras |

## Safety

`discover`, `info`, `get`, `stream`, `probe` are read-only.

`set` changes camera config and prompts before writing. `reboot` refuses
without `--i-understand-this-reboots`. A reboot interrupts recording and is
audible; only run write commands against a camera you own or have explicit
permission to configure.

## Scope and limits

Tested against `IPC_XM210_X2-WR-T_S38` (H.264) and `XM530V200_X2C-WQ_8M`
(H.265) cameras. Other Xiongmai devices use the same protocol but may expose
different config nodes and message quirks. DVRs report multiple channels; the
CLI defaults to channel 0.

On `000999WP` firmware, writing `NetWork.NetRTSP` or `NetWork.OnVif` is accepted
but starts no service. That firmware has no RTSP or ONVIF binary. Use the stream
bridge instead.

## License

MIT, same as the rest of this repo — see [../../LICENSE](../../LICENSE).

## Credit

Protocol details build on prior community work on the Xiongmai / Sofia protocol
(python-dvr and others). This client was written fresh from packet captures and
does not vendor any of that code.
