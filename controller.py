import sys
import time
import struct
import serial
from crc import crc5, crc16, crc16_false


# ================== SERIAL PORT CONFIG  ==================
timeout_port = 2.0

# ================== KONSTANTA PROTOKOL BITAXE-RAW ==================
PAGE_I2C = 0x05
PAGE_GPIO = 0x06
PAGE_ADC = 0x07

CMD_I2C_WRITE = 0x20
CMD_I2C_READ = 0x30
CMD_I2C_READWRITE = 0x40


# ================== KONSTANTA EMC2101 ==================

EMC2101_ADDR = 0x4C
REG_INTERNAL_TEMP = 0x00
REG_EXTERNAL_TEMP_MSB = 0x01
REG_EXTERNAL_TEMP_LSB = 0x10
REG_FAN_SETTING = 0x4C
REG_TACH_LSB = 0x46
REG_TACH_MSB = 0x47
REG_STATUS = 0x02
REG_CONFIG = 0x03

TEMP_FAULT_OPEN_CIRCUIT = 0x3F8
TEMP_FAULT_SHORT = 0x3FF

# ================== KONSTANTA TPS546D24A ==================
TPS546_ADDR = 0x24

CMD_TPS_OPERATION = 0x01
CMD_TPS_ON_OFF_CONFIG = 0x02
CMD_TPS_CLEAR_FAULTS = 0x03
CMD_TPS_VOUT_MODE = 0x20
CMD_TPS_VOUT_COMMAND = 0x21
CMD_TPS_OT_WARN_LIMIT = 0x51
CMD_TPS_OT_FAULT_LIMIT = 0x4F
CMD_TPS_STATUS_WORD = 0x79
CMD_TPS_READ_VIN = 0x88
CMD_TPS_READ_VOUT = 0x8B
CMD_TPS_READ_IOUT = 0x8C
CMD_TPS_READ_TEMP = 0x8D
CMD_TPS_PHASE = 0x30

# ================== KONSTANTA GPIO ==================
GPIO_ASIC_RST_N = 0x00

# ================== AKSES KE PORT CONTROLL  ==================

class BitaxeController:
    """Controll untuk komunikasi dengan firmware bitaxe-raw via control serial port."""

    def __init__(self, port, baudrate, timeout=timeout_port):
        self.port = port
        try:
            self.ser = serial.Serial(
                port, baudrate, timeout=timeout,
                dsrdtr=None, rtscts=None
            )
            self.ser.dtr = False
            self.ser.rts = False
            time.sleep(0.5)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            print(f"[OK] Connected to {port} @ {baudrate} baud")
        except serial.SerialException as e:
            print(f"[ERR] Gagal membuka port serial: {e}")
            sys.exit(1)

    def close(self):
        if self.ser.is_open:
            self.ser.close()

    def _build_packet(self, pkt_id: int, page: int, cmd: int, data: list = []) -> bytes:
        length = 6 + len(data)
        header = struct.pack("<HBBBB", length, pkt_id, 0x00, page, cmd)
        return header + bytes(data)

    def send_packet(self, pkt_id: int, page: int, cmd: int, data: list = []):
        """Kirim packet dan baca response."""
        pkt = self._build_packet(pkt_id, page, cmd, data)

        self.ser.reset_input_buffer()
        self.ser.write(pkt)
        self.ser.flush()
        time.sleep(0.05)

        len_bytes = self.ser.read(2)
        if len(len_bytes) < 2:
            return None

        length = struct.unpack("<H", len_bytes)[0]

        id_byte = self.ser.read(1)
        if len(id_byte) < 1:
            return None

        r_data = self.ser.read(length) if length > 0 else b''

        return r_data

    def i2c_write(self, i2c_addr: int, reg_addr: int, value):
        """Write ke I2C device. value bisa int (single byte) atau list (multi-byte)."""
        if isinstance(value, int):
            value = [value]
        data = [i2c_addr, reg_addr] + list(value)
        return self.send_packet(0x01, PAGE_I2C, CMD_I2C_WRITE, data)

    def i2c_readwrite(self, i2c_addr: int, reg_addr: int, read_len: int):
        """Write register address lalu read data."""
        return self.send_packet(0x01, PAGE_I2C, CMD_I2C_READWRITE, [i2c_addr, reg_addr, read_len])

    def gpio_set(self, pin_cmd: int, level: int):
        """Set GPIO pin level."""
        return self.send_packet(0x01, PAGE_GPIO, pin_cmd, [level])

    def adc_read(self, adc_cmd: int):
        """Read ADC value."""
        return self.send_packet(0x01, PAGE_ADC, adc_cmd, [])

# ================== controlll emc2101  ==================

