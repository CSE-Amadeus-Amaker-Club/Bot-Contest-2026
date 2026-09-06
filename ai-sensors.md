# Sensors

The bot combines onboard sensors with external modules connected through the expansion board. This page distinguishes the sensors' **hardware capabilities** from the smaller set of features exposed by the current aMaker bot UDP firmware.

> A capability listed by the hardware manufacturer is not automatically available to a UDP client. Use the **UDP access** column below as the source of truth for remote clients.

## UDP Sensor Overview

Sensor services use the same binary UDP transport as the rest of the bot on port `24642`.



| Sensor | Hardware | Service | UDP access in the current firmware |
|---|---|---:|---|
| LiDAR |  64x8 DTOF sensor | `0x08` LidarService | Distance and intensity scans, statistics, stream configuration, and stream control |
| Geomagnetic sensor | DFRobot SEN0619 BMM350 | `0x09` GeomagService | Heading, three-axis magnetic field, stream configuration and control, and hard-iron calibration |
| Accelerometer | DFRobot SEN0409 LIS2DW12 | `0x0A` ImuService | Three-axis acceleration, stream configuration and control, and bump configuration/events |
| AI vision | DFRobot SEN0305 HuskyLens K210 | `0x07` HuskyLensService | Light and stream controls; usable results depend on sensor and firmware readiness |

Sensor streams are asynchronous UDP frames. A client should identify each frame by its action byte and keep stream reception separate from command/reply handling. The documented LiDAR distance stream uses action `0x8F`.

The current documentation does not define every sensor command's byte-level payload. Do not infer action IDs or payload layouts from the manufacturer's I2C, UART, or Arduino APIs. Use only action and payload definitions documented for the aMaker Bot firmware.

## LiDAR

The [SEN0682 64x8 Matrix DTOF sensor](https://wiki.dfrobot.com/sen0682/) measures 512 points simultaneously across a **120-degree horizontal by 20-degree vertical field of view**, with a manufacturer-specified maximum range of 5m (10cm minimum). The hardware supports single-point, line, and full-matrix output over UART or USB Type-C.
It scans 512 points at 8Hz.

The UDP service exposes distance and intensity scans, statistics, and configurable streaming. It does **not** imply access to every native SEN0682 mode or AT command.

** Be careful with wiring !!! The LiDAR uses UART and requires 5 V power. See [AI wiring](ai-wiring.html#lidar-dfrobot-64x8-dtof) before connecting or powering it.***

## Geomagnetic Sensor

The [SEN0619 BMM350](https://wiki.dfrobot.com/sen0619/) measures magnetic field strength on three axes. The hardware has a manufacturer-specified range of +/-2000 uT and supports selectable sampling rates up to 400 Hz.

The UDP service exposes heading, three-axis field values, streaming, configuration, and hard-iron calibration. Heading quality depends on calibration and nearby motors, wiring, batteries, and steel parts. **Calibrate after final assembly and repeat calibration when the magnetic environment changes.**

## Accelerometer

The [SEN0409 LIS2DW12](https://wiki.dfrobot.com/sen0409/) is a three-axis accelerometer with selectable +/-2 g, +/-4 g, +/-8 g, and +/-16 g ranges. The sensor hardware also supports functions such as orientation, tap, free-fall, wake-up, and motion detection.

The UDP service exposes only **acceleration and bump event**. The hardware's other interrupt and detection modes are not  UDP features.

## HuskyLens

The [SEN0305 HuskyLens K210](https://wiki.dfrobot.com/sen0305/) provides built-in vision algorithms including face recognition, object tracking, object recognition, line tracking, color recognition, tag recognition, and object classification. Its native interfaces can report detected object coordinates and IDs.

The UDP service documents light and stream controls only. **Choice of detection algorithm must be done on the device itself**. Do not assume that model training, algorithm selection, screenshots, SD-card functions, custom text, or the complete native result API can be controlled over UDP.

## Onboard Sensors

The [UNIHIKER K10](https://wiki.dfrobot.com/dfr0992-en/) includes more sensing hardware than the bot protocol currently exposes:

| Onboard hardware | Manufacturer capability | UDP status |
|---|---|---|
| AHT20 | Temperature and humidity | Not documented over UDP |
| LTR303ALS | Ambient light, up to 64,000 lux | Not documented over UDP |
| SC7A20H | Three-axis acceleration | Not documented over UDP; the bot's ImuService describes the external LIS2DW12 path |
| GC2145 camera | 2 MP image sensor, 80-degree field of view | Not documented as a general camera stream over UDP |
| Two MEMS microphones | Audio input | Not documented over UDP |
| Buttons | A, B, RST, and BOOT | Not documented over UDP |

The display, speaker, and three RGB LEDs are outputs rather than sensors. Some outputs have dedicated UDP controls; see [Bot capabilities](ai-capabilities.html).

## Expansion Board Inputs

The [DFR1216 expansion board](https://wiki.dfrobot.com/dfr1216/) provides GPIO, I2C, infrared, and ultrasonic connectivity in addition to its motor, servo, LED, and battery features. Its general-purpose analog/digital inputs, infrared receiver, ultrasonic input, and arbitrary sensors connected to its ports are **not documented as remotely readable through the current UDP protocol**.

## Client Guidance

Consult [UDP services](ai-services.html) for service IDs and [UDP client](ai-udp-client.html#sensor-stream-handling) for the receive-loop pattern, and [binary protocol](binary-protocol.html) for documented frame rules and response codes.

## Hardware References

- [SEN0682 LiDAR 64x8](https://wiki.dfrobot.com/sen0682/)
- [SEN0409 LIS2DW12 accelerometer](https://wiki.dfrobot.com/sen0409/)
- [SEN0619 BMM350 geomagnetic sensor](https://wiki.dfrobot.com/sen0619/)
- [SEN0305 HuskyLens](https://wiki.dfrobot.com/sen0305/)
- [DFR0992-Unihiker K10](https://wiki.dfrobot.com/dfr0992-en/)
- [DFR1216 Epansion board](https://wiki.dfrobot.com/dfr1216/)

---

*See also: [wiring](ai-wiring.html) · [capabilities](ai-capabilities.html) · [service map](ai-services.html)*