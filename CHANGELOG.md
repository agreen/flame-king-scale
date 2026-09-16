# Changelog

All notable changes to this project are documented here.

## 0.4.0

- Add guided two-point calibration that captures live raw readings from the
  connected scale.
- Support a confirmed-empty, disconnected cylinder as the reference load using
  its configured stamped tare weight.
- Separate tank settings from calibration and disable manual calibration-number
  entities by default.

## 0.3.1

- Use 18 lb as the suggested tare weight for a standard 20 lb cylinder. The
  cylinder's stamped `TW` value remains authoritative and can be changed during
  setup or from the device page.

## 0.3.0

- Add a first-run wizard for scale name, room, cylinder tare weight, and propane
  capacity.
- Add writable configuration entities for tank and calibration values.
- Classify the raw scale reading as a diagnostic entity.
- Add local Home Assistant brand assets and HACS/Hassfest validation.
- Preserve the Bluetooth connection while configuration values change.

## 0.2.1

- Fix sensor registration on current Home Assistant releases.
- Fix the Bluetooth confirmation translation placeholder.

## 0.2.0

- Add address-free active Bluetooth discovery for devices named `Gas Monitor`.
- Validate the `FFE0` service and `FFE4` notification characteristic on
  connection.

## 0.1.0

- Initial Flame King YSNPS1 Bluetooth integration.
