# bm1370.py
import struct
import serial
import time
import binascii
import logging
import math
from crc import crc5, crc16_false

# Konstanta dari bm_hal.h
TYPE_JOB = 0x20
TYPE_CMD = 0x40
JOB_PACKET = 0
CMD_PACKET = 1
GROUP_SINGLE = 0x00
GROUP_ALL = 0x10
CMD_SETADDRESS = 0x00
CMD_WRITE = 0x01
CMD_INACTIVE = 0x03
TICKET_MASK = 0x14

NONCE_SPACE = 0xffffffff
FREQ_MULT = 25.0
CORE = 128

class AsicResult:

    def __init__(self):
        self.preamble = [0x00, 0x00]
        self.nonce = 0
        self.job_id = 0
        self.version = 0
        self.asic_id = 0
        self.subcore_id = 0
        self.midstate_num = 0

    @classmethod
    def from_bytes(cls, data):
        if not data or len(data) < 11:
            return None

        result = cls()
        result.preamble = list(data[0:2])
        result.nonce = int.from_bytes(data[2:6], 'little')
        result.asic_id = (result.nonce >> 25) & 0x7F
        result.midstate_num = data[6]
        raw_header = data[7]
        result.job_id = (raw_header >> 4) & 0x0F
        result.subcore_id = raw_header & 0x0F
        raw_version = int.from_bytes(data[8:10], 'big')
        result.version = raw_version << 13

        return result

    def __str__(self):
        return (f"ASIC[{self.asic_id}] Nonce: {self.nonce:08x} "
                f"(Job ID: {self.job_id}, Subcore: {self.subcore_id}, "
                f"Midstate: {self.midstate_num}, Ver: {self.version:08x})")


class WorkRequest:
    def __init__(self, job_id, starting_nonce, nbits, ntime, merkle_root, prev_block_hash, version):
        self.id = job_id
        self.starting_nonce = starting_nonce
        self.nbits = nbits
        self.ntime = ntime
        self.merkle_root = merkle_root
        self.prev_block_hash = prev_block_hash
        self.version = version


