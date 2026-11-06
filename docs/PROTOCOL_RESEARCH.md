# Phase 2/3 protocol research (DRAFT for owner review)

Status: research only. No protocol code has been written. Waiting for the owner's go-ahead.
Everything below marked **(unverified)** comes from search-result summaries or memory and must be
checked against the primary source before we rely on it.

## 0. What we already know (measured in the car)
* Head unit: BYD DiLink 5.0, Android 12 (SDK 32), Qualcomm SM7325. Wi-Fi 5 GHz and 6 GHz supported,
  Bluetooth LE supported, LocalOnlyHotspot API present (real start not tested yet).
* Dongle `1a86:5512` = CH341 in I2C mode. Bulk OUT 0x02 / IN 0x82. Our Phase 1 probe reads it fine from a normal app.
* One device answers on I2C address 0x11. Its registers read back as: version 05, firmware 01, protocol 2.0,
  device ID 00 00 02 00, challenge length 0x0014 (20), response length 0x0080 (128).
  This is consistent with an Apple MFi authentication coprocessor (2.0C family) **(inference, not proof)**.
  Open item: the certificate-length register (0x30) read back `FF FF`; needs a second look.
* The vendor app "Phone Screen" is `com.autochips.carplayapp`. We do not decompile or copy it.

## 1. What is publicly documented, and what is not
| Area | Status |
|---|---|
| CH341 I2C framing | Public, open-source Linux driver (used in Phase 1). |
| MFi auth coprocessor register map / protocol | Apple's interface specification is under the MFi NDA (the SparkFun library README says so). Only partial community knowledge exists. |
| Wireless CarPlay handover (Bluetooth iAP2 session, accessory info, authentication, Wi-Fi credentials handover) | Not published by Apple. Described in security research, e.g. the TU Darmstadt SEEMOO talk "Apple CarPlay: What's Under the Hood" (Troopers 2024). **Need to read it fully (unverified details here).** |
| AirPlay / CarPlay session (video, audio, touch) | Partly open (AirPlay pieces exist in open-source), partly closed (MFi parts). No single authoritative public spec found. |
| Security note | Researchers report iAP2 authenticates the head unit to the phone's expectations only one way (head unit checks phone, not the reverse). Reported claim, not verified by us. Relevant to safety: a car-side stack must treat the phone as untrusted input. |

## 2. Existing open-source projects (very relevant)
1. **xcertplay** (github.com/shilapi/xcertplay) - CarPlay receiver for Android head units, wired and wireless.
   * Talks to the MFi chip through a **CH341 I2C bridge** or the board's native I2C - exactly our hardware path.
   * Also has "local key files" and "remote MFi server" modes. **We must NOT use those**: our hard rules allow only
     the genuine chip inside the owner's own dongle.
   * License: **GNU GPL v3.0**. Author says it works on some head units/phones; Ultra protocol is incomplete.
2. **DiPlay** - reported (search summary, unverified) to be an open-source Android CarPlay receiver aimed at
   BYD DiLink, built on xcertplay, no dongle hardware required. Repo URL and license NOT verified yet
   (could not be fetched from this session). It would be the closest match to this car.
3. **PlayPort** - macOS server ported from DiPlay/xcertplay; relies on own or remote MFi credentials (not chip). Not usable for us.
4. Carlinkit / wireless-dongle reverse-engineering repos - they study another vendor's dongle firmware, not a raw
   head-unit stack. Useful for protocol hints only.

## 3. Licensing consequence (needs the owner's decision)
xcertplay is GPLv3. Options:
* **A. Use it as a study reference only**, write our own code (clean-room style, credit it). Slowest, most work, no license entanglement.
* **B. Fork/reuse xcertplay code inside SpanPlay.** Allowed under GPLv3 provided SpanPlay is also released under GPLv3 with source
  available to anyone who receives the APK. For a car used only by the owner this is easy to satisfy. Fastest.
* **C. Before any coding: install and test xcertplay's own APK in the car** (chip mode over CH341) and see how far it gets
  on this DiLink 5.0 unit. If it works, our job shrinks to the Guardian, hotspot/auto-start and polish.
  Needs care: use only the "CH341 chip" mode, never the key-file or remote modes.
Recommendation: C first (zero code, very informative), then B if it nearly works, A only if licensing is a problem.

## 4. Phase 2 design sketch (not started)
1. **Wi-Fi:** `WifiManager.startLocalOnlyHotspot` (SDK 26+). Caveat: a normal app cannot choose band/channel, the OS picks;
   we will log what it picked. Whether DiLink 5.0 allows it for a third-party app is unknown until tested. Fallback: the
   car's own hotspot switched on by hand (what happens today), or privileged paths we do not have.
2. **Bluetooth:** pair with the iPhone, open the iAP2-style RFCOMM link, authenticate through the real chip (Phase 1 access),
   then send the Wi-Fi credentials to the phone. Android 12 needs runtime permissions (BLUETOOTH_CONNECT/SCAN/ADVERTISE).
   Unknown: whether the head unit's own Bluetooth stack lets a third-party app register the needed RFCOMM service
   while "Phone Screen" and the system also use Bluetooth.
3. **Auto-run:** start with the car and when the paired iPhone is in range. Our boot trigger itself is not proven yet on this
   unit (open issue from Phase A testing).
4. Only Phase 3 (video H.264 -> MediaCodec, audio, touch) needs the full session stack.

## 5. Risks (be honest)
* Apple can change behaviour in any iOS update and break an unofficial receiver; no official support.
* The authoritative spec is under NDA; we work from reverse-engineered material that may be incomplete or wrong.
* Possible conflicts with the vendor "Phone Screen" app and the OS Bluetooth/Wi-Fi stack on the head unit.
* Legal/terms grey area: unlicensed accessory implementation. Personal use only, genuine chip only, no leaked keys.
* Safety: a receiver parses data from the phone; keep it a sandboxed normal app and never touch vehicle functions.

## 6. Realistic estimate (rough guesses, not commitments)
* Option C test (xcertplay as-is): minutes to an hour of the owner's time; outcome is information.
* Phase 2 (hotspot + Bluetooth handoff + auto-run), if reusing xcertplay ideas/code: a few focused sessions plus several
  car test rounds. Uncertain mainly because of OS permissions on this DiLink unit.
* Phase 3 from scratch: weeks of work with high risk; much less if xcertplay's stack runs on this unit.

## 7. Questions for the owner
1. OK to publish SpanPlay under GPLv3 if we reuse xcertplay code (option B)? Or keep clean-room (A)?
2. OK to test xcertplay's own APK in the car first (option C), chip mode only?
3. Does the head unit sleep (suspend) when you turn the car off, or fully reboot? (decides how auto-start must work)

## Sources
* xcertplay README: https://raw.githubusercontent.com/shilapi/xcertplay/master/README.md (GPLv3, CH341 I2C support)
* i2c-ch341-usb (GPL-2.0), CH341 framing: https://github.com/gschorcht/i2c-ch341-usb
* SparkFun Authentication Coprocessor library (notes the spec is NDA-only): https://github.com/sparkfun/SparkFun_Authentication_Coprocessor_Arduino_Library
* TU Darmstadt SEEMOO, "Apple CarPlay: What's Under the Hood", Troopers 2024 (to be read in full)
* PlayPort wiki: https://github.com/youcci/playport/wiki
* DiPlay: referenced only via a web search summary; primary source not yet checked
