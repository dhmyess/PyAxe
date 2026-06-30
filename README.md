# PyAxe
Bitcoin Miner with python and Bitaxe Gamma 601 with bitaxe-raw firmware

First bitaxe-raw firmware must be installed on your Bitaxe
https://github.com/bitaxeorg/bitaxe-raw

This is an alternative to mujina firmware https://github.com/256foundation/mujina
if you see like this
~~~
  --- TELEMETRY TPS546D24A ---
    Input Voltage (VIN)  : 5.38 V
    Core Voltage (VOUT)  : 1.096 V
    Output Current (IOUT): -0.49 A
    Regulator Temp       : 34.8 °C
~~~
Output Current (IOUT): -0.49 A is normal because Temp Diode (Reg 0x54) not activated yet in this phase, will be activated in the ASIC init phase, you can call function read_output_current(controll) after asic init finish to see that

My method in this script:
- Random Extranonce2
- Version masks don't start from the base version, but rather randomly. A single bm1370 chip with a hash rate of 1.2 TH/s can't possibly complete 65536 versions in a single job (the average pool gives 60 seconds per job), while a bm1370 chip takes over 200 seconds to complete scanning 65536 version masks (1fffe000). For example, if scanning starts from version 3cec0000 and reaches the 3fffe000 limit, the chip will automatically roll back to 20000000, so this method is not problematic.

This is output sample
~~~
python miner.py 
[OK] Connected to /dev/ttyACM0 @ 115200 baud
[INFO] full reset sequence...
  [INFO] Reset ASIC (RST_N -> LOW)...
  [INFO] Power OFF TPS546...
  [INFO] Set fan minimum...
  [INFO] EMC2101 Status Register: 0x12
  [OK] EMC2101 Config: TACH input enabled
  [OK] EMC2101 Fan Config: Driver enabled, Direct mode
  [OK] EMC2101 reset & init finished
  [INFO] Waiting for settle...
  [INFO] EMC2101 Status Register: 0x12
  [OK] EMC2101 Config: TACH input enabled
  [OK] EMC2101 Fan Config: Driver enabled, Direct mode
  [OK] EMC2101 reset & init finished
Internal temp = 33°C Fan speed = 8955rpm
POWER ON TPS546D24A (Vcore = 1.1V)
  [OK] TPS546 ON_OFF_CONFIG = 0x1F
  [OK] TPS546 Temperature limits set (80°C warn, 85°C fault)
  [OK] TPS546 VOUT_COMMAND set: 1.1V
  [OK] TPS546 OPERATION = ON (0x80)

  --- TELEMETRY TPS546D24A ---
    Input Voltage (VIN)  : 5.38 V
    Core Voltage (VOUT)  : 1.096 V
    Output Current (IOUT): -0.49 A
    Regulator Temp       : 39.2 °C

  --- STATUS WORD ---
    Raw Status: 0x0000
    [OK] TPS546: Power is ON dan Regulating.
[INFO] Doing pin RESET ASIC (RST_N -> HIGH)...
  [OK] ASIC nRST (GPIO 0) set HIGH
  [INFO] Waiting 3 seconds for ASIC to boot...
2026-07-01 04:24:29,170 - INFO - Opening a serial connection to /dev/ttyACM1 baud 3000000
2026-07-01 04:24:30,823 - INFO - Found 1 chip BM1370
2026-07-01 04:24:30,823 - INFO - Initiation BM1370: 1 chip, Diff: 256, Freq: 600MHz
2026-07-01 04:24:30,824 - INFO - Setting ASIC diff mask to 255
2026-07-01 04:24:30,835 - INFO - Ramping frequency from 56.25 MHz to 600.0 MHz
2026-07-01 04:24:40,595 - INFO -   Get ready to mine
[DEBUG] authorize response: {'id': 3, 'error': None, 'result': True}
[+] Auth OK
[+] extranonce1 = 638a4cfa
[+] extranonce2_size = 8
[+] Set version mask = 1fffe000
[+] Initial difficulty: 100000.00
2026-07-01 04:24:42,181 - INFO - [*] ASIC Current Temp: 68.25°C
[+] New Job detected! Job ID: 142fdb
2026-07-01 04:25:22,287 - INFO - [*] ASIC Current Temp: 74.00°C
[+] New Job detected! Job ID: 143add
2026-07-01 04:26:22,406 - INFO - [*] ASIC Current Temp: 76.50°C
[+] New Job detected! Job ID: 1445e7
2026-07-01 04:27:22,240 - INFO - [*] ASIC Current Temp: 77.25°C
  [✅] 04:27:22 New Session Best Diff!
       Job ID: 1445e7
       EN2   : a22d5b03d5c92eee
       Ntime : 6a4434ba
       Nonce : 3ba0a28b
       V_Mask: 3f2d6000
       Hash  : 0000000000000e73e1285fda95064212f7f26f95d13618da83a4562956a39d0f
       Diff  : 1160822.06
