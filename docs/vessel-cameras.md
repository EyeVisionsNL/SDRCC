# Onboard cameras — develop 0.69.1

An optional **Onboard camera** button accompanies Possible speaker and Recent
possible speakers. A confirmed ATIS/AIS match must have both a curated MMSI and
matching normalized vessel name. This does not change AIS matching or reception.
No camera is requested in the background. A click opens the original provider
page in a sandboxed dialog. Closing it, pressing Escape, hiding the browser tab,
stopping Marine Traffic or a status failure removes the iframe. A new ATIS match
does not silently switch an already opened camera. The title identifies its ship.
A provider link remains available for blocked embeds or unavailable playback.

## Coverage and sources

On 27 October 2026, https://webcam-binnenvaart.nl/ listed 23 ship pages: 22
contained video players and 18 returned an HLS playlist during a point-in-time
check. This is not proof of fresh images or continuous availability. The initial
registry contains 11 identity candidates checked against public vessel records;
it does not imply that all 23 cameras can be reliably associated with AIS.
Camera ownership/association is curated, not confirmed by an automatic provider
MMSI API. Names and MMSIs can change; remove doubtful associations.

| Camera / vessel | MMSI | Identity reference |
| --- | --- | --- |
| Carisma | 244010927 | https://www.vesselfinder.com/vessels/details/244010927 |
| Yaris | 205263890 | https://www.vesselfinder.com/vessels/details/205263890 |
| Mi-Mundo | 244139567 | https://merlingroup.nl/vloot/mi-mundo/ |
| Mejuri | 244219047 | https://www.myshiptracking.com/vessels/mejuri-mmsi-244219047-imo-0 |
| Survivor | 244670966 | https://www.myshiptracking.com/vessels/survivor-mmsi-244670966-imo-0 |
| Karel Doorman | 244660333 | https://www.myshiptracking.com/vessels/karel-doorman-mmsi-244660333-imo-0 |
| Lauwerszee | 244180341 | https://www.myshiptracking.com/vessels/lauwerszee-mmsi-244180341-imo-0 |
| Furka | 244850307 | https://www.myshiptracking.com/vessels/furka-mmsi-244850307-imo-0 |
| Everingen | 244650973 | https://www.vesselfinder.com/vessels/details/244650973 |
| Red Fox | 244700660 | https://www.myshiptracking.com/vessels/red-fox-mmsi-244700660-imo-0 |
| Strick | 244710427 | https://www.myshiptracking.com/vessels/strick-mmsi-244710427-imo-0 |

Camera pages are recorded in `core/vessel_camera.py`. Bernina and Sayonara are
excluded because multiple same-name inland vessels prevent confident matching.
No expiring stream tokens are stored and no video proxy or download is added.
Cameras can be delayed/offline; the UI intentionally does not promise live images.

## Validation and installation

- `python -m unittest discover -s tests -p test_vessel_camera.py -v`
- `node scripts/validate_vessel_camera.cjs`
- Python and JavaScript syntax checks; manifest source/history validation and
  actual `scripts/install/check_update.py` against previous releases and a target
  without optional satellite/radio files.
- The legacy `validate_traffic_voice_ais_correlation_v0550e.py` rejects an existing
  `postMessage` in unchanged `radio_view.js`; that baseline failure is unrelated
  to cameras. The new snapshot regression tests the AIS/camera contract directly.
- The old `validate_release_update_v0590.py` audio-repair assertion also fails
  on unchanged 0.69.0; current service-permission and channel-failure validators pass.
- Real browser video playback and reception hardware still require station testing.

Install through the usual SDRCC dashboard Update button on **develop/beta**.
Confirm version 0.69.1. With a matching ship, open the camera and verify the
provider player and source link. Confirm audio and AIS map remain usable after
closing. Non-catalog ships should have no camera button. No new packages,
satellite missions, Radio Receiver installation or receiver assignments required.
Main is unchanged. The existing updater records its code backup and rollback
path; use that recorded rollback with receivers idle if necessary.
