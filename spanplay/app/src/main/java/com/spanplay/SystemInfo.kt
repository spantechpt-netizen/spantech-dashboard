package com.spanplay

import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Build

object SystemInfo {
    fun report(ctx: Context): String {
        val sb = StringBuilder()
        fun l(s: String) { sb.append(s).append('\n') }
        val pm = ctx.packageManager
        l("=== Device ===")
        l("Android version : ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT}, security patch ${if (Build.VERSION.SDK_INT >= 23) Build.VERSION.SECURITY_PATCH else "n/a"})")
        l("Model           : ${Build.MANUFACTURER} ${Build.MODEL} (device=${Build.DEVICE}, product=${Build.PRODUCT}, board=${Build.BOARD})")
        l("Hardware / ABI  : ${Build.HARDWARE} / ${Build.SUPPORTED_ABIS.joinToString()}")
        l("Build           : ${Build.DISPLAY}")
        l("Fingerprint     : ${Build.FINGERPRINT}")

        l("")
        l("=== Bluetooth ===")
        l("Feature bluetooth     : ${pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH)}")
        l("Feature bluetooth LE  : ${pm.hasSystemFeature(PackageManager.FEATURE_BLUETOOTH_LE)}")
        try {
            val bt = (ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager)?.adapter
            if (bt == null) l("Adapter                : none") else {
                l("Adapter enabled       : ${bt.isEnabled}")
                if (Build.VERSION.SDK_INT >= 26) {
                    l("LE 2M PHY supported   : ${bt.isLe2MPhySupported}")
                }
                l("Multi-adv supported   : ${bt.isMultipleAdvertisementSupported}")
            }
        } catch (t: Throwable) {
            l("Adapter query failed  : $t")
        }

        l("")
        l("=== Wi-Fi ===")
        l("Feature wifi          : ${pm.hasSystemFeature(PackageManager.FEATURE_WIFI)}")
        l("Feature wifi direct   : ${pm.hasSystemFeature(PackageManager.FEATURE_WIFI_DIRECT)}")
        l("Feature wifi aware    : ${if (Build.VERSION.SDK_INT >= 26) pm.hasSystemFeature(PackageManager.FEATURE_WIFI_AWARE) else "n/a (<26)"}")
        try {
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            l("Wi-Fi enabled         : ${wm.isWifiEnabled}")
            l("5 GHz band supported  : ${wm.is5GHzBandSupported}")
            if (Build.VERSION.SDK_INT >= 30) l("6 GHz band supported  : ${wm.is6GHzBandSupported}")
            if (Build.VERSION.SDK_INT >= 21) l("P2P supported         : ${wm.isP2pSupported}")
            val lohApi = Build.VERSION.SDK_INT >= 26
            l("LocalOnlyHotspot API  : ${if (lohApi) "present (SDK>=26) - real start is tested in Phase 2" else "NOT available (SDK<26)"}")
        } catch (t: Throwable) {
            l("Wi-Fi query failed    : $t")
        }
        return sb.toString()
    }
}