def reset_emc2101(controll):
    res = controll.i2c_readwrite(EMC2101_ADDR, REG_STATUS, 1)
    if res and len(res) > 0:
        status = res[0]
        print(f"  [INFO] EMC2101 Status Register: 0x{status:02X}")

    res = controll.i2c_write(EMC2101_ADDR, REG_CONFIG, 0x04)
    if res:
        print("  [OK] EMC2101 Config: TACH input enabled")
    time.sleep(0.05)

    res = controll.i2c_write(EMC2101_ADDR, 0x4A, 0x23)
    if res:
        print("  [OK] EMC2101 Fan Config: Driver enabled, Direct mode")
    time.sleep(0.05)

    print("  [OK] EMC2101 reset & init finished")
    return True

def get_internal_temp(controll):
    res = controll.i2c_readwrite(EMC2101_ADDR, REG_INTERNAL_TEMP, 1)
    if res and len(res) > 0:
        temp = res[0]
        if temp >= 0x80: temp -= 0x100
        return temp
    return None

def get_external_temp(controll):
    # Baca MSB dan LSB langsung dari I2C
    res_msb = controll.i2c_readwrite(EMC2101_ADDR, REG_EXTERNAL_TEMP_MSB, 1)
    res_lsb = controll.i2c_readwrite(EMC2101_ADDR, REG_EXTERNAL_TEMP_LSB, 1)

    if res_msb and res_lsb and len(res_msb) > 0 and len(res_lsb) > 0:
        temp_msb = res_msb[0]
        temp_lsb = res_lsb[0]

        # Gabungkan MSB dan LSB, lalu geser 5 bit sesuai spesifikasi EMC2101
        reading = (temp_msb << 8) | temp_lsb
        reading >>= 5  # Menghasilkan 11-bit signed value

        # Sign extension untuk nilai negatif (11-bit ke integer Python)
        if reading & 0x0400:  # Jika bit ke-10 (sign bit) bernilai 1
            reading -= 0x0800  # Kurangi dengan 2048

        # Konversi ke float dengan membagi 8.0 (karena 3-bit fractional)
        temp_c = reading / 8.0
        return temp_c
    return None


def set_fan_speed(controll, fan_duty):
    duty = fan_duty
    if duty > 63:
        duty = 63
    controll.i2c_write(EMC2101_ADDR, REG_FAN_SETTING, duty)

def get_fan_rpm(controll):
    res_low = controll.i2c_readwrite(EMC2101_ADDR, REG_TACH_LSB, 1)
    res_high = controll.i2c_readwrite(EMC2101_ADDR, REG_TACH_MSB, 1)
    if res_low and res_high and len(res_low) > 0 and len(res_high) > 0:
        tach_lsb = res_low[0]
        tach_msb = res_high[0]
        reading = tach_lsb | (tach_msb << 8)

        if reading == 0:
            rpm = 0
        else:
            rpm = 5400000 // reading
            if rpm == 82:
                rpm = 0
    return rpm
# ================== FUNGSI MATEMATIKA PMBus ==================
def linear11_to_float(raw_bytes):
    """Konversi Linear11 (5-bit exp, 11-bit mantissa) ke float."""
    raw = int.from_bytes(raw_bytes, 'little')
    exponent = (raw >> 11) & 0x1F
    if exponent & 0x10:
        exponent -= 32
    mantissa = raw & 0x7FF
    if mantissa & 0x400:
        mantissa -= 2048
    return mantissa * (2.0 ** exponent)

def float_to_linear11(value):
    """Konversi float ke format Linear11."""
    for exp in range(-16, 16):
        if -1024 <= value / (2.0 ** exp) < 1024:
            mantissa = int(round(value / (2.0 ** exp)))
            exp_5bit = exp & 0x1F
            mant_11bit = mantissa & 0x7FF
            return (exp_5bit << 11) | mant_11bit
    return 0

def get_vout_mode_exponent(client):
    """Baca VOUT_MODE exponent."""
    res = client.i2c_readwrite(TPS546_ADDR, CMD_TPS_VOUT_MODE, 1)
    if res and len(res) > 0:
        mode_byte = res[0]
        exp = mode_byte & 0x1F
        if exp & 0x10:
            exp -= 32
        return exp
    return -9

def linear16_to_float(raw_bytes, exponent):
    """Konversi Linear16 ke float."""
    raw = int.from_bytes(raw_bytes, 'little')
    return raw * (2.0 ** exponent)

def float_to_linear16(value, exponent):
    """Konversi float ke Linear16."""
    return int(value / (2.0 ** exponent)) & 0xFFFF

