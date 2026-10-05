# UART capture notes

Pads: 3 unpopulated through-hole points near the main SoC, no silkscreen
label. Identified by continuity (GND) and voltage behavior during boot
(TX wobbles 0-3.3V while printing, RX sits flat).

Adapter: generic CH340/CP2102-class 3.3V USB-serial adapter.
Settings: 115200 baud, 8 data bits, no parity, 1 stop bit, no flow control.

`boot-log.txt` in this folder is the exact, byte-identical capture obtained
on every power-on and every `reboot` command sent back over the same link —
confirmed reproducible across multiple captures with hex-level comparison,
not just eyeballed.

See the main README's "UART findings" section for what commands were tried
beyond `reboot` and why we believe the real RT-Thread shell is bound to a
different UART than the one exposed on this board.