[+] New Job detected! Job ID: 1450db
2026-07-01 04:28:22,234 - INFO - [*] ASIC Current Temp: 77.50°C
[i] 04:28:47 Share submitted: Job ID: 1450db EN2: cb11dcb98d249ae1 Ntime: 6a4434f6 Nonce: dfc6f6a5 V_Mask: 3ef7e000 Diff: 150577.85 of 100000.0
[+] New Job detected! Job ID: 145bc3
2026-07-01 04:29:22,155 - INFO - [*] ASIC Current Temp: 77.62°C
[+] Pool difficulty updated: 16384.000000
[+] New Job detected! Job ID: 145c43
2026-07-01 04:29:42,117 - INFO - [*] ASIC Current Temp: 77.62°C
[+] New Job detected! Job ID: 1466a8
2026-07-01 04:30:22,328 - INFO - [*] ASIC Current Temp: 77.75°C
[+] New Job detected! Job ID: 147150
2026-07-01 04:30:25,974 - INFO - [*] ASIC Current Temp: 77.62°C
[+] Pool difficulty updated: 2048.000000
[+] New Job detected! Job ID: 1471dc
2026-07-01 04:30:42,117 - INFO - [*] ASIC Current Temp: 77.75°C
[i] 04:30:54 Share submitted: Job ID: 1471dc EN2: ea5a0890b53826a3 Ntime: 6a443582 Nonce: 5256e8cd V_Mask: 23e94000 Diff: 4152.90 of 2048.0
[i] 04:31:07 Share submitted: Job ID: 1471dc EN2: ea5a0890b53826a3 Ntime: 6a443582 Nonce: d5090551 V_Mask: 25b5a000 Diff: 35057.00 of 2048.0
[i] 04:31:10 Share submitted: Job ID: 1471dc EN2: ea5a0890b53826a3 Ntime: 6a443582 Nonce: 6065ee79 V_Mask: 2620a000 Diff: 17890.85 of 2048.0
[i] 04:31:12 Share submitted: Job ID: 1471dc EN2: ea5a0890b53826a3 Ntime: 6a443582 Nonce: 61548972 V_Mask: 2670c000 Diff: 16785.30 of 2048.0
[i] 04:31:14 Share submitted: Job ID: 1471dc EN2: ea5a0890b53826a3 Ntime: 6a443582 Nonce: 6bafdb70 V_Mask: 26ab2000 Diff: 2501.76 of 2048.0
[+] New Job detected! Job ID: 147c1c
2026-07-01 04:31:15,173 - INFO - [*] ASIC Current Temp: 77.88°C
[i] 04:31:17 Share submitted: Job ID: 147c1c EN2: fac2c18d61d49dc8 Ntime: 6a4435a3 Nonce: 4fff102b V_Mask: 277d6000 Diff: 7621.46 of 2048.0
[i] 04:31:34 Share submitted: Job ID: 147c1c EN2: fac2c18d61d49dc8 Ntime: 6a4435a3 Nonce: beafe57c V_Mask: 29d20000 Diff: 2072.63 of 2048.0
[i] 04:31:39 Share submitted: Job ID: 147c1c EN2: fac2c18d61d49dc8 Ntime: 6a4435a3 Nonce: f5653721 V_Mask: 2a814000 Diff: 3177.74 of 2048.0
[+] Pool difficulty updated: 16384.000000
[+] New Job detected! Job ID: 147cc9
2026-07-01 04:31:42,117 - INFO - [*] ASIC Current Temp: 77.88°C
~~~
[+] New Job detected! Job ID: 1486fc
2026-07-01 04:32:15,898 - INFO - [*] ASIC Current Temp: 78.12°C
