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
