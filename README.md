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
- Gas flowing and extended gas use
- Propane consumption rate
- Estimated time remaining while gas is flowing
- Gas-use duration
- Battery
- Raw scale reading (for calibration and troubleshooting)
- Request reading and Start live monitoring buttons

The scale device exposes a tank-size dropdown for propane capacity. Selecting
20 lb, 30 lb, or 40 lb supplies the matching typical empty-cylinder weight;
the cylinder's stamped `TW` is an optional override when it differs. Guided
calibration captures raw readings directly from the scale; its manual
calibration entities are disabled by default and remain available for
diagnostics.

## Battery-friendly polling

The integration does not hold the Bluetooth connection open continuously. By
default it wakes the scale every 60 minutes, collects a short sample, and
disconnects so the hardware can return to its low-power state. If the measured
weight changed by more than 1% of propane capacity, it streams updates until the
load has remained within that variance for 5 minutes, then disconnects again.
While a sustained downward trend indicates gas flow, the quiet timer keeps
resetting. The connection closes only after both the weight and detected flow
have been quiet for 5 minutes.

The regular interval, stable time, and variance are configurable from the
device page or **Configure → Polling and battery**. **Request reading** fetches
one fresh sample without changing the schedule. **Start live monitoring**
connects immediately and stays connected until the configured quiet period has
passed; pressing it again extends that window. The most recent values remain
available in Home Assistant while the scale sleeps.

The **Gas flowing** binary sensor is designed as an automation trigger. The
**Extended gas use** binary sensor turns on after the configurable long-use
time (2 hours by default), so notifications remain under the user's normal Home
Assistant notification and automation controls.

Time remaining is calculated from the measured propane weight divided by the
observed consumption rate. It is available only during a sustained burn, when
there is enough live data for an honest estimate. For comparison, the official
Flame King app assumes every appliance burns 36,000 BTU/hour; this integration
does not use that fixed assumption.

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

## Optional package-box overlay

The repository also includes an optional Home Assistant package that uses any
configured Flame King scale as a package-presence sensor without changing this
integration's code or calibration. It supports both `!include_dir_named` and
`!include_dir_merge_named`, captures the empty box as a separate baseline, and
can request one settled reading 10 seconds after the package-box contact sensor
changes from open to closed.
The integration's normal hourly reading remains a fallback for packages placed
on top of the box without opening it.

See [`home_assistant_packages/README.md`](home_assistant_packages/README.md) for
the package files and installation instructions.

## Set up

1. Go to **Settings → Devices & services** and accept the discovered Flame King
   scale. If discovery does not appear, choose **Add integration** and search for
   **Flame King Propane Scale**. The setup flow performs an active scan and finds
   the scale; it never asks you to type a Bluetooth address. Candidates must use
   the exact `Gas Monitor` name and, when advertised, the `FFE0` service UUID.
   On connection the integration verifies the `FFE0` service and `FFE4`
   notification characteristic before accepting scale packets. The discovery
   wizard lets you name the scale, assign its room, and choose the tank size.
   It then offers the cylinder's stamped tare weight as an optional override;
   leave it blank to use the preset empty weight for that tank size.
2. Open the integration's **Configure** dialog and choose **Tank settings**.
   Choose its propane capacity from the tank-size dropdown (normally 20 lb for
   a grill cylinder). Leave the following override blank to use the preset, or
   enter the cylinder's stamped tare weight (`TW`) when it differs.

## Calibration choices

### Factory calibration

Start with the factory calibration. It matches the conversion in the official
Flame King app and is normally adequate for tracking tank level and deciding
when to refill. The firmware can report a literal raw zero with nothing on the
platform even though the loaded conversion extrapolates to zero at raw 64; the
integration treats that as an unloaded state and clips displayed gross weight
at zero instead of showing `-0.55 lb`.

Choose **Configure → Reset factory calibration** at any time to restore those
defaults. Resetting preserves tank size, stamped-tare override, device name,
room, and polling settings.

### Guided household calibration

Use **Configure → Guided scale calibration** if you want to tune the conversion
to the individual scale. Laboratory weights are unnecessary: the goal is a
useful household estimate, not a certified measurement.

1. Remove everything and capture the unloaded state. This identifies the
   firmware's no-load value but is not used as a loaded calibration point.
2. Capture a first known load. A confirmed-empty cylinder, disconnected from
   hoses and accessories, can use its stamped `TW` automatically.
3. Capture a different second load and enter the actual total weight on the
   scale. A reference near the normal 20–40 lb working range gives a useful
   span. The integration derives both scale factor and offset from these two
   loaded measurements, so it no longer assumes Flame King's raw-64 offset.

Practical second references include two gallon water jugs, a weighed bucket of
water, a bag of pet food or rice, or exercise weights. A digital bathroom scale
is adequate: take several readings and use their average, preferably weighing
yourself with and without an awkward object and subtracting the averages. Enter
the result honestly to about `0.1 lb`; extra decimal places do not make a
household reference more accurate. Do not assume an overflowing nominal
five-gallon bucket contains exactly five gallons unless its total weight was
measured separately.

After calibration, use a third known load as a validation check if convenient.
If the result is not better than the factory conversion, reset to factory and
try again with a heavier or more accurately measured reference.

### Advanced manual calibration

**Advanced manual calibration** exposes the fitted raw-zero intercept and a
loaded reference point for diagnostics. Normal setup never requires copying raw
sensor readings or editing these values.

The propane calculation is:

```text
gross_lb = max(0, (raw - raw_zero) × reference_weight_lb / (raw_reference - raw_zero))
propane_lb = max(0, gross_lb - tare_lb)
propane_percent = propane_lb / capacity_lb × 100
```

Percentage is clamped to 0–100%. Raw scale readings remain available for
troubleshooting even when a below-zero converted gross weight is displayed as
zero.

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

The official app's factory conversion is equivalent to:

```text
gross_kg = (raw - 64) / 256
```

Those values are this integration's defaults. Guided calibration first records
the unloaded sentinel, then replaces the factory conversion using two distinct
loaded measurements from the individual scale.

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
