# Flame King BLE monitor

This Windows console monitor records every nearby `Gas Monitor` Bluetooth Low
Energy advertisement. It prints events while it runs and writes the complete
evidence to a timestamped JSONL file under `monitor\logs`.

After recognizing the scale by name, it follows that Bluetooth address for the
rest of the run, including packets that omit the name. On Windows it also logs
the native advertisement and scan-response pair: packet type, flags, PHY,
connectability, native timestamp, and every raw AD data section.

## Passive monitoring

From PowerShell in the repository directory:

```powershell
.\monitor\run.ps1
```

Passive mode does not connect, pair, subscribe, or write anything. Stop it with
Ctrl+C. Each run prints the exact log path near the top.

## One brief probe

To connect when the scale is first seen, inventory its GATT services, try every
characteristic marked readable, and capture FFE4 notifications for 15 seconds:

```powershell
.\monitor\run.ps1 -ProbeOnFirstSeen
```

Subscribing enables the standard notification descriptor (CCCD). The monitor
does not write the proprietary FFE9 characteristic.

## Periodic health probes

For a brief probe every three hours:

```powershell
.\monitor\run.ps1 -ProbeEveryMinutes 180
```

The scanner must see the device at least once before a probe can connect. Use
`-NotifySeconds 30` to change the notification window.

## Bounded experiment

This example passively records advertisements for 30 minutes and exits:

```powershell
.\monitor\run.ps1 -MaxRuntimeMinutes 30
```

## Long-term sleep experiment

The long-capture preset records every raw scale packet to disk, keeps noisy
advertisement lines off the console, prints a health summary once per minute,
and temporarily prevents Windows system sleep. It does not connect to the
scale. A four-hour capture is the default:

```powershell
.\monitor\long-capture.ps1
```

Choose another duration with `-Hours`, for example:

```powershell
.\monitor\long-capture.ps1 -Hours 8
```

The monitor also counts callbacks from other nearby BLE devices without
recording their names, addresses, or payloads. If the scale becomes silent
while those anonymous witness counts keep increasing, the scale—not the PC
scanner—stopped advertising. A 30-second gap triggers `advertisement_silence`.

Silence and status reporting can be adjusted from PowerShell, for example:

```powershell
.\monitor\run.ps1 -SilenceSeconds 20 -StatusSeconds 120
```

The launcher also accepts `-Name` and `-LogDirectory`. Run
`Get-Help .\monitor\run.ps1` to see its parameters. The Python program has a
few lower-level equivalents listed by
`.\monitor\.venv\Scripts\python.exe .\monitor\flame_king_monitor.py --help`.

Logs are newline-delimited JSON. Important event names include
`advertisement`, `advertisement_update`, `advertisement_silence`, `gatt_service`,
`gatt_characteristic`, `gatt_read`, `notification`, `probe_failed`, and
`run_stopped`.

Advertisement gaps that overlap an intentional GATT probe are marked with
`"gap_includes_scanner_pause": true`; they must not be interpreted as the scale
sleeping or disappearing.
