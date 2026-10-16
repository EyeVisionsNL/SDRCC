# 🔌 Your first reception

## 1. Check System

Open **System** and check service status and detected receiver hardware. A configured slot is a logical role; it does not mean a particular USB socket.

## 2. Bind the receivers

Under **System → Receiver hardware + bindings**, assign the detected receiver serials to **SDR1 / SDR2**. Use **None** for an unused slot. Check the physical serial before assigning a receiver: USB indexes can change after reconnecting or restarting.

![Services and receiver bindings](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/system-services.webp)

## 3. Check the role assignments

Open **Radio Control** to inspect receiver assignments and RF settings. Decide which receiver should provide AIS, ADS-B or a temporary listening task. A receiver already doing another job may need to be handed over by Receiver Manager.

![Radio Control](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/radio-control.webp)

## 4. Test one task first

Start the reception service you want to test and confirm its status. For Marine listening, continue with [[Marine and ATIS]]. For aircraft or general listening, use [[Radio and aircraft]]. Once one task works, add the next service and check that its receiver is available.

## 5. Allow browser audio

Start listening using the page's audio controls. If the browser blocks playback, allow audio for the SDRCC site and check the tab and system volume. A running receiver and audible browser playback are separate checks.

## Know where to look

| Page | Purpose |
| --- | --- |
| System | Health, hardware, bindings and maintenance |
| Radio Control | Assignments, receiver status and RF settings |
| Radio View | Aircraft, vessels and satellite overview |
| Traffic Voice | Marine or Airband listening and correlations |
| Radio Receiver | Direct tuning, spectrum and waterfall |
| Mission Planner / Control | Pass planning and scheduled reception |
| Mission Operations / History / Analytics | Results and reception quality |
| Logs | Details when a task does not work as expected |

[[Home]] · [[Updates and troubleshooting]]
