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
