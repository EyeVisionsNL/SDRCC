"""Isolated foundation checks; no downloads, live services or receiver access."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from core import features, local_ai as ai


class LocalAI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.config = root / "config" / "features.yaml"
        self.assets = root / "data" / "local_ai"
        for obj, name, value in (
            (features, "FEATURES_CONFIG", self.config),
            (ai, "ROOT", root),
            (ai, "AI_DIR", self.assets),
            (ai, "_transfer", None),
        ):
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        app = Flask(__name__)
        app.register_blueprint(ai.bp)
        self.client = app.test_client()

    def test_legacy_defaults_without_files_or_download(self):
        with patch.object(ai, "download") as download:
            state = self.client.get("/api/local-ai/status").get_json()
            self.assertFalse(state["enabled"])
            self.assertFalse(state["installed"])
            self.assertFalse(self.assets.exists())
            self.assertFalse(self.config.exists())
            self.assertEqual(self.client.post("/api/local-ai/chat", json={"question": "hello"}).status_code, 503)
            download.assert_not_called()
        self.assertTrue(features.feature_enabled("satellite"))

    def test_selection_preserves_features(self):
        self.config.parent.mkdir()
        self.config.write_text("features:\n  satellite: false\n  traffic_voice: true\n  radio_receiver: false\n")
        ai.set_enabled(True)
        self.assertEqual(features.get_features(), {
            "satellite": False, "traffic_voice": True, "radio_receiver": False, "local_ai": True})
        ai.set_enabled(False)
        self.assertFalse(ai.enabled())
        self.assertFalse(features.feature_enabled("satellite"))
        self.assertFalse(features.feature_enabled("radio_receiver"))
        self.config.write_text("features:\n  local_ai: 'false'\n")
        self.assertFalse(ai.enabled())

    def test_bad_origin_and_invalid_request(self):
        self.assertEqual(self.client.post("/api/local-ai/action", json={"action": "install"},
                                         headers={"Origin": "https://foreign.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/local-ai/chat", json={"question": " "}).status_code, 400)
        self.assertEqual(self.client.post("/api/local-ai/chat", json={"question": "x"*2001}).status_code, 400)
        self.assertEqual(self.client.post("/api/local-ai/action", json={"action": "other"}).status_code, 400)

    def test_download_checksum(self):
        payload = b"example"
        with patch.object(ai.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            ai.download("https://example.invalid", Path(self.temp.name)/"ok",
                        hashlib.sha256(payload).hexdigest(), 100)
        with patch.object(ai.urllib.request, "urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                ai.download("https://example.invalid", Path(self.temp.name)/"bad", "0"*64, 100)

    def test_download_progress_and_cancel(self):
        payload = b"example"
        seen = []
        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(payload))}
            def read1(self, size=-1):
                seen.append(dict(ai._transfer))
                return super().read1(size)
        with patch.object(ai.urllib.request, "urlopen", return_value=Response(payload)):
            ai.download("https://example.invalid", Path(self.temp.name)/"progress",
                        hashlib.sha256(payload).hexdigest(), 100)
        self.assertEqual(seen[0]["total_bytes"], len(payload))
        self.assertEqual(seen[1]["received_bytes"], len(payload))
        self.assertIsNone(ai._transfer)
        with patch.object(ai, "_installing", True), patch.object(ai, "_transfer", {"stage": "downloading"}):
            try:
                self.assertEqual(self.client.post("/api/local-ai/action", json={"action": "cancel_install"}).status_code, 202)
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    ai.check_cancel()
            finally:
                ai._cancel.clear()
        self.assertEqual(self.client.post("/api/local-ai/action", json={"action": "cancel_install"}).status_code, 409)

    def test_install_failure_does_not_activate(self):
        with patch.object(ai, "preflight"), patch.object(ai, "download", side_effect=RuntimeError("test failure")):
            with self.assertRaisesRegex(RuntimeError, "test failure"):
                ai.install_assets()
        self.assertFalse(ai.enabled())
        self.assertFalse(self.assets.exists())
        self.assertFalse(self.config.exists())

    def test_remove_only_ai_directory(self):
        self.assets.mkdir(parents=True)
        (self.assets / "example").write_text("data")
        neighbor = self.assets.parent / "receiver.json"
        neighbor.write_text("keep")
        ai.set_enabled(True)
        self.assertEqual(self.client.post("/api/local-ai/action", json={"action": "remove"}).status_code, 200)
        self.assertFalse(self.assets.exists())
        self.assertEqual(neighbor.read_text(), "keep")
        self.assertFalse(ai.enabled())

    def test_busy_gate(self):
        self.assertTrue(ai.LOCK.acquire(blocking=False))
        try:
            self.assertEqual(self.client.post("/api/local-ai/chat", json={"question":"test"}).status_code, 409)
            self.assertEqual(self.client.post("/api/local-ai/action", json={"action":"remove"}).status_code, 409)
        finally:
            ai.LOCK.release()

    def test_settings_saved_only_when_installed(self):
        self.assertEqual(self.client.get("/api/local-ai/status").get_json()["settings"]["max_tokens"], 384)
        self.assertFalse(self.assets.exists())
        self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads": 1, "max_tokens": 128}).status_code, 409)
        self.assets.mkdir(parents=True)
        with patch.object(ai, "installed", return_value=True):
            self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads": 999, "max_tokens": 128}).status_code, 400)
            self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads": True, "max_tokens": 128}).status_code, 400)
            self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads": 1, "max_tokens": 128}).status_code, 200)
        self.assertEqual(ai.settings(), {"threads": 1, "max_tokens": 128, "address_space_gib": 7})
        self.assertFalse(ai.enabled())

    def test_address_space_migration(self):
        self.assets.mkdir(parents=True)
        (self.assets / "settings.json").write_text('{"threads":1,"max_tokens":512}')
        self.assertEqual(ai.settings(), {"threads":1, "max_tokens":512, "address_space_gib":7})
        self.assertEqual(ai.MEMORY_LIMIT, 7 * ai.GIB)
        with patch.object(ai, "installed", return_value=True):
            for limit in (4, 9, True, "7"):
                self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads":1,"max_tokens":128,"address_space_gib":limit}).status_code, 400)
            self.assertEqual(self.client.post("/api/local-ai/settings", json={"threads":1,"max_tokens":128,"address_space_gib":8}).status_code, 200)
        self.assertEqual(ai.settings()["address_space_gib"], 8)

    def test_inference_uses_default_7gib_and_progress(self):
        from unittest.mock import MagicMock
        proc = MagicMock()
        proc.poll.return_value = None
        def request(port, key, path, payload=None, timeout=2):
            if path == "/health":
                self.assertEqual(ai._progress, "Loading model...")
                return {}
            self.assertEqual(ai._progress, "Generating answer...")
            return {"choices":[{"message":{"content":"OK"}}]}
        with patch.object(ai, "enabled", return_value=True), patch.object(ai, "installed", return_value=True), patch.object(ai, "preflight"), patch.object(ai, "binary", return_value=self.assets/"llama-server"), patch.object(ai.subprocess, "Popen", return_value=proc) as spawn, patch.object(ai, "local_request", side_effect=request):
            result = self.client.post("/api/local-ai/chat", json={"question":"OK"})
        self.assertEqual(result.get_json(), {"answer":"OK"})
        args, kwargs = spawn.call_args
        self.assertIn("--as=7516192768", args[0])
        self.assertNotIn("--chat-template-kwargs", args[0])
        self.assertIsNone(kwargs["stderr"])
        proc.terminate.assert_called_once()
        self.assertEqual(ai._progress, "")

    def test_reception_chat_evidence_and_disabled_gate(self):
        from core import local_ai_reception
        evidence = {"source": local_ai_reception.SOURCE, "status": "no_samples", "period": "7d"}
        with patch.object(local_ai_reception, "read_evidence", return_value=evidence) as read, patch.object(ai, "infer", return_value="answer") as infer:
            disabled = self.client.post("/api/local-ai/chat", json={"question":"AIS last week"})
            self.assertEqual(disabled.status_code, 503)
            read.assert_not_called()
            infer.assert_not_called()
            with patch.object(ai, "enabled", return_value=True), patch.object(ai, "installed", return_value=True):
                r = self.client.post("/api/local-ai/chat", json={"question":"AIS last week"})
                self.assertEqual(r.get_json(), {"answer":"answer","evidence":evidence})
                read.assert_called_once_with(ai.ROOT,"7d")
                infer.assert_called_once_with("AIS last week",evidence=evidence)
                infer.side_effect = RuntimeError("inference failed")
                r = self.client.post("/api/local-ai/chat", json={"question":"AIS last week"})
                self.assertEqual(r.status_code,503)
                self.assertEqual(r.get_json()["evidence"], evidence)
        self.assertEqual(self.client.post("/api/local-ai/chat", json={"question":"AIS","reception_period":"SELECT"}).status_code,400)
        self.assertFalse(ai.LOCK.locked())

    def test_reception_context_is_sent_as_data(self):
        from unittest.mock import MagicMock
        proc = MagicMock()
        proc.poll.return_value = None
        evidence = {"period":"24h","ais":{"targets":{"mean":0,"peak":None}}}
        def request(port,key,path,payload=None,timeout=2):
            if path == "/health":
                return {}
            self.assertIn('"mean":0,"peak":null', payload["messages"][0]["content"])
            self.assertIn("not unique ships", payload["messages"][0]["content"])
            self.assertEqual(payload["messages"][1]["content"], "AIS targets?")
            return {"choices":[{"message":{"content":"OK"}}]}
        with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True), patch.object(ai,"preflight"), patch.object(ai,"binary",return_value=self.assets/"llama-server"), patch.object(ai.subprocess,"Popen",return_value=proc), patch.object(ai,"local_request",side_effect=request):
            self.assertEqual(ai.infer("AIS targets?", evidence=evidence),"OK")

    def test_observer_api_read_only_and_optional_inference(self):
        from core import local_ai_health, local_ai_maritime
        health = {"kind":"station_health", "status":"partial"}
        with patch.object(local_ai_health,"snapshot",return_value=health) as observe, patch.object(ai,"infer",return_value="assessment") as infer:
            self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"station_health"}).status_code,503)
            observe.assert_not_called()
            with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True):
                result=self.client.post("/api/local-ai/inspect",json={"kind":"station_health"})
                self.assertEqual(result.get_json(),{"evidence":health})
                infer.assert_not_called()
                result=self.client.post("/api/local-ai/inspect",json={"kind":"station_health","question":"check"})
                self.assertEqual(result.get_json(),{"evidence":health,"answer":"assessment"})
                infer.assert_called_once_with("check",evidence=health)
        self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"maritime","radius_km":999}).status_code,400)
        self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"other"}).status_code,400)
        self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"station_health"},headers={"Origin":"https://foreign.example"}).status_code,403)
        self.assertFalse(ai.LOCK.locked())

    def test_historical_inspect_routes(self):
        from core import local_ai_performance, local_ai_missions
        with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True), patch.object(local_ai_performance,"snapshot",return_value={"kind":"reception_performance"}) as perf, patch.object(local_ai_missions,"snapshot",return_value={"kind":"mission_analyst"}) as missions, patch.object(ai,"infer",return_value="assessment") as infer:
            result=self.client.post("/api/local-ai/inspect",json={"kind":"reception_performance"})
            self.assertEqual(result.get_json(),{"evidence":{"kind":"reception_performance"}})
            perf.assert_called_once_with(ai.ROOT)
            infer.assert_not_called()
            result=self.client.post("/api/local-ai/inspect",json={"kind":"mission_analyst","mission_period":"7d","question":"compare"})
            self.assertEqual(result.get_json(),{"evidence":{"kind":"mission_analyst"},"answer":"assessment"})
            missions.assert_called_once_with(ai.ROOT,"7d")
            infer.assert_called_once_with("compare",evidence={"kind":"mission_analyst"})
            self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"mission_analyst","mission_period":"invalid"}).status_code,400)
        self.assertFalse(ai.LOCK.locked())

    def test_aviation_and_memory_routes(self):
        from core import local_ai_aviation, local_ai_memory
        evidence={"kind":"station_memory","entries":[]}
        with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True), patch.object(local_ai_aviation,"snapshot",return_value={"kind":"aviation"}) as aviation, patch.object(local_ai_memory,"snapshot",return_value=evidence) as memory, patch.object(local_ai_memory,"add") as add, patch.object(local_ai_memory,"delete") as delete, patch.object(local_ai_memory,"import_events",return_value={"added":2}) as importer, patch.object(ai,"infer",return_value="answer") as infer:
            response=self.client.post("/api/local-ai/inspect",json={"kind":"aviation","radius_km":200})
            self.assertEqual(response.get_json()["evidence"]["kind"],"aviation")
            aviation.assert_called_once_with(ai.ROOT,200)
            self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"aviation","radius_km":300}).status_code,400)
            response=self.client.post("/api/local-ai/inspect",json={"kind":"station_memory","memory_query":"USB","memory_page":2,"question":"summarize"})
            self.assertEqual(response.get_json(),{"answer":"answer","evidence":evidence})
            memory.assert_called_once_with(ai.ROOT,"USB",2)
            infer.assert_called_once_with("summarize",evidence=local_ai_memory.model_evidence(evidence))
            add.assert_not_called()
            delete.assert_not_called()
            importer.assert_not_called()
            self.assertEqual(self.client.post("/api/local-ai/memory",json={"action":"add","entry_kind":"note","title":"test"}).status_code,200)
            add.assert_called_once()
            self.assertEqual(self.client.post("/api/local-ai/memory",json={"action":"delete","id":1}).status_code,200)
            delete.assert_called_once_with(ai.ROOT,1)
            self.assertEqual(self.client.post("/api/local-ai/memory",json={"action":"import"}).get_json()["added"],2)
            self.assertEqual(self.client.post("/api/local-ai/memory",json={"action":"import"},headers={"Origin":"https://foreign.example"}).status_code,403)
        self.assertFalse(ai.LOCK.locked())

    def test_anomaly_read_and_settings_api(self):
        from core import local_ai_anomaly
        from unittest.mock import Mock
        evidence={"kind":"anomaly_detection","enabled":True,"status":"monitoring","active":[{"rule":"ram"}]}
        monitor=Mock()
        monitor.snapshot.return_value=evidence
        monitor.configure.return_value=evidence
        with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True), patch.object(local_ai_anomaly,"instance",return_value=monitor), patch.object(ai,"infer",return_value="assessment") as infer:
            response=self.client.get("/api/local-ai/anomaly-status")
            self.assertEqual(response.get_json()["active_count"],1)
            response=self.client.post("/api/local-ai/inspect",json={"kind":"anomaly_detection"})
            self.assertEqual(response.get_json()["evidence"],evidence)
            infer.assert_not_called()
            response=self.client.post("/api/local-ai/inspect",json={"kind":"anomaly_detection","question":"check"})
            self.assertEqual(response.get_json()["answer"],"assessment")
            infer.assert_called_once_with("check",evidence=evidence)
            monitor.configure.assert_not_called()
            self.assertEqual(self.client.post("/api/local-ai/anomaly-settings",json={"enabled":"yes","mqtt":False}).status_code,400)
            self.assertEqual(self.client.post("/api/local-ai/anomaly-settings",json={"enabled":True,"mqtt":True},headers={"Origin":"https://foreign.example"}).status_code,403)
            self.assertEqual(self.client.post("/api/local-ai/anomaly-settings",json={"enabled":False,"mqtt":False}).status_code,200)
            monitor.configure.assert_called_once_with(False,False)

    def test_daily_briefing_api(self):
        from core import local_ai_briefing
        evidence={"kind":"daily_briefing","date":"2026-11-27","mode":"archive"}
        with patch.object(ai,"enabled",return_value=True), patch.object(ai,"installed",return_value=True), patch.object(local_ai_briefing,"snapshot",return_value=evidence) as read, patch.object(ai,"infer",return_value="briefing") as infer:
            result=self.client.post("/api/local-ai/inspect",json={"kind":"daily_briefing","briefing_date":"2026-11-27"})
            self.assertEqual(result.get_json()["evidence"],evidence)
            read.assert_called_once_with(ai.ROOT,"2026-11-27")
            infer.assert_not_called()
            result=self.client.post("/api/local-ai/inspect",json={"kind":"daily_briefing","briefing_date":"2026-11-27","question":"summarize"})
            self.assertEqual(result.get_json()["answer"],"briefing")
            infer.assert_called_once_with("summarize",evidence=evidence)
            self.assertEqual(self.client.post("/api/local-ai/inspect",json={"kind":"daily_briefing","briefing_date":"../invalid"}).status_code,400)
        self.assertFalse(ai.LOCK.locked())

    def test_chat_adapter(self):
        with patch.object(ai, "infer", return_value="answer") as infer:
            res = self.client.post("/api/local-ai/chat", json={"question": " hello "})
            self.assertEqual(res.get_json(), {"answer":"answer"})
            infer.assert_called_once_with("hello")
        self.assertFalse(ai.LOCK.locked())


if __name__ == "__main__":
    unittest.main()
