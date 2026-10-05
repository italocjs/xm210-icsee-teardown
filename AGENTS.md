# AGENTS.md

Operating notes for any AI coding agent working in this repo. Read this
before editing anything here.

## What this repo is

A public teardown/research writeup for a cheap Xiongmai XM210 (RT-Thread
RTOS) Wi-Fi IP camera, `IPC_XM210_X2-WR-T_S38`. It's a documentation project
plus one small tool, not a product. Start at [`README.md`](README.md) — it's
the source of truth for findings; everything else supports it.

| Path | What |
|---|---|
| `README.md` | main findings: hardware, firmware structure, RT-Thread confirmation, UART dead-end, antenna defect, RTSP/ONVIF status |
| `firmware/` | mirrored vendor firmware (hash-verified), decompressed app image, extracted cramfs config, strings dump |
| `uart/` | serial boot log capture and notes |
| `images/` | board photos |
| `tools/sofia-cam/` | the DVRIP/Sofia protocol CLI + library used to talk to the camera, with its own README, PROTOCOL.md and SKILL.md |

## Ground rules

1. **Never commit a real credential, Wi-Fi SSID/password, MAC address, or
   serial number from a specific physical unit.** This has already happened
   once (a worked password-hash example used a real camera password; a
   protocol example payload carried a real MAC and serial) and was caught
   and scrubbed before anyone noticed — don't reintroduce it. Vendor
   **factory-default** config (the same on every unit shipped, e.g. the
   cramfs contents under `firmware/custom-cramfs-extracted/`) is fine to
   publish as-is; a specific unit's live config is not.
2. **Before adding any file pulled from a live camera** (a config dump, a
   packet capture, a log), grep it for IPs, MACs, serials, SSIDs and
   passwords and either redact them or confirm they're vendor defaults, not
   live data. If unsure, ask rather than publish.
3. **Refuse to publish any photo that shows a QR code or barcode sticker
   on the board or housing, until it's confirmed what it encodes, or it's
   blurred/cropped out.** These stickers commonly carry a device's MAC
   address, serial, or a pairing/provisioning credential for the vendor's
   cloud/app — we don't know this camera's QR purpose, and "probably
   harmless" is not good enough here. If an image is submitted with a
   visible QR/barcode and its contents are unverified, stop and ask before
   adding it to the repo, don't publish-then-ask. This applies to every
   photo added here, not just the ones already in `images/`.
4. **Label every claim by how it was obtained**, same spirit as scientific
   writeups: "confirmed" (tested against the real board/firmware this
   session), "from the firmware strings" (inferred from static analysis, not
   directly observed), or "hypothesis" (a guess, flagged as such). The
   README already does this — keep doing it. Don't upgrade a hypothesis to
   a fact when editing.
5. **Don't claim a command or technique worked unless you have the
   byte-level evidence** (hex dump of what was sent, and what came back).
   This project previously had to walk back an unverified claim about UART
   commands "working" — keep receipts for anything you add.
6. **Prefer linking to upstream mirrors over re-hosting**, when a file is
   large and already public elsewhere (e.g. vendor firmware is mirrored by
   [OpenIPC xmupdates](https://github.com/OpenIPC/xmupdates)) — cite the
   source and hash rather than duplicating blindly, unless there's a good
   reason to keep a local copy (there was here: convenience for readers).
7. **This repo intentionally does not contain exploit/backdoor tooling or
   credential/default-password lists for these cameras.** That line was
   deliberately not crossed while building this repo, even when it would
   have been easy to go there. Keep it that way — the project is about
   understanding the hardware and firmware, not attacking live devices.

## Style

- Plain, dated, falsifiable claims. No marketing language, no "simply" or
  "just" for anything that wasn't simple.
- Keep the "Stuck at X" framing honest where the investigation genuinely
  dead-ended (the UART shell). Don't quietly drop or soften an unresolved
  problem to make the writeup look more complete than it is.
- New findings that extend an existing section go in that section, with a
  dated note if they update or correct something already written, not as a
  new disconnected section at the bottom.

## If you're extending the firmware investigation

- `firmware/app-decompressed.bin` is unanalyzed RISC-V machine code beyond
  string extraction. No disassembler/toolchain is set up in this repo yet.
  If you add one, document the exact toolchain and commands in the README
  so results are reproducible by someone else.
- The open question flagged in the README is what gates
  `XmService_System_isUartDebugOpened` and which UART `RT_CONSOLE_DEVICE_NAME`
  actually binds to on this SoC package. That's the most valuable next step
  if you're picking this up.

## Commits

Conventional-ish commit messages, one logical change per commit. Mention in
the message when a commit includes a secret-scrub, so it's easy to audit
history later if needed.