# ================== controlll tps546  ==================
def power_on_tps546(controll, target_voltage=1.15):
    """Step 3: Power ON TPS546D24A dengan Vcore target."""
    print(f"POWER ON TPS546D24A (Vcore = {target_voltage}V)")
    controll.i2c_write(TPS546_ADDR, CMD_TPS_OPERATION, 0x00)
    time.sleep(0.1)

    res = controll.i2c_write(TPS546_ADDR, CMD_TPS_ON_OFF_CONFIG, 0x1F)
    if res:
        print("  [OK] TPS546 ON_OFF_CONFIG = 0x1F")
    time.sleep(0.05)

    ot_warn = float_to_linear11(80.0)
    ot_fault = float_to_linear11(85.0)
    controll.i2c_write(TPS546_ADDR, CMD_TPS_OT_WARN_LIMIT, [ot_warn & 0xFF, (ot_warn >> 8) & 0xFF])
    time.sleep(0.05)
    controll.i2c_write(TPS546_ADDR, CMD_TPS_OT_FAULT_LIMIT, [ot_fault & 0xFF, (ot_fault >> 8) & 0xFF])
    time.sleep(0.05)
    print("  [OK] TPS546 Temperature limits set (80°C warn, 85°C fault)")

    controll.i2c_write(TPS546_ADDR, CMD_TPS_PHASE, 0xFF)
    time.sleep(0.05)

    vout_exp = get_vout_mode_exponent(controll)
    raw_val = float_to_linear16(target_voltage, vout_exp)
    controll.i2c_write(TPS546_ADDR, CMD_TPS_VOUT_COMMAND, [raw_val & 0xFF, (raw_val >> 8) & 0xFF])
    time.sleep(0.05)
    print(f"  [OK] TPS546 VOUT_COMMAND set: {target_voltage}V")

    controll.i2c_write(TPS546_ADDR, CMD_TPS_CLEAR_FAULTS, [])
    time.sleep(0.05)

    res = controll.i2c_write(TPS546_ADDR, CMD_TPS_OPERATION, 0x80)
    if res:
        print("  [OK] TPS546 OPERATION = ON (0x80)")
    time.sleep(0.05)

    time.sleep(0.2)
    controll.i2c_write(TPS546_ADDR, CMD_TPS_CLEAR_FAULTS, [])
    time.sleep(0.05)

    print("\n  --- TELEMETRY TPS546D24A ---")

    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_READ_VIN, 2)
    if res and len(res) == 2:
        vin = linear11_to_float(res)
        print(f"    Input Voltage (VIN)  : {vin:.2f} V")

    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_READ_VOUT, 2)
    if res and len(res) == 2:
        vout = linear16_to_float(res, vout_exp)
        print(f"    Core Voltage (VOUT)  : {vout:.3f} V")

    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_READ_IOUT, 2)
    if res and len(res) == 2:
        iout = linear11_to_float(res)
        print(f"    Output Current (IOUT): {iout:.2f} A")

    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_READ_TEMP, 2)
    if res and len(res) == 2:
        temp = linear11_to_float(res)
        print(f"    Regulator Temp       : {temp:.1f} °C")

    print("\n  --- STATUS WORD ---")
    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_STATUS_WORD, 2)
    if res and len(res) == 2:
        status = int.from_bytes(res, 'little')
        print(f"    Raw Status: 0x{status:04X}")

        if status in [0x0000, 0x0002, 0x0080, 0x0082]:
            print("    [OK] TPS546: Power is ON dan Regulating.")
            return True
        else:
            if status & 0x0004: print("    [ERR] VOUT Fault/Warning!")
            if status & 0x0010: print("    [ERR] IOUT Overcurrent!")
            if status & 0x0020: print("    [ERR] VIN Fault/Warning!")
            if status & 0x0040: print("    [ERR] Temperature Fault/Warning!")
            if status & 0x0080: print("    [ERR] CML Fault!")
            if status & 0x0800: print("    [ERR] POWER_GOOD is False!")
            if (status & 0x0002) == 0: print("    [WRN] POWER is OFF.")
            return False

    return False
def read_output_current(controll):
    res = controll.i2c_readwrite(TPS546_ADDR, CMD_TPS_READ_IOUT, 2)
    if res and len(res) == 2:
        iout = linear11_to_float(res)
    return iout

def enable_asic(controll):
    """Enable ASIC (set RST_N High)."""
    res = controll.gpio_set(GPIO_ASIC_RST_N, 0x01)
    if res:
        print("  [OK] ASIC nRST (GPIO 0) set HIGH")
        print("  [INFO] Waiting 3 seconds for ASIC to boot...")
        time.sleep(3.0)
        return True
    else:
        print("  [ERR] Fail to enable ASIC!")
        return False

def emergency_shutdown(controll):
    """Emergency shutdown: matikan ASIC, fan, dan power."""
    print("\n[!] EMERGENCY SHUTDOWN...")
    try:
        controll.gpio_set(GPIO_ASIC_RST_N, 0x00)
        time.sleep(0.05)
        controll.i2c_write(EMC2101_ADDR, REG_FAN_SETTING, 35)
        time.sleep(0.05)
        controll.i2c_write(TPS546_ADDR, CMD_TPS_OPERATION, 0x00)
        print("[OK] ASIC reset, Fan off, Power off.")
    except Exception as e:
        print(f"[ERR] Emergency shutdown Failed: {e}")

