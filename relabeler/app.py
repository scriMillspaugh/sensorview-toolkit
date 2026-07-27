"""
SensorView Backup Relabeler — a local, browser-based tool.

Load a SensorView .svdb backup, give devices/zones new labels (edit in the table
or upload a filled CSV), validate against Acuity BMS rules, and download a rebuilt
_relabeled.svdb to import in SensorView.

Runs entirely on localhost — the backup never leaves the machine (it contains hashed
passwords in its Users table). The original file is never modified.

Run:  py webtool/app.py    then open http://127.0.0.1:5000
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
import webbrowser
from threading import Timer

from flask import Flask, jsonify, request, send_file, Response

import core

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024  # 300 MB backups

# In-memory session store: token -> {svdb_path, tempdir, name}
SESSIONS: dict[str, dict] = {}
OUTPUTS: dict[str, str] = {}  # download token -> file path


@app.after_request
def _local_only(resp: Response) -> Response:
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.route("/")
def index() -> Response:
    return Response(PAGE, mimetype="text/html")


@app.route("/api/load", methods=["POST"])
def api_load():
    f = request.files.get("svdb")
    if not f or not f.filename:
        return jsonify({"error": "No file provided."}), 400
    if not f.filename.lower().endswith((".svdb", ".svdo")):
        return jsonify({"error": "Please choose a SensorView .svdb backup file."}), 400
    token = uuid.uuid4().hex
    tmp = tempfile.mkdtemp(prefix="svload_")
    svdb_path = os.path.join(tmp, os.path.basename(f.filename))
    f.save(svdb_path)
    try:
        mdb, _members = core.extract_svdb(svdb_path, tmp)
        tables = core.read_tables(mdb)
        driver = core.find_access_driver()
    except Exception as e:  # noqa: BLE001 — surface any load error to the UI
        return jsonify({"error": str(e)}), 400
    SESSIONS[token] = {"svdb_path": svdb_path, "tempdir": tmp, "name": f.filename}
    return jsonify({
        "token": token,
        "name": f.filename,
        "driver": driver,
        "devices": tables["devices"],
        "zones": tables["zones"],
    })


@app.route("/api/validate", methods=["POST"])
def api_validate():
    data = request.get_json(force=True)
    problems = core.validate(data.get("devices", {}), data.get("zones", {}))
    return jsonify({"ok": not problems, "problems": problems})


@app.route("/api/apply", methods=["POST"])
def api_apply():
    data = request.get_json(force=True)
    token = data.get("token")
    sess = SESSIONS.get(token)
    if not sess:
        return jsonify({"error": "Session expired — please reload the backup."}), 400
    dev_map = {k: v for k, v in data.get("devices", {}).items() if (v or "").strip()}
    zone_map = {k: v for k, v in data.get("zones", {}).items() if (v or "").strip()}
    if not dev_map and not zone_map:
        return jsonify({"error": "No new labels entered — nothing to apply."}), 400
    stem = os.path.splitext(os.path.basename(sess["name"]))[0]
    out_dir = tempfile.mkdtemp(prefix="svout_")
    out_path = os.path.join(out_dir, f"{stem}_relabeled.svdb")
    try:
        summary = core.relabel(sess["svdb_path"], dev_map, zone_map, out_path)
    except ValueError as e:  # validation failure
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"Relabel failed: {e}"}), 500
    dl = uuid.uuid4().hex
    OUTPUTS[dl] = out_path
    return jsonify({
        "download": dl,
        "filename": f"{stem}_relabeled.svdb",
        "devices_changed": summary["devices_changed"],
        "zones_changed": summary["zones_changed"],
    })


@app.route("/api/download/<dl>")
def api_download(dl: str):
    path = OUTPUTS.get(dl)
    if not path or not os.path.exists(path):
        return "Not found", 404
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


# ── Single-page UI (inline so the tool packages as one file) ─────────────────
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SensorView Backup Relabeler</title>
<style>
  :root{--teal:#00778b;--ink:#1a2530;--bg:#f4f6f8;--line:#d5dde3;--bad:#c0392b;--ok:#1e8449;}
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.45 "Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--bg)}
  header{background:var(--teal);color:#fff;padding:14px 22px}
  header h1{margin:0;font-size:18px;font-weight:600}
  header p{margin:3px 0 0;font-size:12.5px;opacity:.9}
  main{max-width:1080px;margin:0 auto;padding:22px}
  .card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:18px;margin-bottom:18px}
  .note{background:#eef6f8;border-left:4px solid var(--teal);padding:10px 14px;border-radius:4px;font-size:13px;margin-bottom:16px}
  button{font:inherit;background:var(--teal);color:#fff;border:0;border-radius:6px;padding:8px 16px;cursor:pointer}
  button.secondary{background:#fff;color:var(--teal);border:1px solid var(--teal)}
  button:disabled{opacity:.45;cursor:not-allowed}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .tabs{display:flex;gap:6px;margin:6px 0 12px}
  .tabs button{background:#e7edf1;color:var(--ink)}
  .tabs button.active{background:var(--teal);color:#fff}
  input[type=text]{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:5px;width:100%}
  input.bad{border-color:var(--bad);background:#fdecea}
  table{border-collapse:collapse;width:100%;font-size:13px}
  th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
  th{position:sticky;top:0;background:#fff;z-index:1}
  .scroll{max-height:52vh;overflow:auto;border:1px solid var(--line);border-radius:6px}
  .cur{color:#5a6b78;font-family:Consolas,monospace;font-size:12px}
  .muted{color:#5a6b78;font-size:12.5px}
  #status{font-size:13px}
  .pill{display:inline-block;background:#e7edf1;border-radius:12px;padding:1px 9px;font-size:12px;margin-left:6px}
  .problems{color:var(--bad);font-size:12.5px;white-space:pre-wrap;margin-top:8px}
  .hidden{display:none}
  a.dl{display:inline-block;margin-top:10px;background:var(--ok);color:#fff;padding:9px 16px;border-radius:6px;text-decoration:none}
</style></head><body>
<header><h1>SensorView Backup Relabeler</h1>
<p>Local tool — the backup stays on this machine. The original file is never modified.</p></header>
<main>
  <div class="note"><b>How it works:</b> 1) Load a <code>.svdb</code> backup. 2) Enter new labels in the table, or download the CSV template, fill it, and upload it. 3) Validate. 4) Apply &amp; download the rebuilt <code>_relabeled.svdb</code>, then import it in SensorView (Import → Synchronize if labels don't push → do <b>not</b> Clear).</div>

  <div class="card" id="loadCard">
    <div class="row">
      <input type="file" id="file" accept=".svdb,.svdo">
      <button id="loadBtn">Load backup</button>
      <span id="loadMsg" class="muted"></span>
    </div>
  </div>

  <div class="card hidden" id="editCard">
    <div class="row" style="justify-content:space-between">
      <div><b id="fileName"></b><span class="pill" id="devCount"></span><span class="pill" id="zoneCount"></span></div>
      <div class="row">
        <button class="secondary" id="tplBtn">Download CSV template</button>
        <label class="secondary" style="border:1px solid var(--teal);color:var(--teal);border-radius:6px;padding:8px 16px;cursor:pointer">Upload filled CSV<input type="file" id="csv" accept=".csv" class="hidden"></label>
      </div>
    </div>
    <div class="tabs">
      <button data-tab="devices" class="active">Devices</button>
      <button data-tab="zones">Zones</button>
    </div>
    <div class="row" style="margin-bottom:8px">
      <input type="text" id="filter" placeholder="Filter rows…" style="max-width:280px">
      <span class="muted" id="editHint">Leave a New Label blank to keep the current one.</span>
    </div>
    <div class="scroll"><table><thead><tr><th style="width:120px">ID</th><th>Current label</th><th style="width:38%">New label</th></tr></thead><tbody id="tbody"></tbody></table></div>
    <div class="row" style="margin-top:14px">
      <button id="validateBtn">Validate</button>
      <button id="applyBtn">Apply &amp; download</button>
      <span id="status"></span>
    </div>
    <div class="problems" id="problems"></div>
    <div id="dlWrap"></div>
  </div>
</main>
<script>
const S={token:null,name:null,devices:[],zones:[],labels:{devices:{},zones:{}},tab:"devices"};
const $=id=>document.getElementById(id);
function esc(s){return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

$("loadBtn").onclick=async()=>{
  const f=$("file").files[0]; if(!f){$("loadMsg").textContent="Choose a .svdb file first.";return;}
  $("loadBtn").disabled=true;$("loadMsg").textContent="Loading… (large backups take a few seconds)";
  const fd=new FormData(); fd.append("svdb",f);
  const r=await fetch("/api/load",{method:"POST",body:fd}); const d=await r.json();
  $("loadBtn").disabled=false;
  if(!r.ok){$("loadMsg").textContent="⚠ "+d.error;return;}
  S.token=d.token;S.name=d.name;S.devices=d.devices;S.zones=d.zones;S.labels={devices:{},zones:{}};
  $("loadMsg").textContent="Loaded with driver: "+d.driver;
  $("fileName").textContent=d.name;
  $("devCount").textContent=d.devices.length+" devices";
  $("zoneCount").textContent=d.zones.length+" zones";
  $("editCard").classList.remove("hidden");
  renderTable();
};

function rows(){return S.tab==="devices"?S.devices:S.zones;}
function renderTable(){
  const flt=$("filter").value.toLowerCase();
  const store=S.labels[S.tab];
  const html=rows().filter(x=>!flt||x.id.toLowerCase().includes(flt)||(x.current||"").toLowerCase().includes(flt)||(store[x.id]||"").toLowerCase().includes(flt))
    .map(x=>`<tr><td class="cur">${esc(x.id)}</td><td class="cur">${esc(x.current)}</td>
      <td><input type="text" data-id="${esc(x.id)}" value="${esc(store[x.id]||"")}"></td></tr>`).join("");
  $("tbody").innerHTML=html;
  $("tbody").querySelectorAll("input").forEach(inp=>{
    inp.oninput=()=>{ const v=inp.value; if(v.trim())store[inp.dataset.id]=v; else delete store[inp.dataset.id]; inp.classList.remove("bad"); };
  });
}
$("filter").oninput=renderTable;
document.querySelectorAll(".tabs button").forEach(b=>b.onclick=()=>{
  document.querySelectorAll(".tabs button").forEach(x=>x.classList.remove("active"));
  b.classList.add("active"); S.tab=b.dataset.tab; $("filter").value=""; renderTable();
});

$("tplBtn").onclick=()=>{
  const which=S.tab, hdrId=which==="devices"?"DeviceID":"ZoneID", hdrCur=which==="devices"?"CurrentLabel":"CurrentName", hdrNew=which==="devices"?"ProposedLabel":"ProposedName";
  const store=S.labels[which];
  let csv=hdrId+","+hdrCur+","+hdrNew+"\n";
  rows().forEach(x=>{csv+=`${x.id},${csvq(x.current)},${csvq(store[x.id]||"")}\n`;});
  const blob=new Blob([csv],{type:"text/csv"}); const a=document.createElement("a");
  a.href=URL.createObjectURL(blob); a.download=which+"_rename_template.csv"; a.click();
};
function csvq(s){s=s||"";return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}

$("csv").onchange=async e=>{
  const f=e.target.files[0]; if(!f)return;
  const text=await f.text(); const lines=text.split(/\r?\n/).filter(l=>l.trim());
  if(!lines.length)return;
  const head=parseCsvLine(lines[0]).map(h=>h.trim());
  const iId=head.findIndex(h=>/^(DeviceID|ZoneID)$/i.test(h));
  const iNew=head.findIndex(h=>/^(ProposedLabel|ProposedName)$/i.test(h));
  if(iId<0||iNew<0){alert("CSV needs an ID column (DeviceID/ZoneID) and a ProposedLabel/ProposedName column.");return;}
  const which=/ZoneID/i.test(head[iId])?"zones":"devices"; const store=S.labels[which];
  let n=0;
  for(let i=1;i<lines.length;i++){const c=parseCsvLine(lines[i]);const id=(c[iId]||"").trim();const nl=(c[iNew]||"").trim();
    if(id&&nl){store[id]=nl;n++;}}
  S.tab=which; document.querySelectorAll(".tabs button").forEach(x=>x.classList.toggle("active",x.dataset.tab===which));
  renderTable(); $("status").textContent=`Loaded ${n} new ${which} labels from CSV.`;
};
function parseCsvLine(line){const out=[];let cur="",q=false;for(let i=0;i<line.length;i++){const ch=line[i];
  if(q){if(ch=='"'){if(line[i+1]=='"'){cur+='"';i++;}else q=false;}else cur+=ch;}
  else{if(ch=='"')q=true;else if(ch==","){out.push(cur);cur="";}else cur+=ch;}}
  out.push(cur);return out;}

$("validateBtn").onclick=async()=>{
  $("problems").textContent=""; $("status").textContent="Validating…";
  const r=await fetch("/api/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({devices:S.labels.devices,zones:S.labels.zones})});
  const d=await r.json();
  markBad(d.problems);
  if(d.ok){$("status").textContent="✓ Valid — "+countFilled()+" labels ready.";$("status").style.color="var(--ok)";}
  else{$("status").textContent="✗ "+d.problems.length+" problem(s):";$("status").style.color="var(--bad)";$("problems").textContent=d.problems.join("\n");}
};
function countFilled(){return Object.keys(S.labels.devices).length+Object.keys(S.labels.zones).length;}
function markBad(problems){
  document.querySelectorAll("#tbody input").forEach(i=>i.classList.remove("bad"));
  const badLabels=new Set((problems||[]).map(p=>{const m=p.match(/'([^']+)'/);return m?m[1]:null;}).filter(Boolean));
  document.querySelectorAll("#tbody input").forEach(i=>{if(badLabels.has(i.value.trim()))i.classList.add("bad");});
}

$("applyBtn").onclick=async()=>{
  if(!countFilled()){$("status").textContent="Enter at least one new label first.";return;}
  $("applyBtn").disabled=true;$("status").style.color="";$("status").textContent="Applying and rebuilding backup…";$("dlWrap").innerHTML="";
  const r=await fetch("/api/apply",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:S.token,devices:S.labels.devices,zones:S.labels.zones})});
  const d=await r.json(); $("applyBtn").disabled=false;
  if(!r.ok){$("status").style.color="var(--bad)";$("status").textContent="✗ "+d.error;$("problems").textContent=d.error;return;}
  $("status").style.color="var(--ok)";
  $("status").textContent=`✓ Rebuilt: ${d.devices_changed} devices, ${d.zones_changed} zones updated.`;
  $("dlWrap").innerHTML=`<a class="dl" href="/api/download/${d.download}">⬇ Download ${esc(d.filename)}</a>`;
};
</script>
</body></html>"""


def _open_browser():
    webbrowser.open("http://127.0.0.1:5000")


if __name__ == "__main__":
    # Bind to localhost only — the backup contains hashed passwords and must not leave the machine.
    Timer(1.0, _open_browser).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
