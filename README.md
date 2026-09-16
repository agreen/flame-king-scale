# Flame King Propane Scale for Home Assistant

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

The scale device also exposes configuration-number entities for tare weight,
propane capacity, reference weight, raw zero, and raw reference. These appear in
the **Configuration** section of the device page and can be changed or automated
without reopening the integration setup flow.

## Requirements

- Home Assistant 2025.1 or newer
- A Bluetooth adapter or a connectable ESPHome Bluetooth proxy in range
- Flame King YSNPS1 advertising as `Gas Monitor`

Only one Bluetooth client can connect to the scale at a time. Fully close the
Flame King app and nRF Connect before Home Assistant connects.

## Install with HACS

Until this repository is included in the default HACS catalog:

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
2. Keep the empty scale unloaded and note the **Raw scale reading**.
3. Put a known weight on the scale and note the new raw reading.
4. Open the scale's device page and use its **Configuration** entities (or open
   the integration's **Configure** dialog) to enter:
   - raw zero reading;
   - raw reference reading;
   - known reference weight in pounds;
   - the cylinder's stamped tare weight (`TW`) in pounds;
   - propane capacity (normally 20 lb for a grill cylinder).

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
