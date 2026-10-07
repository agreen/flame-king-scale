# Flame King YSNPS1 Bluetooth protocol notes

Everything here is either implemented and tested in this repository
(`protocol.py`, `tests/test_protocol.py`) or comes from the official app's
conversion as reproduced in `const.py`. Items we have not verified are listed
separately at the end rather than guessed at.

## Device

| Item | Value |
| --- | --- |
| Model | Flame King YSNPS1 (stock electronics, no modification) |
| Advertised local name | `Gas Monitor` (exact match, case-insensitive) |
| Radio | Bluetooth Low Energy, connectable |
| Connections | One central at a time; close the official app / nRF Connect first |

Some firmware omits service UUIDs from its advertisement. Discovery therefore
accepts the exact name alone, but if services *are* advertised, `FFE0` must be
among them (`discovery.py`). On connect the integration requires both the
service and the notification characteristic below before it trusts any data.

## GATT

| Item | UUID |
| --- | --- |
| Service | `0000ffe0-0000-1000-8000-00805f9b34fb` (`FFE0`) |
| Notify characteristic | `0000ffe4-0000-1000-8000-00805f9b34fb` (`FFE4`) |

The integration only enables notifications on `FFE4` (a write to its standard
CCCD descriptor). It never writes the proprietary `FFE9` characteristic, and
neither does the capture tool in `monitor/`.

## Notification packet

Six bytes, sent by the scale as `FFE4` notifications while connected:

```text
offset  0    1    2    3    4    5
        AA   01   LL   HH   BB   CC
```

| Offset | Meaning |
| --- | --- |
| 0 | Header `0xAA` |
| 1 | Packet type / version `0x01` |
| 2–3 | Raw load-cell reading, unsigned 16-bit little-endian (`LL` low, `HH` high) |
| 4 | Battery percentage (0–100) |
| 5 | Checksum: XOR of bytes 0–4 |

A packet is rejected unless it is exactly six bytes, begins `AA 01`, and the
checksum matches. Rejected packets are logged at debug level and ignored.

Worked examples (both are in the test suite):

| Packet | Raw | Battery | Checksum check |
| --- | --- | --- | --- |
| `AA 01 00 00 64 CF` | 0 | 100 % | `AA^01^00^00^64 = CF` |
| `AA 01 3A 08 64 FD` | `0x083A` = 2106 | 100 % | `AA^01^3A^08^64 = FD` |

## Converting raw readings to weight

The official app converts raw counts to kilograms as:

```text
gross_kg = (raw - 64) / 256
```

so one count is 1/256 kg (about 0.0039 kg, or 0.0086 lb) and raw 1600 is
exactly 6 kg. The integration stores this as a two-point line
(`raw_zero = 64`, `raw_reference = 1600`, `reference_weight = 6 kg =
13.2277 lb`) so that guided calibration can replace it:

```text
gross_lb    = max(0, (raw - raw_zero) × reference_weight_lb / (raw_reference - raw_zero))
propane_lb  = max(0, gross_lb - tare_lb)
percent     = clamp(propane_lb / capacity_lb × 100, 0, 100)
```

### The raw-zero quirk

With nothing on the platform the firmware can report a literal raw `0`, even
though the factory line extrapolates to zero weight at raw `64`. Evaluated
naively that gives about −0.55 lb. The integration clips gross weight at zero
and keeps the unmodified raw value in the diagnostic *Raw scale reading* entity.
Guided calibration treats the unloaded capture as a no-load sentinel and fits
the line from two *loaded* measurements only
(`calibration_from_loaded_points`).

## Connection behaviour used by the integration

This is the integration's policy, not something the scale dictates.

1. Every *regular reading interval* (default 60 min) connect, subscribe, and
   wait up to 15 s for the first packet.
2. Compare it with the previous session's reading. If it moved by more than the
   configured variance (default 1 % of tank capacity, converted to raw counts),
   or a further 10 s of sampling shows such a change, keep streaming.
3. Stay connected until the weight has been within the variance — and no gas
   flow is detected — for the stable time (default 5 min), capped at 24 h.
4. Disconnect so the scale can return to its low-power state.

*Request reading* does steps 1 then disconnects. *Start live monitoring* skips
the change check and holds the connection for the full quiet period.

Gas flow is inferred from the stream, not reported by the scale: over a window
of at least the detection time (default 60 s) the window is split into thirds
and the median propane weight must fall from first to middle to last third, at
a rate of at least the minimum (default 0.5 lb/h). Requiring both steps to fall
keeps a single bump or lifted tank from registering as use.

## Not yet documented

These have **not** been verified in this repository and should be filled in from
`monitor/` captures rather than assumed:

- Advertisement interval, payload layout, and what changes when the scale is
  awake vs. asleep.
- How long the scale keeps notifying after connect, and its notification rate.
- Whether the scale ever sends any packet other than `AA 01 …`.
- Load-cell range, resolution limits, and the mechanical dead zone below which
  raw stays at zero.
- Battery byte behaviour at low charge (only `100` appears in the tests).
- Purpose of `FFE9` and other characteristics (inventoried by
  `run.ps1 -ProbeOnFirstSeen`, but not written to).

## Capturing data

`monitor/` is a Windows tool that records advertisements and, optionally,
GATT inventory and `FFE4` notifications to JSONL. See
[`monitor/README.md`](../monitor/README.md). Captures stay local
(`monitor/logs/` is git-ignored) because they can contain identifiers of
unrelated nearby devices.

## Credits and related work

Earlier public reverse-engineering by Alex Whittemore and Althost2 informed this
work. For hardware-level notes on the scale (not its Bluetooth protocol), see
[mmiller7's ESPHome conversion](https://github.com/mmiller7/ESPHome-Mod-Flame-King-Propane-Scale),
which reports three load cells, a separate Bluetooth radio and microcontroller,
and load-cell drift of roughly 6–7 lb over a 30 °F change. These are that
author's observations on their own unit and have not been reproduced here.
