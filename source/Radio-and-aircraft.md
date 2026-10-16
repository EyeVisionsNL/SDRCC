# 📻 Radio and aircraft

## Radio Receiver: tune directly

1. Open **Radio Receiver** and check that a receiver can be allocated.
2. Select a preset or enter the wanted frequency.
3. Select the appropriate demodulation mode. SDRCC supports **LSB, USB, CW, AM, NFM, FM and WFM**.
4. Start reception and enable audio playback.
5. Use the spectrum/waterfall and click-to-tune controls to inspect the signal. Adjust tuning steps, gain and RF-power squelch as needed.
6. Stop the Radio Receiver when finished so Receiver Manager can release it and restore its previous role.

![Radio Receiver](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/radio-receiver.webp)

## Airband Voice and ADS-B

Open **Traffic Voice** and select **Airband Voice + ADS-B** for aviation listening. Choose the channels to scan or listen on a fixed channel. Airband audio preferences are separate from Marine settings.

ADS-B provides aircraft data; Airband Voice provides radio audio. Check both reception paths independently when one works and the other does not. Use **Radio View** for the combined overview and the aircraft map for aircraft details.

![Airband Traffic Voice](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/traffic-airband.webp)

## If a receiver is busy

Check **Radio Control**, Traffic Voice, Radio Receiver and active missions. Receiver Manager coordinates access to a physical dongle: multiple logical roles do not create extra receivers. Stop the task you no longer need through its normal controls, then retry.

[[Home]] · [[First steps]] · [[Updates and troubleshooting]]
