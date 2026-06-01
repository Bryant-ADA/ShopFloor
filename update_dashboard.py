import urllib.request
import urllib.error
import json
import os
from datetime import datetime

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJOYW1lIjoiQ2xhdWRlIiwiUmV2b2NhdGlvbklkIjoiNjdjODMzYjEtMDZkZS00YjI5LTljZGMtNjdkNjcwZGJjYTllIiwiZXhwIjo0ODk5MTM5MjAwLCJpc3MiOiJhZGFlbnQuZnVsY3J1bXByby5jb20iLCJhdWQiOiJhZGFlbnQifQ.z9I8KmwmnebrP7GVg_NrVgCdUeSTZfpj340cPno8ZhU"
BASE = "https://adaent.fulcrumpro.com/api"

def fulcrum_post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def classify(job):
    item = (job.get("itemNumber") or job.get("itemName") or "").upper()
    comp = job.get("completedOperationCount", 0)
    total = job.get("totalOperationCount", 1) or 1
    pct = comp / total
    co = (job.get("companyName") or "").lower()

    # Running operations take priority
    running = job.get("runningOperations", [])
    if running:
        op = (running[0].get("name") or "").lower()
        if "laser cut tube" in op or "tube laser" in op: return "Tube Laser"
        if "laser cut sheet" in op or "sheet laser" in op: return "Sheet Laser"
        if "robot" in op or "weld" in op: return "Welding"
        if "coat" in op: return "Hot For Coating"
        if "palletize" in op: return "Shipping"
        if "brake" in op or "bend" in op: return "Brake & Bend"
        if "shear" in op: return "Shear"
        if "turret" in op: return "Turret"

    if pct >= 0.85 and total > 1: return "Shipping"

    # Single-op coating items
    if total == 1 and any(item.startswith(p) for p in ["622-","625-","630-","633-","634-","638-","642-","651-","652-","653-","660-","733-"]):
        return "Hot For Coating"

    # RACS company
    if "racs" in co:
        if pct < 0.4: return "Weld Ag/RACS"
        if pct < 0.85: return "Hot For Coating"
        return "Shipping"

    # Premier Polysteel
    if "premier" in co:
        if pct < 0.5: return "Welding"
        if pct < 0.85: return "Hot For Coating"
        return "Shipping"

    # Tube items (220- 230- 102-)
    if any(item.startswith(p) for p in ["220-","230-","102-","304-","303-","302-"]):
        if pct < 0.4: return "Tube Laser"
        if pct < 0.75: return "Brake & Bend"
        return "Tube Laser"

    # AG multi-op welding items (622/625/630/633/634/638/642/652/653/660/733 multi-op)
    if any(item.startswith(p) for p in ["622-","625-","630-","633-","634-","638-","642-","651-","652-","653-","660-","733-"]):
        if total > 1:
            if pct < 0.5: return "Welding"
            return "Hot For Coating"

    # BCI Burke (B0xx-)
    if item.startswith("B") and len(item) > 3 and item[1:4].isdigit():
        if comp <= 1: return "Cut Bar & Chop Saw"
        if pct < 0.75: return "Hot For Coating"
        return "Shipping"

    # Custom/RACS by item name patterns
    if total >= 5:
        if pct < 0.3: return "Weld Ag/RACS"
        if pct < 0.7: return "Welding"
        if pct < 0.85: return "Hot For Coating"
        return "Shipping"

    if pct == 0: return "Hot For Coating"
    if pct < 0.5: return "Welding"
    if pct < 0.85: return "Hot For Coating"
    return "Shipping"

def fmt_d(d):
    if not d: return ""
    return d[:10]

def srt_key(j):
    late = 0 if j["l"] else 1
    pri = {"High":0,"Moderate":1,"Low":2}.get(j["p"],1)
    return (1 if j.get("wo") else 0, late, pri, j["d"])

