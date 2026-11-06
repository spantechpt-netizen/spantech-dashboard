package com.spanplay

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import android.os.Build
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Phase 1: talk to the Apple MFi authentication coprocessor through the CH341 (1a86:5512).
 * Strictly READ-ONLY identification: bus scan + a few register reads. No authentication
 * challenge is ever started, nothing is written except register-pointer bytes.
 */
class DongleProbe(private val ctx: Context, private val log: (String) -> Unit) {
    companion object {
        const val VID = 0x1a86
        const val PID = 0x5512
        private const val ACTION_PERM = "com.spanplay.USB_PERMISSION"

        // HYPOTHESIS ONLY: register map of Apple MFi auth coprocessor (2.0C family). Raw hex is what counts.
        private val REGS = listOf(
            Triple(0x00, 1, "device version?"),
            Triple(0x01, 1, "firmware version?"),
            Triple(0x02, 1, "auth protocol major?"),
            Triple(0x03, 1, "auth protocol minor?"),
            Triple(0x04, 4, "device ID?"),
            Triple(0x05, 1, "error code?"),
            Triple(0x10, 1, "auth control/status?"),
            Triple(0x11, 2, "challenge response length?"),
            Triple(0x20, 2, "challenge length?"),
            Triple(0x30, 2, "accessory certificate length?"),
        )
    }

    private fun hex(b: ByteArray?): String =
        if (b == null) "<null>" else if (b.isEmpty()) "<empty>" else b.joinToString(" ") { "%02X".format(it) }

    private fun h2(v: Int) = "0x%02X".format(v)

    fun run() {
        val um = ctx.getSystemService(Context.USB_SERVICE) as UsbManager
        log("=== Dongle probe (Phase 1) ===")
        log("USB devices currently visible:")
        if (um.deviceList.isEmpty()) log("  (none)")
        um.deviceList.values.forEach {
            log("  %s  VID=%04x PID=%04x class=%d name='%s' product='%s'".format(
                it.deviceName, it.vendorId, it.productId, it.deviceClass, it.deviceName,
                if (Build.VERSION.SDK_INT >= 21) it.productName else "?"))
        }
        val dev = um.deviceList.values.firstOrNull { it.vendorId == VID && it.productId == PID }
        if (dev == null) { log("RESULT: dongle 1a86:5512 NOT found. Is it plugged in?"); return }
        log("Found dongle: ${dev.deviceName}")

        if (!um.hasPermission(dev) && !askPermission(um, dev)) {
            log("RESULT: USB permission denied/timeout."); return
        }

        val ifaces = (0 until dev.interfaceCount).map { dev.getInterface(it) }
        log("Interfaces: ${ifaces.size}")
        var chosen: UsbInterface? = null
        var epOut: UsbEndpoint? = null
        var epIn: UsbEndpoint? = null
        for (i in ifaces) {
            log("  IF#${i.id} class=${i.interfaceClass} sub=${i.interfaceSubclass} proto=${i.interfaceProtocol} endpoints=${i.endpointCount}")
            for (e in 0 until i.endpointCount) {
                val ep = i.getEndpoint(e)
                val type = when (ep.type) {
                    UsbConstants.USB_ENDPOINT_XFER_BULK -> "BULK"
                    UsbConstants.USB_ENDPOINT_XFER_INT -> "INT"
                    UsbConstants.USB_ENDPOINT_XFER_ISOC -> "ISOC"
                    else -> "CTRL"
                }
                val dir = if (ep.direction == UsbConstants.USB_DIR_IN) "IN" else "OUT"
                log("    EP addr=0x%02X %s %s maxPacket=%d interval=%d".format(ep.address, type, dir, ep.maxPacketSize, ep.interval))
                if (ep.type == UsbConstants.USB_ENDPOINT_XFER_BULK) {
                    if (ep.direction == UsbConstants.USB_DIR_IN && epIn == null) { epIn = ep; chosen = i }
                    if (ep.direction == UsbConstants.USB_DIR_OUT && epOut == null) { epOut = ep; chosen = i }
                }
            }
        }
        if (chosen == null || epIn == null || epOut == null) { log("RESULT: no bulk IN+OUT pair found."); return }
        log("Using IF#${chosen.id}: bulk OUT 0x%02X, bulk IN 0x%02X".format(epOut.address, epIn.address))

        val conn = um.openDevice(dev)
        if (conn == null) { log("RESULT: openDevice() returned null."); return }
        try {
            if (!conn.claimInterface(chosen, true)) { log("RESULT: claimInterface failed."); return }
            val ch = Ch341(conn, epOut, epIn) { log(it) }
            ch.drain()
            log("Set I2C speed 100 kHz: ${ch.setSpeed(1)}")
            scanAndDump(ch)
        } finally {
            try { conn.close() } catch (_: Throwable) {}
        }
    }

