# v0.56.0u — Stop Traffic Voice before receiver reassignment

Receiver Assignments now ends the Traffic Voice session before reserving receivers and applying AIS/readsb serial changes. This covers both Marine and Airband. The existing controller waits for the voice service to stop, restores the preceding AIS/ADS-B service topology, and clears the voice session. Voice recovery is cancelled and the session cannot restart Voice during reassignment.

Invalid assignments are rejected before stopping reception. A failed stop aborts reassignment. Traffic Voice remains stopped after the swap; start the desired voice mode explicitly when needed.

Validation: four workflow regression scenarios pass (Marine, Airband, failed stop, and an old session requesting Voice restart). Receiver Authority and Airband regression suites pass, as do Python syntax and diff checks. Services are simulated; physical dongle reception still needs an operator test. The older v0550b controls suite has an existing Marine bank assertion failure, reproduced on unchanged commit 9478b01.