class BM1370:
    def __init__(self, port, baudrate=115200, timeout=1.0):
        logging.info(f"Opening a serial connection to {port} baud {baudrate}")
        self.serial = serial.Serial(port, baudrate, timeout=timeout)
        # Toggle DTR/RTS agar USB-serial tidak stuck saat re-eksekusi
        self.serial.dtr = False
        self.serial.rts = False
        time.sleep(0.1)
        self.serial.dtr = True
        time.sleep(0.05)
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()
        self.diff_current = 0

    def send(self, header, data):
        packet_type = JOB_PACKET if header & TYPE_JOB else CMD_PACKET
        data_len = len(data)
        total_length = data_len + 6 if packet_type == JOB_PACKET else data_len + 5

        buf = bytearray(total_length)
        buf[0] = 0x55
        buf[1] = 0xAA
        buf[2] = header
        buf[3] = data_len + 4 if packet_type == JOB_PACKET else data_len + 3
        buf[4:4 + data_len] = data

        if packet_type == JOB_PACKET:
            crc16_total = crc16_false(buf[2:4 + data_len])
            buf[4 + data_len] = (crc16_total >> 8) & 0xFF
            buf[5 + data_len] = crc16_total & 0xFF
        else:
            buf[4 + data_len] = crc5(buf[2:4 + data_len])

        self.serial.write(buf)

    def send_simple(self, data):
        self.serial.write(data)

    def clear_port_cache(self):
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def set_chain_inactive(self):
        self.send(TYPE_CMD | GROUP_ALL | CMD_INACTIVE, [0x00, 0x00])

    def set_chip_address(self, address):
        self.send(TYPE_CMD | GROUP_SINGLE | CMD_SETADDRESS, [address, 0x00])

    def BM1370_set_version_mask(self, version_mask: int):
        """Mengonfigurasi mask bit versi (AsicBoost) secara dinamis."""
        versions_to_roll = version_mask >> 13
        version_byte0 = (versions_to_roll >> 8) & 0xFF
        version_byte1 = versions_to_roll & 0xFF
        version_cmd = [0x00, 0xA4, 0x90, 0x00, version_byte0, version_byte1]
        
        #logging.info(f"Setting dinamis version mask ke: {[hex(x) for x in version_cmd]}")
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, version_cmd)

    def set_version_mask(self):
        # Default 0x1FFFFFFF
        self.BM1370_set_version_mask(0x1FFFFFFF)

    def _reverse_bits(self, num):
        return int('{:08b}'.format(num)[::-1], 2)

    def _largest_power_of_two(self, n):
        p = 1
        while p * 2 <= n:
            p *= 2
        return p

    def _next_power_of_two(self, x: int) -> int:
        if x == 0:
            return 1
        return 1 << (x - 1).bit_length()

    def set_job_difficulty(self, difficulty):
        job_difficulty_mask = [0x00, TICKET_MASK, 0b00, 0b00, 0b00, 0b11111111]
        diff_mask = self._largest_power_of_two(difficulty) - 1

        for i in range(4):
            value = (diff_mask >> (8 * i)) & 0xFF
            job_difficulty_mask[5 - i] = self._reverse_bits(value)

        self.diff_current = diff_mask + 1
        logging.info(f"Setting ASIC diff mask to {diff_mask}")
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, job_difficulty_mask)
        return self.diff_current

    def BM1370_set_hash_counting_number(self, hcn: int):
        set_10_hash_counting = [0x00, 0x10, 0x00, 0x00, 0x00, 0x00]
        set_10_hash_counting[2] = (hcn >> 24) & 0xFF
        set_10_hash_counting[3] = (hcn >> 16) & 0xFF
        set_10_hash_counting[4] = (hcn >> 8) & 0xFF
        set_10_hash_counting[5] = hcn & 0xFF
        return set_10_hash_counting

    def BM1370_set_nonce_space(self, frequency: float, asic_count: int, cores: int = 128, nonce_percent: float = 1.0):
        cores_up = self._next_power_of_two(cores)
        asic_count_up = self._next_power_of_two(asic_count)

        hcn_space = NONCE_SPACE / cores_up / asic_count_up
        hcn_max = hcn_space * FREQ_MULT / frequency * 0.5
        hcn_error = 2 * 134
        hcn_frac = nonce_percent * (hcn_max - hcn_error)
        hcn_register_value = int(hcn_frac)

        nonce_space_payload = self.BM1370_set_hash_counting_number(hcn_register_value)
        #logging.info(f"Setting dynamic nonce space for {frequency}MHz, payload: {[hex(x) for x in nonce_space_payload]}")
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, nonce_space_payload)

    def set_hash_frequency(self, asic_id, target_freq, max_diff=0.001):
        freqbuf = bytearray([0x00, 0x08, 0x40, 0xA0, 0x02, 0x41])
        best = None
        postdiv_min = 255
        postdiv2_min = 255

        for refdiv in range(2, 0, -1):
            for postdiv1 in range(7, 0, -1):
                for postdiv2 in range(7, 0, -1):
                    fb_divider = round(target_freq / 25.0 * (refdiv * postdiv2 * postdiv1))
                    newf = 25.0 * fb_divider / (refdiv * postdiv2 * postdiv1)

                    if (0xa0 <= fb_divider <= 0xef and
                            abs(target_freq - newf) < max_diff and
                            postdiv1 >= postdiv2 and
                            postdiv1 * postdiv2 < postdiv_min and
                            postdiv2 <= postdiv2_min):

                        postdiv2_min = postdiv2
                        postdiv_min = postdiv1 * postdiv2
                        best = (refdiv, fb_divider, postdiv1, postdiv2, newf)

        if not best:
            logging.warning(f"Failed to find PLL configuration for {target_freq}MHz")
            return False

        if asic_id != -1:
            freqbuf[0] = asic_id * 2

        freqbuf[2] = 0x50 if (best[1] * 25 / best[0]) >= 2400 else 0x40
        freqbuf[3] = best[1]
        freqbuf[4] = best[0]
        freqbuf[5] = ((best[2] - 1) & 0xf) << 4 | (best[3] - 1) & 0xf

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, freqbuf)
        return True

    def frequency_ramp_up(self, target_frequency):
        current = 56.25
        step = 6.25

        if target_frequency == 0 or abs(target_frequency - current) < 0.001:
            return True

        logging.info(f"Ramping frequency from {current} MHz to {target_frequency} MHz")
        direction = step if target_frequency > current else -step

        while (direction > 0 and current < target_frequency) or (direction < 0 and current > target_frequency):
            next_step = min(abs(direction), abs(target_frequency - current))
            current += next_step if direction > 0 else -next_step
            self.set_hash_frequency(-1, current)
            time.sleep(0.1)

        return self.set_hash_frequency(-1, target_frequency)

    def get_asic_count(self):
        for _ in range(4):
            self.set_version_mask()

        init3 = bytearray([0x55, 0xAA, 0x52, 0x05, 0x00, 0x00, 0x0A])
        self.send_simple(init3)

        chip_counter = 0
        start_time = time.time()

        while (time.time() - start_time) < 1.0:
            if self.serial.in_waiting >= 11:
                rsp = self.serial.read(11)
                if b'\xaa\x55\x13\x70' in rsp:
                    chip_counter += 1
        return chip_counter

    def init(self, freq, diff, asic_count):
        logging.info(f"Initiation BM1370: {asic_count} chip, Diff: {diff}, Freq: {freq}MHz")
        # Meniru mujina: version mask default dikirim awal
        self.set_version_mask()

        self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [0x00, 0xA8, 0x00, 0x07, 0x00, 0x00])
        self.set_chain_inactive()

        address_interval = 4
        for i in range(asic_count):
            self.set_chip_address(i * address_interval)
            
        #core register
        self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x8B, 0x00])
        self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x80, 0x0C])

        self.set_job_difficulty(diff)

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x58, 0x00, 0x01, 0x11, 0x11])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x68, 0x5A, 0xA5, 0x5A, 0xA5])

        for i in range(asic_count):
            addr = i * address_interval
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0xA8, 0x00, 0x07, 0x01, 0xF0])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x18, 0xF0, 0x00, 0xC1, 0x00])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x8B, 0x00])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x80, 0x0C])
            self.send(TYPE_CMD | GROUP_SINGLE | CMD_WRITE, [addr, 0x3C, 0x80, 0x00, 0x82, 0xAA])

        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0xB9, 0x00, 0x00, 0x44, 0x80])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x54, 0x00, 0x00, 0x00, 0x02])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0xB9, 0x00, 0x00, 0x44, 0x80])
        self.send(TYPE_CMD | GROUP_ALL | CMD_WRITE, [0x00, 0x3C, 0x80, 0x00, 0x8D, 0xEE])

        self.frequency_ramp_up(float(freq))
        
        # Konfigurasi nonce space dinamis berbasis nilai kalkulasi otomatis
        self.BM1370_set_nonce_space(frequency=float(freq), asic_count=int(asic_count), cores=CORE)
        
        self.set_version_mask()

    def _word_reverse(self, data: bytes) -> bytes:
        """Reverse per 4-byte word (untuk hash 256-bit)."""
        result = bytearray()
        for i in range(0, len(data), 4):
            result.extend(data[i:i+4][::-1])
        return bytes(result)

    def send_work_to_asic(self, job: WorkRequest):
        job_header = (job.id & 0x0F) << 3

        prev_block_wr  = self._word_reverse(job.prev_block_hash)
        merkle_root_wr = self._word_reverse(job.merkle_root)

        job_packet_data = struct.pack(
            '<B B I I I 32s 32s I',
            job_header,
            0x01,                  # Command Write
            0x00000000,            # starting_nonce = 0
            job.nbits,             # ← nbits DULU
            job.ntime,             # ← lalu ntime
            merkle_root_wr,        # ← merkle_root (word-reversed)
            prev_block_wr,         # ← prev_block (word-reversed)
            job.version            # ← version PALING AKHIR
        )

        # Build frame serial
        header_byte = TYPE_JOB | GROUP_SINGLE | CMD_WRITE
        data_len = len(job_packet_data)
        total_length = data_len + 6

        buf = bytearray(total_length)
        buf[0] = 0x55
        buf[1] = 0xAA
        buf[2] = header_byte
        buf[3] = data_len + 4
        buf[4:4 + data_len] = job_packet_data
        crc16_total = crc16_false(buf[2:4 + data_len])
        buf[4 + data_len] = (crc16_total >> 8) & 0xFF
        buf[5 + data_len] = crc16_total & 0xFF

        logging.info(
            f"JobFull {{ job_id: {job.id}, nbits: {job.nbits}, ntime: {job.ntime}, "
            f"version: {job.version} }}, bytes={len(buf)}, frame={buf.hex()}"
        )

        self.send(header_byte, job_packet_data)

    def wait_for_result(self):
        rsp = self.serial.read(11)
        if not rsp or len(rsp) != 11:
            return None

        if rsp[0] != 0xAA or rsp[1] != 0x55:
            self.clear_port_cache()
            return None

        return AsicResult.from_bytes(rsp)

    def raw_result(self):
        rsp = self.serial.read()
        return rsp

    def close(self):
        if self.serial and self.serial.is_open:
            try:
                self.serial.dtr = False
                self.serial.rts = False
                time.sleep(0.05)
                self.serial.reset_input_buffer()
                self.serial.reset_output_buffer()
            except Exception:
                pass
            self.serial.close()
