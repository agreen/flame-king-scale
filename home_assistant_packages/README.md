# Package box overlay

This optional Home Assistant package turns an existing Flame King scale into a
package-presence sensor. It does not change the Flame King integration or the
scale's calibration. The empty package box is treated as an independent
baseline and subtracted from the scale's gross weight.

## Choose one package format

Copy **only one** of the following files into Home Assistant. The two files
contain the same entities and automations, but their outer YAML structure is
different.

### `!include_dir_named` (recommended)

In `/config/configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Copy `include_dir_named/package_box.yaml` to:

```text
/config/packages/package_box.yaml
```

With this include method, the filename becomes the package name, so the file
starts directly with `input_number:`, `template:`, and the other integrations.

### `!include_dir_merge_named`

In `/config/configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_merge_named packages
```

Copy `include_dir_merge_named/package_box.yaml` to:

```text
/config/packages/package_box.yaml
```

With this include method, the YAML file must contain its own top-level
`package_box:` package name. Do not use this version with `!include_dir_named`.

## Initial setup

The included defaults use these existing Flame King entities:

```text
sensor.back_yard_gas_monitor_2_gross_weight
button.back_yard_gas_monitor_2_request_reading
```

If this is a different scale, change the two **Package box scale...** text
helpers after Home Assistant starts. Enter complete entity IDs, including the
`sensor.` or `button.` prefix.

1. Check the configuration and restart Home Assistant.
2. Make sure the box is completely empty and closed.
3. Run the **Package box: Capture empty baseline** script once.
4. Adjust **Package box detection threshold** if needed. It defaults to 1 lb.
5. Leave **Package box clear hysteresis** at 0.25 lb initially. This prevents
   small scale fluctuations from repeatedly reporting a package as added and
   removed.

The package creates:

- **Package box weight change**: signed weight relative to the empty-box
  baseline; useful for troubleshooting.
- **Package box package weight**: positive package weight, clipped at zero.
- **Package box package present**: on when the positive change crosses the
  configured detection threshold.
- **Package box: Capture empty baseline**: stores the current gross weight as
  the empty-box baseline. This does not alter scale calibration.
- **Package box: Check 10 seconds after close**: waits 10 seconds and presses
  the integration's one-shot **Request reading** button.

## Package-box contact sensor

The Aqara package-box sensor exposes this Home Assistant entity:

```text
binary_sensor.package_box_contact
```

It is a door-class contact sensor, not an event entity. `on` means open and
`off` means closed. The included automation listens specifically for the
`on → off` transition. Ten seconds after closing, it verifies that the box is
still closed and requests one scale reading. The delay gives the lid, box, and
scale time to settle. If the box was reopened during the delay, the reading is
skipped and the next close schedules a new one. A live five-minute monitoring
session is intentionally not started. The same settled check detects both a
newly delivered package and a package that was removed.

This close-triggered reading is only a fast path. The package-presence sensor
also evaluates every normal reading produced by the Flame King integration,
including its battery-friendly hourly poll. A delivery left on top of the box
without opening the lid will therefore still be detected, although the notice
can arrive up to approximately one polling interval later. Reducing that delay
means shortening the integration's regular polling interval, with the expected
battery-life tradeoff.

If another installation uses a differently named contact entity, change both
references to `binary_sensor.package_box_contact` in the YAML. Alternatively,
have an existing close automation run:

```yaml
- action: script.package_box_check_10_seconds_after_close
```

No scale action is required when the box opens. The reading after the next
close captures the useful settled state.

The contact device also exposes battery, voltage, internal device temperature,
and last-seen diagnostics. Those can be useful for maintenance alerts but are
not delivery triggers. The disabled trigger-count and link-quality diagnostics
are likewise unnecessary for this package.

## Notification hooks

When package presence changes, this package fires:

```text
flame_king_package_detected
flame_king_package_removed
```

Both events include `package_weight_lb` and `gross_weight_lb`. Use those events
as triggers in normal Home Assistant UI automations and choose any mobile,
speaker, or other notification action you prefer. Keeping notification targets
outside this package makes it portable between Home Assistant installations.

## Updating the empty baseline

Run **Package box: Capture empty baseline** again whenever the empty box itself
changes materially. Do not use the integration's scale-calibration controls to
tare the box; calibration describes the physical scale, while this baseline
describes the object that permanently sits on it.

