# SpanPlay A1 — Guardian + Dongle Probe

Project lives in `spanplay/`. Build locally: `cd spanplay && ./gradlew assembleDebug`
(APK: `spanplay/app/build/outputs/apk/debug/app-debug.apk`).

## Sources used (credited)
* CH341 I2C stream framing: `i2c-ch341-usb` by Gunar Schorcht (GPL-2.0),
  <https://github.com/gschorcht/i2c-ch341-usb>. Only the wire format (command bytes / packet layout) was used
  as a reference; the Kotlin code is an independent implementation (`Ch341.kt`).
* The MFi register map in `DongleProbe.kt` is a HYPOTHESIS, only raw hex is trusted.

## Known limits (honest)
* The watchdog sees the foreground app through UsageStats. It detects "app left / was killed", NOT an app that
  is frozen but still on screen.
* The CH341 stream mode does not report ACK/NACK; a NACK reads back `FF`. The scan therefore treats
  "not all FF" as "responds". A real device that answers only FF would be missed (raw dumps are still shown for 0x10/0x11).
* Android 10+ can block background activity launches; grant "Display over other apps" (button 2).
* Nothing here was tested in the car yet.

## Measured on the car (2026-11-07, from the Event log)
* Usage Access settings page does NOT exist on this unit (ActivityNotFound for the per-app and direct screens;
  the system shows "Multimedia system does not support this operation" for the generic one).
  The UsageStats watchdog therefore cannot run unless the permission is granted over adb.
* Car off/on sequence seen in the log: `USB dongle 1a86:5512 attached` -> ~15 s later `BOOT_COMPLETED`.
  Kernel uptime keeps counting (no real reboot), but our process is dead at each wake (the service is "created" fresh
  every time), so the app is killed and re-started by those two triggers. Both triggers reached the app.
* Opt-in "Restart on wake" fired: usb-attach at 02:27:11 -> kill requested 02:27:31 -> relaunch 02:27:33.
  Not proven that killBackgroundProcesses really killed the target, and not proven the vendor app would not have started by itself.
* The BOOT_COMPLETED that follows the USB attach is debounced (60 s).

## Result (owner, 2026-11-07)
* Usage Access granted over adb (`appops set com.spanplay GET_USAGE_STATS allow`) via an on-unit "Remote ADB Shell" at 127.0.0.1:5555.
* Watchdog verified in the car: target force-stopped -> detected -> relaunched after ~5 s -> back in foreground (~8 s total).
* Phone Screen reached the real CarPlay screen after the restart-on-wake relaunch.
* Decision: stop at Phase A for now (no Phase 2/3). Added pause (15/30/60 min, also from the service notification) for navigation / video use.
