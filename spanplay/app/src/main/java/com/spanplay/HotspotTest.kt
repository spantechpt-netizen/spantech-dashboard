package com.spanplay

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import android.net.wifi.SoftApConfiguration
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.Looper

/**
 * Phase 2, step 1 (no protocol code): can this unit start a LocalOnlyHotspot from a normal app,
 * and and what SSID/security does it use? (band and channel are not readable by normal apps) The passphrase is never logged.
 */
class HotspotTest(private val act: Activity, private val log: (String) -> Unit) {
    private var reservation: WifiManager.LocalOnlyHotspotReservation? = null

    fun start() {
        log("=== LocalOnlyHotspot test ===")
        if (reservation != null) { log("Already running. Press Stop first."); return }
        if (Build.VERSION.SDK_INT < 26) { log("Not available: SDK < 26"); return }

        val need = mutableListOf<String>()
        if (act.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED)
            need += Manifest.permission.ACCESS_FINE_LOCATION
        if (Build.VERSION.SDK_INT >= 33 &&
            act.checkSelfPermission(Manifest.permission.NEARBY_WIFI_DEVICES) != PackageManager.PERMISSION_GRANTED)
            need += Manifest.permission.NEARBY_WIFI_DEVICES
        if (need.isNotEmpty()) {
            log("Permission needed: ${need.joinToString()} - allow the dialog, then press Start again.")
            act.requestPermissions(need.toTypedArray(), 7)
            return
        }
        try {
            val lm = act.getSystemService(Context.LOCATION_SERVICE) as LocationManager
            if (Build.VERSION.SDK_INT >= 28) log("Location services on: ${lm.isLocationEnabled}")
        } catch (_: Throwable) {}

        val wm = act.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        log("Wi-Fi enabled: ${wm.isWifiEnabled}")
        try {
            wm.startLocalOnlyHotspot(object : WifiManager.LocalOnlyHotspotCallback() {
                override fun onStarted(r: WifiManager.LocalOnlyHotspotReservation) {
                    reservation = r
                    log("STARTED.")
                    describe(r)
                    EventLog.add(act, "LocalOnlyHotspot test: started")
                }
                override fun onStopped() { log("Hotspot stopped by system."); reservation = null }
                override fun onFailed(reason: Int) {
                    val name = when (reason) {
                        ERROR_NO_CHANNEL -> "NO_CHANNEL"
                        ERROR_GENERIC -> "GENERIC"
                        ERROR_INCOMPATIBLE_MODE -> "INCOMPATIBLE_MODE (e.g. Wi-Fi/tethering already in use)"
                        ERROR_TETHERING_DISALLOWED -> "TETHERING_DISALLOWED"
                        else -> "unknown"
                    }
                    log("FAILED: reason=$reason $name")
                    EventLog.add(act, "LocalOnlyHotspot test failed: $name")
                }
            }, Handler(Looper.getMainLooper()))
            log("Requested, waiting for the system...")
        } catch (t: Throwable) {
            log("startLocalOnlyHotspot threw: $t")
        }
    }

    private fun describe(r: WifiManager.LocalOnlyHotspotReservation) {
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                val c: SoftApConfiguration? = r.softApConfiguration
                if (c == null) { log("  (no SoftApConfiguration)"); return }
                // Band / channel getters are @SystemApi, i.e. NOT readable by a normal app.
                log("  Band/channel: not exposed to normal apps (check from the iPhone's Wi-Fi details or a scan)")
                log("  Security  : ${c.securityType}")
                log("  Passphrase: ${c.passphrase?.length ?: 0} chars (not shown)")
            } else {
                @Suppress("DEPRECATION")
                val c = r.wifiConfiguration
                log("  SSID: ${c?.SSID}  (band/channel not exposed below SDK 30)")
            }
        } catch (t: Throwable) {
            log("  describe failed: $t")
        }
    }

    fun stop() {
        val r = reservation
        if (r == null) { log("Hotspot test is not running."); return }
        try { r.close() } catch (_: Throwable) {}
        reservation = null
        log("Hotspot test stopped.")
        EventLog.add(act, "LocalOnlyHotspot test: stopped")
    }
}
