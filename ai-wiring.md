# Expected Wiring

This page describes the wiring assumptions used by the firmware and client examples.

The cable diagram is the source of truth for sensor connections:

![Sensor wiring diagram](wiring.png)

## Sensor Cable Rules From the Diagram

| Sensor class | Connection rule |
|---|---|
| I2C sensors | Connect to the expansion board I2C header and use `3.3V` power |
| Non-I2C UART/digital sensor shown at left | Do not connect it to I2C; connect it to `P0`, `P1`, `GND`, and `5V` as shown |
| Ground | All externally powered sensors must share ground with the K10/DFR1216 stack |

Do not infer a cable path from protocol service names. Match the physical sensor to the wiring diagram first, then enable the corresponding UDP service.

## Board Stack

| Part | Role |
|---|---|
| UniHiker K10 | ESP32-S3 controller, TFT, onboard RGB LEDs, camera, buttons |
| DFR1216 expansion board | Motor, servo, battery, LED, and GPIO breakout support |
| External sensors | LiDAR, geomag, IMU, HuskyLens depending on build |

## DFR1216 Expansion Board

The DFR1216 board is not only an I2C device. It also breaks out K10 GPIO pins such as `P0`, `P1`, `P2`, `P3`, `P8`, `P12`, `P13`, `P14`, and `P15`.

The servo/motor/LED controller on the board is I2C-controlled. GPIO breakout pins behave like direct K10 GPIO pins.

## LiDAR: DFRobot 64x8 DTOF

The LiDAR-style non-I2C sensor must not be connected to the I2C header. Follow `wiring.png`: signal wires go to GPIO breakout pins and the sensor uses `GND` plus `5V` power.

| Signal | Connection |
|---|---|
| Diagram signal 1 | `P0` |
| Diagram signal 2 | `P1` |
| Ground | `GND` |
| Power | `5V` |
| UART baud | `921600` |

If source comments or older notes mention alternate GPIO labels, prefer the cable diagram for the physical build described by this `/data` documentation set.

## IMU

The firmware expects the LIS2DW12 path, not LIS2DH12, for current IMU sampling behavior. The diagram shows this class of sensor on the I2C header with `3.3V` power.

## Geomag

The geomag service uses BMM350-style magnetometer behavior and requires hard-iron calibration for useful headings. The diagram shows this class of sensor on the I2C header with `3.3V` power.

## HuskyLens

HuskyLens is handled as an AI vision sensor service. Confirm its I2C/power wiring against the hardware guide before enabling stream handling in a client.

## Motors and Servos

| Capability | Notes |
|---|---|
| DC motors | 4 channels, selected with low 4 bits of a motor mask |
| Servos | 6 channels, selected with low 6 bits of a servo mask |
| Servo types | `0=180 degree`, `1=270 degree`, `2=continuous` |
| Battery | Battery level is queryable through motor/board services |

Configure servo type before sending speed or angle commands. Sending speed to a positional servo or angle to a continuous servo can be rejected.