    private fun askPermission(um: UsbManager, dev: UsbDevice): Boolean {
        val latch = CountDownLatch(1)
        var granted = false
        val rx = object : BroadcastReceiver() {
            override fun onReceive(c: Context, i: Intent) {
                granted = i.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)
                latch.countDown()
            }
        }
        val f = IntentFilter(ACTION_PERM)
        if (Build.VERSION.SDK_INT >= 33) ctx.registerReceiver(rx, f, Context.RECEIVER_NOT_EXPORTED)
        else ctx.registerReceiver(rx, f)
        try {
            val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
            val pi = PendingIntent.getBroadcast(ctx, 0, Intent(ACTION_PERM).setPackage(ctx.packageName), flags)
            log("Requesting USB permission (tap OK on the dialog)...")
            um.requestPermission(dev, pi)
            latch.await(60, TimeUnit.SECONDS)
        } finally {
            try { ctx.unregisterReceiver(rx) } catch (_: Throwable) {}
        }
        log("USB permission granted: $granted")
        return granted
    }

    private fun scanAndDump(ch: Ch341) {
        log("")
        log("--- I2C bus scan 0x08..0x77 (read 2 bytes per address; NACK reads back FF FF) ---")
        val candidates = linkedSetOf(0x10, 0x11)
        var allFf = 0
        for (a in 0x08..0x77) {
            var r = ch.read(a, 2)
            var tries = 1
            // The auth chip may sleep: retry NACK-looking / failed reads a few times.
            while ((r == null || r.all { it == 0xFF.toByte() }) && tries < 4) {
                Thread.sleep(10); r = ch.read(a, 2); tries++
            }
            if (r == null) {
                log("  ${h2(a)}: USB error"); 
            } else if (r.all { it == 0xFF.toByte() }) {
                allFf++
            } else {
                log("  ${h2(a)}: RESPONDS  raw=${hex(r)}  (after $tries tries)")
                candidates.add(a)
            }
        }
        log("  ($allFf addresses returned FF FF = most likely NACK / nothing there)")

        for (a in candidates) {
            log("")
            log("--- Register reads at ${h2(a)} (HYPOTHESIS map, raw hex is what matters) ---")
            var anyData = false
            for ((reg, len, name) in REGS) {
                var r = ch.readReg(a, reg, len)
                var tries = 1
                while ((r == null || r.all { it == 0xFF.toByte() }) && tries < 5) {
                    Thread.sleep(15); r = ch.readReg(a, reg, len); tries++
                }
                val flag = if (r != null && !r.all { it == 0xFF.toByte() }) { anyData = true; "" } else "  (looks like NACK)"
                log("  reg ${h2(reg)} x$len  [$name]: ${hex(r)}$flag")
            }
            if (!anyData) log("  -> nothing but FF at ${h2(a)}: probably no device here (or it stayed asleep).")
        }
        log("")
        log("=== Probe finished ===")
    }
}
