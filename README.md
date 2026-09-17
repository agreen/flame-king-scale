# Flame King Propane Scale for Home Assistant

[![Validation](https://github.com/agreen/flame-king-scale/actions/workflows/validate.yml/badge.svg)](https://github.com/agreen/flame-king-scale/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=agreen&repository=flame-king-scale&category=integration)

A HACS-compatible Home Assistant custom integration for the stock Bluetooth
electronics in the Flame King YSNPS1 propane tank scale.

No disassembly, ESPHome scale firmware, or HX711 is required. Home Assistant
connects to the scale over Bluetooth (directly or through a connectable ESPHome
Bluetooth proxy), subscribes to the `FFE4` characteristic, and decodes the
six-byte weight packets.

## Entities

- Gross weight
- Propane remaining
- Propane remaining percentage
- Battery
- Raw scale reading (for calibration and troubleshooting)
- Request reading button

The scale device exposes configuration-number entities for tare weight and
propane capacity. Guided calibration captures raw readings directly from the
scale; its manual calibration entities are disabled by default and remain
available for diagnostics.

## Battery-friendly polling

The integration does not hold the Bluetooth connection open continuously. By
default it wakes the scale every 30 minutes, collects a short sample, and
disconnects so the hardware can return to its low-power state. If the measured
weight changed by more than 1% of propane capacity, it streams updates until the
load has remained within that variance for 5 minutes, then disconnects again.

The regular interval, stable time, and variance are configurable from the
device page or **Configure → Polling and battery**. **Request reading** starts an
immediate sample without changing the schedule. The most recent values remain
available in Home Assistant while the scale sleeps.

## Requirements

- Home Assistant 2025.1 or newer
- A Bluetooth adapter or a connectable ESPHome Bluetooth proxy in range
- Flame King YSNPS1 advertising as `Gas Monitor`

Only one Bluetooth client can connect to the scale at a time. Fully close the
Flame King app and nRF Connect before Home Assistant connects.

Home Assistant automatically chooses the nearest configured Bluetooth adapter
or connectable ESPHome proxy that can reach the scale. There is no adapter
selection field to configure or maintain.

## Install with HACS

Until this repository is included in the default HACS catalog:

[![Open your Home Assistant instance and add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=agreen&repository=flame-king-scale&category=integration)

1. In HACS, open **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add this repository URL and choose **Integration**.
4. Install **Flame King Propane Scale** and restart Home Assistant.
5. Turn on the scale. Home Assistant should discover `Gas Monitor` automatically.

Manual installation is also supported: copy
`custom_components/flame_king_scale` into Home Assistant's
`/config/custom_components/` directory and restart.

## Set up and calibrate

1. Go to **Settings → Devices & services** and accept the discovered Flame King
   scale. If discovery does not appear, choose **Add integration** and search for
   **Flame King Propane Scale**. The setup flow performs an active scan and finds
   the scale; it never asks you to type a Bluetooth address. Candidates must use
   the exact `Gas Monitor` name and, when advertised, the `FFE0` service UUID.
   On connection the integration verifies the `FFE0` service and `FFE4`
   notification characteristic before accepting scale packets. The discovery
   wizard lets you name the scale, assign its room, and enter the cylinder's
   stamped tare weight and propane capacity before setup finishes.
2. Open the integration's **Configure** dialog and choose **Tank settings**.
   Enter the cylinder's stamped tare weight (`TW`) and its propane capacity
   (normally 20 lb for a grill cylinder).
3. Choose **Guided scale calibration**. With the scale unloaded, capture zero.
4. Add a reference load and capture it when the reading settles. You can use:
   - a confirmed-empty cylinder, disconnected from hoses and accessories; its
     configured stamped tare weight is used automatically; or
   - another accurately known weight entered in pounds.

The guided flow reads both raw values from the connected scale. **Advanced
manual calibration** is available for diagnostics, but normal setup never
requires copying raw sensor readings.

The propane calculation is:

```text
gross_lb = (raw - raw_zero) × reference_weight_lb / (raw_reference - raw_zero)
propane_lb = max(0, gross_lb - tare_lb)
propane_percent = propane_lb / capacity_lb × 100
```

Percentage is clamped to 0–100%, while gross and propane weight remain available
for troubleshooting.

## Protocol

The known YSNPS1 packet is six bytes:

```text
AA 01 LL HH BB CC
```

- `LL HH`: unsigned little-endian raw load-cell reading
- `BB`: battery percentage
- `CC`: XOR of the first five bytes

The scale exposes service `0000FFE0-0000-1000-8000-00805F9B34FB` and notifies
on characteristic `0000FFE4-0000-1000-8000-00805F9B34FB`.

## Troubleshooting

- If the scale is unavailable, disconnect the official app and nRF Connect.
- If discovery works but connection does not, verify that your ESPHome Bluetooth
  proxy has `active: true` and available connection slots.
- If raw readings update but pounds are wrong, repeat the two-point calibration
  with a heavier known weight.
- If the raw value remains zero, ensure the scale is awake and the load is heavy
  enough to overcome its mechanical dead zone.

## Credits

Protocol research builds on public reverse-engineering work by Alex Whittemore
and Althost2. This project is not affiliated with Flame King.

## License

MIT
