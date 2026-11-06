package com.spanplay

import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint

/**
 * Minimal WCH CH341 I2C "stream mode" master (Phase 1).
 *
 * Command bytes and packet framing were taken from the open-source Linux driver
 *   i2c-ch341-usb  (c) 2017 Gunar Schorcht, GPL-2.0
 *   https://github.com/gschorcht/i2c-ch341-usb   (file i2c-ch341-usb.c)
 * which is itself derived from i2c-ch341-usb (Tse Lun Bien) and i2c-ch341 (Marco Gittler).
 * This is an independent Kotlin re-implementation of the same wire format - no code was copied.
 *
 * Framing, as used by that driver:
 *   speed : AA, 60|speed, 00                      (speed 0=20k 1=100k 2=400k 3=750k)
 *   write : AA, 74, 80|(n+1), (addr<<1), data[n], 75, 00
 *   read  : AA, 74, 80|1, (addr<<1)|1, (C0|1) x (len-1), C0, 75, 00   -> device returns `len` data bytes
 * Bulk transfers are at most 32 bytes (CH341A wMaxPacketSize). The driver sends the command packet on
 * the bulk OUT endpoint and, for reads, then reads one packet from the bulk IN endpoint.
 * NOTE: the driver never reads an ACK/NACK status byte; a NACKed read simply returns 0xFF data. So
 * "ACK" detection here is a heuristic (see DongleProbe) and raw bytes are always shown.
 */
class Ch341(
    private val conn: UsbDeviceConnection,
    private val epOut: UsbEndpoint,
    private val epIn: UsbEndpoint,
    private val log: (String) -> Unit,
) {
    companion object {
        const val PKT = 32
        const val CMD_I2C_STREAM = 0xAA
        const val STM_STA = 0x74
        const val STM_STO = 0x75
        const val STM_OUT = 0x80
        const val STM_IN = 0xC0
        const val STM_SET = 0x60
        const val STM_END = 0x00
        const val MAX_READ = PKT - 6 // overhead: AA 74 80|1 addr ... 75 00
        const val TIMEOUT_MS = 500
    }

    fun setSpeed(speed: Int): Boolean {
        val b = byteArrayOf(CMD_I2C_STREAM.toByte(), (STM_SET or (speed and 3)).toByte(), STM_END.toByte())
        return send(b)
    }

    /** Throw away anything left in the IN FIFO from earlier transfers. */
    fun drain() {
        val buf = ByteArray(PKT)
        repeat(4) { conn.bulkTransfer(epIn, buf, PKT, 20) }
    }

    private fun send(data: ByteArray): Boolean {
        val n = conn.bulkTransfer(epOut, data, data.size, TIMEOUT_MS)
        if (n != data.size) { log("  bulkOUT failed: wrote $n of ${data.size}"); return false }
        return true
    }

    /** I2C write of [data] to 7-bit [addr] (START, addr+W, data, STOP). */
    fun write(addr: Int, data: ByteArray): Boolean {
        if (data.size + 5 > PKT) { log("  write too long"); return false }
        val out = ArrayList<Byte>()
        out += CMD_I2C_STREAM.toByte()
        out += STM_STA.toByte()
        out += (STM_OUT or (data.size + 1)).toByte()
        out += (addr shl 1).toByte()
        data.forEach { out += it }
        out += STM_STO.toByte()
        out += STM_END.toByte()
        return send(out.toByteArray())
    }

    /** I2C read of [len] bytes from 7-bit [addr] (START, addr+R, data..., STOP). Null on USB error. */
    fun read(addr: Int, len: Int): ByteArray? {
        if (len < 1 || len > MAX_READ) { log("  bad read length $len"); return null }
        val out = ArrayList<Byte>()
        out += CMD_I2C_STREAM.toByte()
        out += STM_STA.toByte()
        out += (STM_OUT or 1).toByte()
        out += ((addr shl 1) or 1).toByte()
        repeat(len - 1) { out += (STM_IN or 1).toByte() }
        out += STM_IN.toByte()
        out += STM_STO.toByte()
        out += STM_END.toByte()
        if (!send(out.toByteArray())) return null
        val buf = ByteArray(PKT)
        val n = conn.bulkTransfer(epIn, buf, PKT, TIMEOUT_MS)
        if (n < 0) { log("  bulkIN failed/timeout ($n)"); return null }
        return buf.copyOf(n)
    }

    /** Write a register pointer, then read [len] bytes (two separate transactions, STOP in between). */
    fun readReg(addr: Int, reg: Int, len: Int): ByteArray? {
        if (!write(addr, byteArrayOf(reg.toByte()))) return null
        Thread.sleep(2)
        return read(addr, len)
    }
}
