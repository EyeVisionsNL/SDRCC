# 🛰️ Plan a pass. Find the result.

## 1. Check the station

Confirm that your station location and receiver bindings are correct. Connect an antenna suitable for the satellite signal. A predicted pass alone does not guarantee reception: the satellite must be transmitting the wanted mode and your station must be able to receive it.

## 2. Open Mission Planner

Review upcoming passes and the reception rules for the satellite you want to receive. Check timing, receiver availability and the configured reception settings before scheduling.

![Mission Planner](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/mission-planner.webp)

For an announced event such as ISS SSTV, check the current event announcement and its frequency, mode and active dates. Event times can change; an old announcement is not evidence that a transmission is currently active.

## 3. Watch Mission Control

Use **Mission Control** to inspect the upcoming queue, assigned receiver and scheduler state. At reception time SDRCC reserves the required receiver and handles conflicting receiver services. After the pass, it releases the receiver and can restore its earlier context.

![Mission Control](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/mission-control.webp)

## 4. Open the received products

Use **Mission Operations** to view the products associated with a mission. **Mission History** keeps previous results; **Mission Analytics** provides reception information such as Peak SNR and receiver performance.

![Mission results](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/mission-result.webp)

Automated METEOR-M2 3 / METEOR-M2 4 LRPT reception uses SatDump. ISS Voice provides pass planning and reception. Check the available mission type and configuration on your installed version.

## When a pass produces no usable result

Check the mission status and logs first. Compare the planned and actual reception window, receiver assignment, antenna, gain, satellite activity and available reception-quality information. A completed recording can still contain a weak or absent signal.

On Android you can view upcoming missions and selected scheduling controls. Create and configure missions in the main desktop dashboard.

[[Home]] · [[Updates and troubleshooting]]
