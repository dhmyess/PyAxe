import socket
import json
import time
import traceback
import hashlib
import zlib
from datetime import datetime
import random
import controller
import bm1370
import crc
import logging
import sys
import os
import struct
from bm1370 import BM1370, WorkRequest, AsicResult
from crc import crc16_false

# -------------------------------
# CONFIG
# -------------------------------
config = {
    "pool_address": "public-pool.io",
    "pool_port": 3333,
    "user_name": "bc1q7yj3vu46z5uaxafx8krmk3zhy64r6u4j79t2an.pc", #change your btc address in here
    "password": "x",
    "min_diff": 256,
    "poll_sleep": 0.05,
    "reconnect_backoff": 5.0,
    "asic_frequency": 600,
    "voltage": 1.10,
    "controll_port": "/dev/ttyACM0",
    "controll_baudrate": 115200,
    "data_port": "/dev/ttyACM1",
    "data_baudrate": 3000000,
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
controll = controller.BitaxeController(port=config["controll_port"], baudrate=config["controll_baudrate"])


class StratumClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.buffer = b""
        self.extranonce1 = None
        self.extranonce2_size = 0
        self.connected = False
        self.difficulty = 100000.0
        self.request_id = 0
        self.version_mask = "1fffe000"   # default version mask
        self._connect()

    def _connect(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(20.0)
        self.sock.connect((self.host, self.port))
        self.buffer = b""
        self.connected = True

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None
        self.connected = False

    def send(self, method, params):
        self.request_id += 1
        payload = json.dumps({"id": self.request_id, "method": method, "params": params})
        try:
            self.sock.sendall((payload + "\n").encode())
        except Exception:
            self.connected = False

    def recv_blocking_line(self):
        while b"\n" not in self.buffer:
            try:
                data = self.sock.recv(4096)
                if not data:
                    raise Exception("Disconnected")
                self.buffer += data
            except socket.timeout:
                continue
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line.decode())

    def poll_message(self):
        msgs = []
        if not self.connected:
            return msgs
        try:
            self.sock.settimeout(0.0)
            data = self.sock.recv(4096)
            if not data:
                self.connected = False
            else:
                self.buffer += data
        except (BlockingIOError, socket.timeout):
            pass
        except Exception:
            pass
        self.sock.settimeout(20.0)

        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                if line.strip():
                    msgs.append(json.loads(line.decode()))
            except Exception:
                pass
        return msgs

    def configure(self):
        params = [["version-rolling"], {"version-rolling.mask": "ffffffff"}]
        self.send("mining.configure", params)
        resp = self.recv_blocking_line()
        if resp.get("error") is not None:
            raise Exception(f"Configure error: {resp['error']}")
        result = resp.get("result")
        if result and isinstance(result, dict) and "version-rolling.mask" in result:
            self.version_mask = result["version-rolling.mask"]
        return result

    def subscribe(self, user_agent="PyMiner/v1.0"):
        self.send("mining.subscribe", [user_agent])
        resp = self.recv_blocking_line()
        if resp.get("error") is not None:
            raise Exception(f"Subscribe error: {resp['error']}")
        result = resp.get("result")
        if result and len(result) >= 3:
            self.extranonce1 = result[1]
            self.extranonce2_size = result[2]
        else:
            self.extranonce1 = ""
            self.extranonce2_size = 4
        return result

    def authorize(self, user, password):
        self.send("mining.authorize", [user, password])
        resp = self.recv_blocking_line()
        print("[DEBUG] authorize response:", resp)
        if resp.get("error") is not None:
            raise Exception(f"Authorize error: {resp['error']}")
        result = resp.get("result")
        if result is True or result is None:
            return True
        else:
            raise Exception(f"Authorization failed, result = {result}")

    def initialize(self, user, password, user_agent="PyAxe/v1.0"):
        try:
            self.configure()
        except Exception as e:
            print(f"[!] Configure skipped (pool may not support): {e}")
        self.subscribe(user_agent)
        self.authorize(user, password)
        return True


def word_reverse(data: bytes) -> bytes:
    if len(data) % 4 != 0:
        raise ValueError("len must be 4 byte")
    result = bytearray()
    for i in range(0, len(data), 4):
        result.extend(data[i:i+4][::-1])
    return bytes(result)


def rev_hex(hexstr):
    return "".join([hexstr[i:i+2] for i in range(0, len(hexstr), 2)][::-1])


def rev_8B(hexstr):
    out = []
    for i in range(0, len(hexstr), 8):
        out.append(rev_hex(hexstr[i:i+8]))
    return "".join(out)


def double_sha256_hex(hexdata):
    b = bytes.fromhex(hexdata)
    return hashlib.sha256(hashlib.sha256(b).digest()).hexdigest()


def count_bit_1(hexstr):
    bin_str = bin(int(hexstr, 16))[2:]
    count_1 = bin_str.count('1')
    return count_1


def full_reset_sequence():
    """Do full reset before initiation to avoid stuck ports."""
    print("[INFO] full reset sequence...")
    print("  [INFO] Reset ASIC (RST_N -> LOW)...")
    controll.gpio_set(controller.GPIO_ASIC_RST_N, 0x00)
    time.sleep(0.5)

    print("  [INFO] Power OFF TPS546...")
    controll.i2c_write(controller.TPS546_ADDR, controller.CMD_TPS_OPERATION, 0x00)
    time.sleep(0.5)

    print("  [INFO] Set fan minimum...")
    controller.reset_emc2101(controll)
    controller.set_fan_speed(controll, fan_duty=20)
    time.sleep(1.0)

    print("  [INFO] Waiting for settle...")
    time.sleep(2.0)

def gen_version(version_base, mask_hex):
    base_v = version_base
    mask = int(mask_hex, 16)

    low_bit = 0
    while not (mask & (1 << low_bit)) and low_bit < 32:
        low_bit += 1
    num_bits = bin(mask).count('1')
    num_combinations = 2**num_bits
    cleaned_base = base_v & ~mask
    
    results = []
    for i in range(num_combinations):
        rolled_version = cleaned_base | (i << low_bit)
        results.append(rolled_version)
    return results

def mine_loop():
    port = config["data_port"]
    asic = None
    for attempt in range(3):
        try:
            lock_file = f"/var/lock/LCK..{os.path.basename(port)}"
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                    logging.warning(f"remove file lock: {lock_file}")
                except:
                    pass
            asic = BM1370(port=port, baudrate=config["data_baudrate"])
            break
        except Exception as e:
            logging.error(f"Failed to open serial port (attempt {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                controller.emergency_shutdown(controll)
                return

    # ==========================================
    # BLOK TRY 1: Inisialisasi ASIC
    # ==========================================
    try:
        asic.clear_port_cache()
        time.sleep(0.5)
        chip_count = asic.get_asic_count()
        logging.info(f"Found {chip_count} chip BM1370")
        if chip_count == 0:
            chip_count = 1

        asic.init(freq=config["asic_frequency"], diff=config["min_diff"], asic_count=chip_count)
        time.sleep(1.0)
        asic.clear_port_cache()
        logging.info("  Get ready to mine")

    except Exception as e:
        print(f"[!] ASIC initialization failed: {e}")
        if asic:
            asic.set_chain_inactive()
            asic.clear_port_cache()
            asic.close()
        controller.emergency_shutdown(controll)
        return

    # ==========================================
    # VARIABEL LOOP MINING
    # ==========================================
    backoff = config["reconnect_backoff"]
    current_job = None
    current_job_id = None
    target_miner = config["min_diff"]
    need_new_job = True

    # ==========================================
    # BLOK TRY 2: Loop Connection & Mining
    # ==========================================
    while True:
        client = None
        try:
            client = StratumClient(config["pool_address"], config["pool_port"])
            client.initialize(config["user_name"], config["password"])
            print("[+] Auth OK")
            print("[+] extranonce1 =", client.extranonce1)
            print("[+] extranonce2_size =", client.extranonce2_size)
            print(f"[+] Set version mask = {client.version_mask}")
            print(f"[+] Initial difficulty: {client.difficulty:.2f}")
            asic.BM1370_set_version_mask(int(client.version_mask, 16))
            asic_job_id = 0
            best_diff = 0
            version_base = 0x20000000
            vmask = gen_version(version_base,client.version_mask)

            while client.connected:
                # --- Poll pesan dari pool ---
                for msg in client.poll_message():
                    if msg.get("method") == "mining.notify":
                        new_job = msg["params"]
                        new_job_id = new_job[0]
                        new_clean_job = new_job[8]
                        if new_job_id != current_job_id or new_clean_job:
                            current_job = new_job
                            current_job_id = new_job_id
                            need_new_job = False
                            baca_ext_temp = controller.get_external_temp(controll)
                            if baca_ext_temp is not None:
                                logging.info(f"[*] ASIC Current Temp: {baca_ext_temp:.2f}°C")
                                if baca_ext_temp > 79.0:
                                    logging.warning(f"[⚠️] Asic Temp ({baca_ext_temp:.2f}°C) beyond safe limits 79°C!")
                                    logging.warning("[-] Stopping the ASIC hashing circuit...")
                                    asic.set_chain_inactive() # Matikan core hashing
                                    logging.warning("[-] cool down. Rest for 30 seconds...")
                                    time.sleep(30)
                                    asic.clear_port_cache()
                                    logging.info("[+] cool down finish!, resume work, if it always happens, change the frequency and voltage then restart mining.")
                            else:
                                logging.warning("[!] Failed to read temperature (EMC2101)")

                            # Update job variables
                            asic_job_id = 0

                    elif msg.get("method") == "mining.set_difficulty":
                        new_difficulty = float(msg["params"][0])
                        if new_difficulty < target_miner:
                            if new_difficulty < config["min_diff"]:
                                target_miner = config["min_diff"]
                            else:
                                target_miner = new_difficulty
                        if new_difficulty > target_miner:
                            target_miner = new_difficulty
                        if new_difficulty != client.difficulty:
                            client.difficulty = new_difficulty
                            print(f"[+] Pool difficulty updated: {new_difficulty:.6f}")

                if need_new_job and current_job is None:
                    time.sleep(config["poll_sleep"])
                    continue

                # --- If there is a job, send it to ASIC ---
                if current_job is not None:
                    # Build job packet
                    job_header = (asic_job_id & 0x0F) << 3
                    if int(current_job[5], 16) != version_base:
                        version_base = int(current_job[5], 16)
                        vmask = gen_version(version_base,client.version_mask)

                    prev_block_wr = bytes.fromhex(rev_hex(current_job[1]))
                    coinb1 = current_job[2]
                    coinb2 = current_job[3]
                    merkle_branch = current_job[4]
                    nbits = int(current_job[6], 16)
                    ntime = int(time.time())
                    extranonce1 = client.extranonce1
                    extranonce2 = random.randbytes(client.extranonce2_size).hex()
                    coinbase = coinb1 + extranonce1 + extranonce2 + coinb2
                    root = double_sha256_hex(coinbase)
                    for m in merkle_branch:
                        root = double_sha256_hex(root + m)


                    rev_root = rev_hex(root)
                    version_start = random.choice(vmask)
                    merkle_root_wr = bytes.fromhex(rev_8B(rev_root))
                    job_packet_data = struct.pack(
                        '<B B I I I 32s 32s I',
                        job_header,
                        0x01,                  # Command Write
                        0x00000000,            # starting_nonce (nonce2)
                        nbits,                 # nbits
                        ntime,                 # ntime
                        merkle_root_wr,        # merkle_root (word-reversed)
                        prev_block_wr,         # prev_block (word-reversed)
                        version_start   # version
                    )

                    header_byte = 0x21  # TYPE_JOB | GROUP_SINGLE | CMD_WRITE
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

                    raw_frame = bytes(buf)
                    asic.send_simple(raw_frame)

                    # --- Wait for the results from ASIC while continuing to poll for new jobs ---
                    start_wait = time.time()
                    first_packet = None
                    duplicate_detected = False
                    new_job_received = False
                    byte_buffer = bytearray()

                    while (time.time() - start_wait < 60) and not duplicate_detected and not new_job_received:
                        # Poll pool messages
                        for msg in client.poll_message():
                            if msg.get("method") == "mining.notify":
                                new_job = msg["params"]
                                new_job_id = new_job[0]
                                new_clean_job = new_job[8]
                                if new_job_id != current_job_id or new_clean_job:
                                    current_job = new_job
                                    current_job_id = new_job_id
                                    need_new_job = False
                                    new_job_received = True
                                    asic_job_id = 0
                                    print(f"[+] New Job detected! Job ID: {new_job_id}") #breaking asic loop
                                    baca_ext_temp = controller.get_external_temp(controll)
                                    if baca_ext_temp is not None:
                                        logging.info(f"[*] ASIC Current Temp: {baca_ext_temp:.2f}°C")
                                        if baca_ext_temp > 79.0:
                                            logging.warning(f"[⚠️] Asic Temp ({baca_ext_temp:.2f}°C) beyond safe limits 79°C!")
                                            logging.warning("[-] Stopping the ASIC hashing circuit...")
                                            asic.set_chain_inactive() # Matikan core hashing
                                            logging.warning("[-] cool down. Rest for 30 seconds...")
                                            time.sleep(30)
                                            asic.clear_port_cache()
                                            logging.info("[+] cool down finish!, resume work, if it always happens, change the frequency and voltage then restart mining.")
                                    else:
                                        logging.warning("[!] Failed to read temperature (EMC2101)")

                                    break

                            elif msg.get("method") == "mining.set_difficulty":
                                new_difficulty = float(msg["params"][0])
                                if new_difficulty < target_miner:
                                    if new_difficulty < config["min_diff"]:
                                        target_miner = config["min_diff"]
                                    else:
                                        target_miner = new_difficulty
                                if new_difficulty > target_miner:
                                    target_miner = new_difficulty
                                if new_difficulty != client.difficulty:
                                    client.difficulty = new_difficulty
                                    print(f"[+] Pool difficulty updated: {new_difficulty:.6f}")

                        if new_job_received:
                            break

                        # --- Baca dari ASIC ---
                        if asic.serial.in_waiting > 0:
                            raw_bytes = asic.serial.read(asic.serial.in_waiting)
                            byte_buffer.extend(raw_bytes)

                            while True:
                                idx = byte_buffer.find(b'\xaa\x55')
                                if idx != -1:
                                    if idx > 0:
                                        del byte_buffer[:idx]

                                    if len(byte_buffer) >= 11:
                                        packet = bytes(byte_buffer[:11])
                                        del byte_buffer[:11]

                                        if first_packet is None:
                                            first_packet = packet
                                        elif packet == first_packet:
                                            duplicate_detected = True
                                            asic.set_chain_inactive()
                                            break

                                        res = AsicResult.from_bytes(packet)
                                        if res:
                                            nonce = rev_hex(f"{res.nonce:08x}")
                                            version = rev_hex(f"{(version_base + res.version):08x}")

                                            header_result = version + rev_8B(current_job[1]) + root + rev_hex(f"{ntime:08x}") + rev_hex(current_job[6]) + nonce
                                            hash_result = double_sha256_hex(header_result)
                                            blockhash = rev_hex(hash_result)

                                            diff_result = 0x00000000ffff0000000000000000000000000000000000000000000000000000 / int(blockhash, 16)
                                            if diff_result >= target_miner:
                                                now = datetime.now()
                                                current_time_string = now.strftime("%H:%M:%S")
                                                if diff_result > best_diff:
                                                    best_diff = diff_result
                                                    print(f"  [✅] {current_time_string} New Session Best Diff!")
                                                    print(f"       Job ID: {current_job[0]}")
                                                    print(f"       EN2   : {extranonce2}")
                                                    print(f"       Ntime : {ntime:08x}")
                                                    print(f"       Nonce : {res.nonce:08x}")
                                                    print(f"       V_Mask: {(version_base + res.version):08x}")
                                                    print(f"       Hash  : {blockhash}")
                                                    print(f"       Diff  : {diff_result:.2f}")
                                                else:
                                                    print(f"[i] {current_time_string} Share submitted: Job ID: {current_job[0]} EN2: {extranonce2} Ntime: {ntime:08x} Nonce: {res.nonce:08x} V_Mask: {(version_base + res.version):08x} Diff: {diff_result:.2f} of {client.difficulty}")
                                                    #print(f"[i] {current_time_string} Share submitted: Job ID: {current_job[0]} hash = {blockhash} Diff: {diff_result:.2f} of {client.difficulty}")
                                                params = [
                                                    config["user_name"],
                                                    current_job[0],
                                                    extranonce2,
                                                    f"{ntime:08x}",
                                                    f"{res.nonce:08x}",
                                                    f"{res.version:08x}"
                                                ]
                                                client.send("mining.submit", params)
                                    else:
                                        break
                                else:
                                    if len(byte_buffer) > 0:
                                        if byte_buffer[-1] == 0xAA:
                                            del byte_buffer[:-1]
                                        else:
                                            byte_buffer.clear()
                                    break

                            if duplicate_detected:
                                break
                        else:
                            time.sleep(0.001)

                    asic_job_id += 1


        except KeyboardInterrupt:
            print("\nInterrupted by user")
            if asic:
                asic.set_chain_inactive()
                asic.close()
            if client:
                client.close()
            controller.emergency_shutdown(controll)
            return

        except Exception as e:
            print("[!] Exception: ", e)
            traceback.print_exc()
            if asic:
                try:
                    asic.set_chain_inactive()
                except:
                    pass
            if client:
                client.close()
            print(f"[!] Reconnecting in {backoff}s...")
            time.sleep(backoff)


if __name__ == "__main__":

    full_reset_sequence()

    # =====================================================================
    # Normal Initialization
    # =====================================================================
    controller.reset_emc2101(controll)
    controller.set_fan_speed(controll, fan_duty=63)
    time.sleep(2)

    internal_temp = controller.get_internal_temp(controll)
    fan_speed = controller.get_fan_rpm(controll)
    print(f"Internal temp = {internal_temp}°C Fan speed = {fan_speed}rpm")

    # 1. Power On Vcore
    controller.power_on_tps546(controll, target_voltage=config["voltage"])
    time.sleep(2)

    # 2. Activate ASIC
    print("[INFO] Doing pin RESET ASIC (RST_N -> HIGH)...")
    controller.enable_asic(controll)
    time.sleep(1.0)
    mine_loop()
