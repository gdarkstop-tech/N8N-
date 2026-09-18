import json, glob, re, subprocess, sys, os

# The one audit schema every branch in every workflow must write.
AUDIT_COLS = ["request_id", "dedupe_key", "ts", "channel", "action", "tier",
              "approver_id", "subject", "target", "importance", "decision",
              "outcome", "detail"]

OUT = __file__.rsplit('/',1)[0] + '/workflows/'
TMP = '/tmp/alia-jscheck'
os.makedirs(TMP, exist_ok=True)
has_node = subprocess.run(["which", "node"], capture_output=True).returncode == 0

fail = 0
for p in sorted(glob.glob(OUT + "*.json")):
    f = p.split("/")[-1]
    d = json.load(open(p))
    names = {n["name"] for n in d["nodes"]}
    probs = []

    # --- graph integrity ---
    for src, v in d["connections"].items():
        if src not in names:
            probs.append("connection source missing: " + src)
        for key, brs in v.items():
            for b in brs:
                for c in b:
                    if c["node"] not in names:
                        probs.append("connection target missing: " + c["node"])

    # --- every $('X') resolves ---
    blob = json.dumps(d)
    for ref in sorted(set(re.findall(r"\$\('([^']+)'\)", blob))):
        if ref not in names:
            probs.append("expression references missing node: $('%s')" % ref)

    # --- reachability ---
    targets = {c["node"] for v in d["connections"].values() for br in v.values() for b in br for c in b}
    for n in d["nodes"]:
        if n["name"] not in targets and "rigger" not in n["type"] and "lmChat" not in n["type"]:
            probs.append("unreachable node: " + n["name"])

    # --- duplicates ---
    ids = [n["id"] for n in d["nodes"]]
    if len(ids) != len(set(ids)):
        probs.append("duplicate node ids: %s" % sorted({i for i in ids if ids.count(i) > 1}))
    if len(names) != len(d["nodes"]):
        probs.append("duplicate node names")

    # --- no Google Sheets anywhere ---
    for n in d["nodes"]:
        if "googleSheets" in n["type"]:
            probs.append("Google Sheets node still present: " + n["name"])

    # --- audit column consistency: every Outcome node emits exactly AUDIT_COLS ---
    outs = [n for n in d["nodes"] if n["name"].startswith("Outcome:")]
    if not outs:
        probs.append("no Outcome nodes found")
    for n in outs:
        keys = [a["name"] for a in n["parameters"]["assignments"]["assignments"]]
        if keys != AUDIT_COLS:
            probs.append("column mismatch in %s: %s" % (n["name"], set(keys) ^ set(AUDIT_COLS)))

    # --- every Outcome feeds the single shared Audit Log ---
    audits = [n for n in d["nodes"] if n["type"] == "n8n-nodes-base.dataTable"
              and n["parameters"].get("operation") == "insert"]
    if len(audits) != 1:
        probs.append("expected exactly 1 audit insert node, found %d" % len(audits))
    for n in outs:
        tgt = d["connections"].get(n["name"], {}).get("main", [[]])[0]
        if not tgt or tgt[0]["node"] != "Audit Log":
            probs.append("%s does not feed Audit Log" % n["name"])

    # --- Telegram approval hardening ---
    for n in d["nodes"]:
        if n["type"] == "n8n-nodes-base.telegram" and n["parameters"].get("operation") == "sendAndWait":
            pr = n["parameters"]
            if pr.get("chatApproval") is not True:
                probs.append("chatApproval not enabled on " + n["name"])
            if not pr.get("approverIds"):
                probs.append("approverIds empty on " + n["name"])
            if not pr.get("unauthorizedReplyText"):
                probs.append("unauthorizedReplyText missing on " + n["name"])
            lw = pr.get("options", {}).get("limitWaitTime")
            if not isinstance(lw, dict) or "values" not in lw:
                probs.append("limitWaitTime not a fixedCollection on " + n["name"])
            if pr.get("options", {}).get("appendAttribution") is not False:
                probs.append("appendAttribution not disabled on " + n["name"])

    # --- JS syntax check on every Code node ---
    if has_node:
        for n in d["nodes"]:
            if n["type"] == "n8n-nodes-base.code":
                src = n["parameters"]["jsCode"]
                path = TMP + "/" + re.sub(r"\W+", "_", f + "_" + n["name"]) + ".js"
                # n8n Code nodes run as an async function body; wrap to match.
                open(path, "w").write("(async function(){\n" + src + "\n})")
                r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
                if r.returncode != 0:
                    probs.append("JS syntax error in %s: %s" % (n["name"], r.stderr.strip().split("\n")[0]))

    print(("OK  " if not probs else "FAIL") + " %-46s nodes=%d outcomes=%d" % (f, len(d["nodes"]), len(outs)))
    for x in probs:
        print("       -> " + x)
        fail += 1

print("\nnode available for JS check:", has_node)
print("RESULT:", "ALL PASS" if fail == 0 else "%d PROBLEM(S)" % fail)
