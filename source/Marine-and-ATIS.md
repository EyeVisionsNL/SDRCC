# 🚢 Hear the traffic. Find the vessel.

## 1. Open Traffic Voice

Choose **Marine Voice + AIS**. Check the receiver assignment and select the marine channels you want to hear. Use a fixed channel to test reception, then enable scanning if you want to follow several channels.

![Marine Traffic Voice](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/traffic-marine.webp)

## 2. Adjust reception

Use **Smart Gain** or select manual gain, then adjust squelch to keep background noise closed while allowing wanted transmissions through. Compare changes on the same channel. More gain is not always better: strong local signals can overload the receiver.

The selectable Marine channel filter and speech/noise reduction controls help tailor listening. Audio processing preferences are separate for Marine and Airband; the ATIS decoding input remains unchanged by speech noise reduction.

Channel lists support Excel import/export. Check an imported list before scanning and exclude channels you do not want to monitor. AIS data channels are not voice-listening channels.

## 3. Understand Possible Speaker

SDRCC decodes marine **ATIS — Automatic Transmitter Identification System** and correlates validated identities with available AIS vessel information. **Possible Speaker** shows a candidate vessel and matching information when a correlation is available.

A clear voice transmission does not guarantee a valid ATIS decode or an AIS match. The transmitting station may not supply a usable ATIS burst, reception may be incomplete, or the necessary AIS identity information may be unavailable. Treat the result as correlation information.

![Possible Speaker, recordings and photo](https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/images/traffic-marine-photo.webp)

## 4. Replay or save a transmission

Use the recent Marine recordings to replay up to the four latest receptions. Save a recording you want to keep while live reception continues. Check the displayed channel when comparing transmissions.

## 5. Use the map and photographs

The desktop **Auto** function can follow validated matches in the AIS-catcher map, reusing the map window and retaining its zoom. On Android, a match highlights the vessel without re-centering the map; tap it yourself for details.

Optional **Ship photos** shows a vessel thumbnail with photographer credit and a link to the original page. Click the credit/source link to view the original. Existing watermarks remain intact. **Google Images** is a separate search link.

The VTS Rijnmond sector overlay is a separate project. On maps with the plugins installed, enable **VTS sector** and **SDRCC ATIS** in the map's plugin selector.

[[Home]] · [[Android companion]] · [[Updates and troubleshooting]]