print("Fetching jobs from Fulcrum...")
p0 = fulcrum_post("/jobs/search", {"status":"In Progress","page":{"skip":0,"take":100},"sortBy":"dueDate"})
p1 = fulcrum_post("/jobs/search", {"status":"In Progress","page":{"skip":100,"take":100},"sortBy":"dueDate"})
all_jobs = (p0.get("jobs") or []) + (p1.get("jobs") or [])
print(f"  Got {len(all_jobs)} jobs")

print("Fetching work orders from Fulcrum...")
wo_res = fulcrum_post("/workorders/search", {"status":"Open","page":{"skip":0,"take":100}})
all_wos = wo_res.get("workOrders") or []
print(f"  Got {len(all_wos)} work orders")

WCS = ["Welding","Weld Ag/RACS","Brake & Bend","Cut Bar & Chop Saw",
       "Hot For Coating","Punch, Nip & Roll","Turret","Shear",
       "Tube Laser","Sheet Laser","Wire & Spot Weld","Shipping"]

board = {wc: [] for wc in WCS}
total_late = 0
total_hi = 0

for job in all_jobs:
    col = classify(job)
    if col not in board: col = "Hot For Coating"
    entry = {
        "n": job.get("jobName","?"),
        "p": job.get("priority","Moderate"),
        "d": fmt_d(job.get("productionDueDate","")),
        "l": bool(job.get("isLate")),
        "wo": False
    }
    board[col].append(entry)
    if job.get("isLate"): total_late += 1
    if job.get("priority") == "High": total_hi += 1

# WO mapping based on known active operations
WO_MAP = {
    1907: {"col":"Hot For Coating","d":"2026-06-02","l":False},
    1657: {"col":"Welding","d":"2026-05-05","l":True},
    1751: {"col":"Hot For Coating","d":"2026-05-18","l":True},
    1917: {"col":"Brake & Bend","d":"2026-06-17","l":True},
    1959: {"col":"Hot For Coating","d":"2026-04-20","l":True},
    1806: {"col":"Sheet Laser","d":"2026-05-14","l":True},
    1841: {"col":"Sheet Laser","d":"2026-05-11","l":True},
    1910: {"col":"Sheet Laser","d":"2026-05-13","l":True},
    1860: {"col":"Sheet Laser","d":"2026-05-13","l":True},
    1790: {"col":"Shipping","d":"2026-05-27","l":True},
    1496: {"col":"Shipping","d":"2026-04-09","l":True},
}

for wo in all_wos:
    num = wo.get("number",0)
    if not num: continue
    known = WO_MAP.get(num)
    col = known["col"] if known else "Hot For Coating"
    d = known["d"] if known else fmt_d(wo.get("productionDueDate",""))
    l = known["l"] if known else bool(wo.get("isScheduledLate"))
    if col in board:
        board[col].append({"n":f"WO-{num}","p":"Moderate","d":d,"l":l,"wo":True})

for wc in WCS:
    board[wc].sort(key=srt_key)

now = datetime.now().strftime("%B %d, %Y — %I:%M %p")

# Build JS data block
js_data = f"const DATA_UPDATED = '{now}';\n"
js_data += f"const STATS = {{late:{total_late},total:{len(all_jobs)},hi:{total_hi}}};\n\n"
js_data += "const RAW={\n"
for wc in WCS:
    jobs = board[wc]
    js_data += f'"{wc}":[\n'
    for j in jobs:
        n = j['n'].replace("'", "\\'")
        js_data += f"  {{n:\"{n}\",p:\"{j['p']}\",d:\"{j['d']}\",l:{'true' if j['l'] else 'false'}{',wo:true' if j.get('wo') else ''}}},\n"
    js_data += "],\n"
js_data += "};"

# Read template
with open("index_template.html", "r", encoding="utf-8") as f:
    template = f.read()

output = template.replace("%%DATA_BLOCK%%", js_data)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(output)

print(f"Done! index.html written with {len(all_jobs)} jobs, {len(all_wos)} WOs, updated {now}")
