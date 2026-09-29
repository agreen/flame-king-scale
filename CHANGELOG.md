# Changelog

All notable changes to this project are documented here.

## 0.6.3

- Keep Request reading as a one-shot refresh that disconnects after receiving a
  fresh scale packet.
- Add a separate Start live monitoring button that connects immediately and
  stays connected through the configured quiet period.
- Let another Start live monitoring press extend an already-active session.

## 0.6.2

- Make tank size the primary setup choice and automatically apply its typical
  empty-cylinder weight (17 lb, 25 lb, or 32 lb).
- Present stamped tare as an optional override instead of a second required
  tank setting, while preserving existing custom tare values.
- Update the typical empty weight with device-page tank-size changes while
  leaving an existing stamped override untouched.
- Rename the device-page tare entity to Stamped tare override.

## 0.6.1

- Replace the propane-capacity slider with a Tank size dropdown for the Flame
  King app's 20 lb, 30 lb, and 40 lb sizes.
- Preserve an existing custom capacity in the dropdown and allow custom values
  through the integration's Tank settings flow.

## 0.6.0

- Change the battery-friendly regular reading interval to 60 minutes by default.
- Detect sustained propane consumption while actively monitoring the scale.
- Add gas-flow and extended-use binary sensors for Home Assistant automations.
- Add measured consumption-rate, gas-use-duration, and time-remaining sensors.
- Keep resetting the 5-minute quiet timer while gas continues to flow.
- Add configurable flow-detection, minimum-rate, and long-use thresholds.
- Correct the factory default zero point to raw 64 so default weights exactly
  match the official Flame King app conversion across the scale's range.
- Add a confirmed Reset factory calibration action that preserves tank and
  device settings and allows guided calibration to be redone from scratch.

## 0.5.0

- Replace the permanent Bluetooth connection with battery-friendly adaptive
  polling (30-minute regular interval by default).
- Keep streaming after a significant weight change, then disconnect after the
  reading stays within a configurable variance for 5 minutes.
- Keep the last sensor readings available while the scale sleeps.
- Add configurable polling, stability, and variance entities plus a Request
  reading button.

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
