"""Offline Mission Advisor tests; planner/runtime observation is mocked."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json
import sys
from types import SimpleNamespace

from core import local_ai_advisor as advisor


class MissionAdvisorTests(TestCase):
    def setUp(self):
        self.now=1770000000
        self.device={"runtime_id":"sdr1","registry_id":"receiver01","number":"SDR1",
                     "serial":"12345","presence":"PRESENT","roles":["weather","ais"],"locked":False}
        self.tle={"weather":{"valid":True,"stale":False,"age_hours":1},
                  "iss_voice":{"valid":True,"stale":False,"age_hours":1}}
        self.assignments={"weather":"sdr1"}

    def pass_at(self,offset,elevation,name="METEOR-M2 3",**kw):
        start=datetime.fromtimestamp(self.now+offset,timezone.utc)
        return dict({"name":name,"start":start,"end":start+timedelta(seconds=600),
                     "plugin_id":"weather","mission_type":"weather","receiver_role":"weather",
                     "max_elevation":elevation,"pipeline":"lrpt","automation_eligible":True,
                     "execution_enabled":True},**kw)

    def test_geometry_overlap_and_skip(self):
        rows=[self.pass_at(60,75),self.pass_at(300,80,"METEOR-M2 4"),
              self.pass_at(1500,65),self.pass_at(2400,85),
              self.pass_at(-100,90),self.pass_at(90000,90)]
        skipped={"weather:METEOR-M2 3:"+str(self.now+2400):{"skipped":True}}
        result=advisor.summarize(rows,[self.device],self.assignments,{},self.tle,skipped,[],self.now,24,"AUTO")
        self.assertEqual(result["candidate_count"],4)
        self.assertEqual(result["review_count"],3)
        self.assertEqual(result["high_elevation_count"],1)
        self.assertEqual(result["best_geometry"]["elevation"],65)
        self.assertIn("Overlapping mission windows",result["passes"][0]["flags"])
        self.assertIn("Operator skipped",result["passes"][3]["flags"])
        self.assertEqual(result["passes"][2]["shared_roles"],["ais"])

    def test_history_requires_matching_pipeline_receiver_band_and_samples(self):
        raw={"name":"METEOR-M2 3","pipeline":"lrpt","elevation":65}
        row={"satellite":raw["name"],"pipeline":"lrpt","receiver_serial":"12345",
             "max_elevation":70,"result":"SUCCESS","peak_snr_db":9}
        rows=[dict(row),dict(row,result="NO SYNC",peak_snr_db=3),dict(row,peak_snr_db=6),
              dict(row,receiver_serial="wrong",receiver="SDR1"),dict(row,max_elevation=40),
              dict(row,pipeline="other")]
        stats=advisor.historical_match(rows,raw,self.device)
        self.assertEqual(stats["completed"],3)
        self.assertEqual(stats["success_pct"],66.7)
        self.assertEqual(stats["mean_peak_snr_db"],6)
        self.assertIsNone(advisor.historical_match(rows[:2],raw,self.device)["success_pct"])
        self.assertEqual(advisor.historical_match([dict(row,receiver_serial=None,receiver_id="receiver01")],raw,self.device)["completed"],1)

    def test_hardware_tle_and_disabled_flags(self):
        device=dict(self.device,presence="MISSING")
        tle={"weather":{"valid":True,"stale":True}}
        result=advisor.summarize([self.pass_at(100,80,execution_enabled=False)],[device],self.assignments,{},tle,{},[],self.now,24,"PAUSED")
        self.assertIsNone(result["best_geometry"])
        self.assertEqual(set(result["passes"][0]["flags"]),{"Execution not enabled","TLE stale","Receiver presence not confirmed"})
        result=advisor.summarize([self.pass_at(100,80)],[self.device],self.assignments,{"transaction":True},self.tle,{},[],self.now,24,"AUTO")
        self.assertIn("Receiver binding / recovery pending",result["passes"][0]["flags"])

    def test_history_read_only_and_simulation_filter(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/advisor.history.SOURCE
            path.parent.mkdir(parents=True)
            row={"result":"SUCCESS","ended_at":advisor.reception.utc(self.now-1)}
            path.write_text(json.dumps([row,dict(row,pipeline="simulation_demo"),dict(row,result="CANCELLED"),
                                        dict(row,ended_at=advisor.reception.utc(self.now+1))]))
            before=path.read_bytes()
            rows,status=advisor.history_rows(root,self.now)
            self.assertEqual(status,"ok")
            self.assertEqual(rows,[row])
            self.assertEqual(path.read_bytes(),before)

    def test_snapshot_uses_planner_not_queue_mutation(self):
        from core import config, features
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/"data/state/mission_queue.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"overrides":{"old":{"skipped":true}}}')
            before=path.read_bytes()
            from core import __dict__ as core_attrs
            modules={
                "mission_planner":SimpleNamespace(get_candidates=lambda hours:[self.pass_at(100,75)]),
                "device_manager":SimpleNamespace(get_devices=lambda:[self.device]),
                "receiver_manager":SimpleNamespace(binding_status=lambda:{}),
                "tle":SimpleNamespace(get_status=lambda:self.tle),
            }
            with patch.dict(core_attrs,modules),patch.dict(sys.modules,{"core."+k:v for k,v in modules.items()}),patch.object(features,"feature_enabled",return_value=True),patch.object(config,"home_position_configured",return_value=True),patch.object(config,"get_receiver_assignments",return_value=self.assignments):
                data=advisor.snapshot(root,24,now=self.now)
                self.assertEqual(data["status"],"ok")
                self.assertEqual(data["candidate_count"],1)
                self.assertEqual(data["scheduler_mode"],"MANUAL")
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(list(path.parent.iterdir()),[path])
                with self.assertRaises(ValueError):
                    advisor.snapshot(root,True,now=self.now)
                path.write_text('{"overrides":null}')
                self.assertEqual(advisor.snapshot(root,24,now=self.now)["status"],"unavailable")

    def test_display_and_model_bounds(self):
        rows=[self.pass_at(100+i*700,50+i%10) for i in range(30)]
        data=advisor.summarize(rows,[self.device],self.assignments,{},self.tle,{},[],self.now,24,"AUTO")
        self.assertEqual(len(data["passes"]),24)
        self.assertEqual(data["omitted_passes"],6)
        self.assertEqual(len(advisor.model_evidence(data)["passes"]),6)
