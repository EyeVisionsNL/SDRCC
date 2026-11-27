#!/usr/bin/env node
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "..");
(async () => {
  const services = fs.readFileSync(path.join(root,"dashboard/static/js/services.js"),"utf8");
  const template = fs.readFileSync(path.join(root,"dashboard/templates/index.html"),"utf8");
  const section = template.split('id="tab-intelligence"')[1].split('id="tab-logs"')[0];
  for (const id of ["install","toggle","remove","cancel","save","send"]) {
    const button = section.match(new RegExp('<button[^>]*id="local-ai-'+id+'"[^>]*>'))?.[0];
    assert(button?.includes("data-local-ai-control"), "AI button missing isolation: "+id);
  }
  const ai = {disabled:true,classList:{remove(){throw Error("AI controls touched by service refresh");}}};
  const generic = {disabled:true,classList:{remove(){}}};
  global.document = {
    querySelectorAll(selector) {
      assert.equal(selector,".control-button:not([data-local-ai-control])");
      return [generic];
    },
    querySelector(){return null;}
  };
  const module = await import("data:text/javascript;base64,"+Buffer.from(services).toString("base64"));
  module.updateServiceButtons({});
  assert.equal(ai.disabled,true);
  assert.equal(generic.disabled,false);
  const ui=fs.readFileSync(path.join(root,"dashboard/static/js/local_ai.js"),"utf8");
  assert(ui.includes('install.hidden = !s || s.installed;'));
  assert(ui.includes('install.style.display = install.hidden ? "none" : "";'));
  console.log("PASS: AI controls isolated from periodic service refresh");
})().catch(error=>{console.error(error);process.exitCode=1;});
