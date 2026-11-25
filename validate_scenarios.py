#!/usr/bin/env python3
"""Acceptance checks for a scenarios JSON batch (see the Auto Funding Test Data PRD).

Usage:
    python3 validate_scenarios.py [scenarios.txt]
Exits 1 and lists every failure if any MUST rule is broken.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

SRC = sys.argv[1] if len(sys.argv) > 1 else "scenarios.txt"
d = json.load(open(SRC, encoding="utf-8"))
apps = d["applications"]
gen = datetime.fromisoformat(d["generatedAt"])
ts = datetime.fromisoformat
fails = []


def check(ok, where, msg):
    if not ok:
        fails.append(f"{where}: {msg}")


FAMILY = {
    "AUTO_APPROVED_": ("READY_TO_FUND", "AUTO_APPROVED_FOR_FUNDING"),
    "FUNDED_": ("FUNDED", "ACH_DISBURSED"),
    "STIP_DEALER_": ("STIPULATION_ACTION_REQUIRED", "STIPULATION_SENT"),
    "STIP_CUSTOMER_": ("STIPULATION_ACTION_REQUIRED", "STIPULATION_SENT"),
    "AGENT_VERIFY_": ("PENDING_AGENT_VERIFICATION", "ROUTED_TO_AGENT_OCR_REVIEW"),
    "EXPIRED_": ("EXPIRED", "APPLICATION_EXPIRED"),
    "EXCEPTION_HOLD_": ("EXCEPTION_HOLD", "STATUS_UPDATED"),
    "WITHDRAWN_": ("WITHDRAWN", "STATUS_UPDATED"),
    "DECLINED_": ("DECLINED", "STATUS_UPDATED"),
}
SLOT = {"VEHICLE_CROSS_DOC": "01", "LENDER_IDENTITY": "02", "TILA_AND_ITEMIZATION": "03",
        "GAP_COMPLIANCE": "04", "BORROWER_STIPULATION": "05"}
FUNDER = {"VEHICLE_CROSS_DOC": "S. Chen", "LENDER_IDENTITY": "R. Patel", "TILA_AND_ITEMIZATION": "J. Morales",
          "GAP_COMPLIANCE": "A. Brooks", "BORROWER_STIPULATION": "M. Vance-Kerr"}
ENGINE = {"VEHICLE_CROSS_DOC": "DocCrossCheck-OCR-v4", "LENDER_IDENTITY": "ContractRuleEngine-v2",
          "TILA_AND_ITEMIZATION": "TilaMathVerifier-v3", "GAP_COMPLIANCE": "ComplianceFormMatrix-v2",
          "BORROWER_STIPULATION": "Equifax-TWN-Payroll-v3"}
QUEUE = {"DEALER": "DEALER_PORTAL_RECONTRACT", "CUSTOMER": "BORROWER_UPLOAD_PORTAL",
         "INTERNAL_AGENT": "FUNDER_MANUAL_OCR_REVIEW"}
MODE = {"VERIFIED": "AUTOMATION", "STIPULATED": "STIPULATION", "EXPIRED": "STIPULATION",
        "PENDING_AGENT_VERIFICATION": "AGENT_REVIEW"}
OPEN = {"READY_TO_FUND", "STIPULATION_ACTION_REQUIRED", "PENDING_AGENT_VERIFICATION"}
NO_OPEN_TASKS = {"READY_TO_FUND", "FUNDED", "EXCEPTION_HOLD", "WITHDRAWN", "DECLINED"}
STATES = ["TX", "CA", "FL", "GA", "NC", "OH", "IL", "AZ", "WA", "CO"]
CHANNEL_GATEWAY = {"DEALERTRACK": "DEALERTRACK Intake Gateway", "ROUTEONE": "ROUTEONE Intake Gateway",
                   "CUDL": "CUDL Intake Gateway"}

# --- file header ---
check(d["totalScenarios"] == len(apps), "header", "totalScenarios != number of applications")
check(d["statusBreakdown"] == dict(Counter(a["overallFundingStatus"] for a in apps)),
      "header", "statusBreakdown does not match the records")

# --- uniqueness across the dataset ---
ids = defaultdict(list)
actor_roles = defaultdict(set)
for a in apps:
    ids["applicationId"].append(a["applicationId"])
    ids["dealNumber"].append(a["dealNumber"])
    ids["vin"].append(a["vehicle"]["vin"])
    ids["requirementId"] += [r["requirementId"] for r in a["requirements"]]
    ids["eventId"] += [e["eventId"] for e in a["activityLog"]]
    ids["itemId"] += [i["itemId"] for k in ("frontEndProducts", "backEndProducts", "amountsPaidToOthers")
                      for i in a["riscItemization"][k]]
for k, v in ids.items():
    dup = [x for x, c in Counter(v).items() if c > 1]
    check(not dup, "dataset", f"duplicate {k}: {dup[:5]}")

for a in apps:
    w = a["applicationId"]
    n = int(w[4:]) - 9084700
    nnn = f"{n:03d}"
    status, code = a["overallFundingStatus"], a["scenarioCode"]
    fam = next((p for p in FAMILY if code.startswith(p)), None)
    check(fam is not None, w, f"scenarioCode {code} has no known family prefix")
    if fam is None:
        continue
    want_status, want_event = FAMILY[fam]

    # IDs and description
    check(a["dealNumber"] == f"AL-2026-{88400 + n}", w, "dealNumber does not follow N")
    check(a["applicant"]["applicantId"] == f"apl_{4400 + n}", w, "applicantId does not follow N")
    check(a["vehicle"]["vehicleId"] == f"veh_{7700 + n}", w, "vehicleId does not follow N")
    check(a["loanTermsApproved"]["approvalId"] == f"apr_{55900 + n}", w, "approvalId does not follow N")
    check(a["scenarioDescription"].startswith(f"[Scenario #{nnn} | {code} |"), w, "scenarioDescription prefix")
    check(status == want_status, w, f"status {status} but family {fam} needs {want_status}")
    check(a["stateCode"] == STATES[(n - 1) % 10], w, "stateCode out of rotation")

    # dates and SLA
    sub = ts(a["submittedAt"])
    check(ts(a["expiresAt"]) == sub + timedelta(days=7), w, "expiresAt != submittedAt + 7 days")
    check(sub <= gen, w, "submittedAt after generatedAt")
    if status in OPEN:
        check(ts(a["expiresAt"]) > gen, w, "open record already past expiresAt")
    else:
        check(a["sla"]["minutesRemaining"] == 0 or status == "EXCEPTION_HOLD", w, "terminal record with SLA minutes")
    check(a["sla"]["cutoffAt"] == gen.strftime("%Y-%m-%dT17:00:00") + d["generatedAt"][19:], w,
          "cutoffAt is not 17:00 on the generatedAt date")

    # applicant / vehicle
    ap, vh = a["applicant"], a["vehicle"]
    check(re.fullmatch(r"\d{4}", ap["ssnLast4"]) is not None, w, "ssnLast4 not 4 digits")
    check(ap["statedIncome"]["annualGrossAmount"] == 12 * ap["statedIncome"]["monthlyGrossAmount"], w,
          "annual income != 12 x monthly")
    check(ap["email"].endswith("@example.com"), w, "email not on example.com")
    check(re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vh["vin"]) is not None, w, "VIN not 17 valid characters")
    check(vh["titleAndLien"]["titleState"] == a["stateCode"], w, "titleState != stateCode")

    # loan math
    lt = a["loanTermsApproved"]
    cs = lt["contractSummary"]
    ri = a["riscItemization"]
    s = lambda k: round(sum(i["amount"] for i in ri[k]), 2)
    check(s("frontEndProducts") == cs["totalFrontEndProductsAmount"], w, "front-end items != total")
    check(s("backEndProducts") == cs["totalBackEndProductsAmount"], w, "back-end items != total")
    check(s("amountsPaidToOthers") == cs["totalOtherAmountsPaidToOthers"], w, "paid-to-others items != total")
    expected = round(cs["cashPriceOfVehicle"] - cs["downPaymentCash"] - cs["netTradeInAllowance"]
                     + cs["totalFrontEndProductsAmount"] + cs["totalBackEndProductsAmount"]
                     + cs["totalOtherAmountsPaidToOthers"], 2)
    rec = lt["amountFinancedReconciliation"]
    check(rec["expectedAmountFinanced"] == expected, w, "expectedAmountFinanced != formula")
    check(rec["contractAmountFinanced"] == cs["amountFinanced"], w, "contractAmountFinanced != contract")
    check(round(rec["varianceAmount"], 2) == round(cs["amountFinanced"] - expected, 2), w, "varianceAmount wrong")
    check(rec["isReconciled"] == (rec["varianceAmount"] == 0), w, "isReconciled inconsistent with variance")
    check(abs(cs["totalOfPayments"] - (cs["amountFinanced"] + cs["financeCharge"])) < 0.01, w,
          "totalOfPayments != amountFinanced + financeCharge")
    fc_var = lt["tilaMathCheck"].get("financeChargeVarianceAmount") or 0
    check(abs(cs["totalOfPayments"] - lt["estimatedMonthlyPayment"] * lt["approvedTermMonths"] - fc_var) < 0.01, w,
          "totalOfPayments != payment x term + financeChargeVarianceAmount")
    check((lt["tilaMathCheck"]["status"] == "PASSED") == (fc_var == 0 and rec["isReconciled"]
          and cs["totalBackEndProductsAmount"] <= lt["maxBackEndProductCap"]), w,
          "tilaMathCheck.status inconsistent with the math")
    check(abs(cs["totalSalePrice"] - (cs["totalOfPayments"] + cs["downPaymentCash"] + cs["netTradeInAllowance"])) < 0.01,
          w, "totalSalePrice != totalOfPayments + down + trade")
    check(abs(lt["calculatedLtvPercent"] - round(cs["amountFinanced"] / cs["cashPriceOfVehicle"] * 100, 1)) < 0.06,
          w, "calculatedLtvPercent != AF / cash price")
    check(cs["amountFinanced"] <= lt["maxAmountFinanced"], w, "amountFinanced over maxAmountFinanced")
    if code != "STIP_DEALER_BACKEND_PRODUCT_EXCEEDS_APPROVAL_CAP":
        check(cs["totalBackEndProductsAmount"] <= lt["maxBackEndProductCap"], w, "back-end over tier cap")

    # tasks
    reqs = {r["requirementId"]: r for r in a["requirements"]}
    open_tasks = [r for r in a["requirements"] if r["status"] != "VERIFIED"]
    for r in a["requirements"]:
        rw = f"{w}/{r['requirementId']}"
        cat, st, ful = r["category"], r["status"], r["fulfillment"]
        check(r["requirementId"] == f"req_{nnn}_{SLOT[cat]}", rw, "requirementId slot wrong")
        check(ful["mode"] == MODE[st], rw, f"fulfillment.mode {ful['mode']} for status {st}")
        if st == "VERIFIED":
            check(ful["automatedEngine"] == ENGINE[cat], rw, "verified by the wrong engine")
            check(ful["resolvedAt"] == a["submittedAt"], rw, "resolvedAt != submittedAt")
            check(r["stipulation"] is None, rw, "verified task carries a stipulation")
            check(all(c["isMatch"] for c in r["fieldComparisons"]), rw, "verified task has a mismatch")
            check(all(not o["requiresAgentOcrConfirmation"] for o in r["ocrEvidence"]), rw,
                  "verified task still needs agent OCR confirmation")
        else:
            check(ful["automatedEngine"] is None and ful["resolvedAt"] is None, rw, "open task has an engine or resolvedAt")
            sp = r["stipulation"]
            check(sp is not None, rw, "open task has no stipulation")
            if sp:
                check(sp["assignedQueue"] == QUEUE.get(sp["actionTarget"]), rw, "queue does not match target")
                check(ts(sp["dueAt"]) == ts(sp["requestedAt"]) + timedelta(days=7), rw, "dueAt != requestedAt + 7 days")
                if fam == "STIP_DEALER_":
                    check(sp["actionTarget"] == "DEALER", rw, "dealer stip not targeted at DEALER")
                if fam == "STIP_CUSTOMER_":
                    check(sp["actionTarget"] == "CUSTOMER", rw, "customer stip not targeted at CUSTOMER")
                if fam == "AGENT_VERIFY_":
                    check(sp["actionTarget"] == "INTERNAL_AGENT", rw, "agent review not targeted at INTERNAL_AGENT")
            if st == "EXPIRED":
                check(status == "EXPIRED", rw, "EXPIRED task on a record that is not EXPIRED")
            if st == "PENDING_AGENT_VERIFICATION":
                check(any(o["requiresAgentOcrConfirmation"] for o in r["ocrEvidence"]), rw,
                      "agent review without an OCR item needing confirmation")
    if status in NO_OPEN_TASKS:
        check(not open_tasks, w, f"{status} record has open tasks")
    if fam in ("STIP_DEALER_", "STIP_CUSTOMER_", "AGENT_VERIFY_"):
        check(len(open_tasks) == 1, w, f"{fam} record needs exactly 1 open task, has {len(open_tasks)}")
    check(len(open_tasks) <= 1, w, "more than one open task")

    # events
    evs = a["activityLog"]
    check([e["timestamp"] for e in evs] == sorted((e["timestamp"] for e in evs), key=ts, reverse=True), w,
          "activityLog not newest first")
    types = [e["eventType"] for e in sorted(evs, key=lambda e: ts(e["timestamp"]))]
    check(types == ["APPLICATION_SUBMITTED", want_event], w, f"events {types}, expected submission + {want_event}")
    for e in evs:
        ew = f"{w}/{e['eventId']}"
        actor_roles[e["actor"]["name"]].add(e["actor"]["actorType"])
        check(sub <= ts(e["timestamp"]) <= gen, ew, "timestamp outside submittedAt..generatedAt")
        md = e.get("metadata") or {}
        if "dealNumber" in md:
            check(md["dealNumber"] == a["dealNumber"], ew, "metadata.dealNumber != dealNumber")
        if e["eventType"] == "APPLICATION_SUBMITTED":
            check(e["actor"]["name"] == CHANNEL_GATEWAY[a["dealer"]["channel"]], ew, "gateway does not match channel")
        rid = e.get("relatedRequirementId")
        if rid:
            check(rid in reqs, ew, "relatedRequirementId not in this record")
            if rid not in reqs:
                continue
            r = reqs[rid]
            check(r["status"] != "VERIFIED", ew, "event points at a VERIFIED task")
            if e["actor"]["actorType"] == "FUNDER_AGENT":
                check(e["actor"]["name"] == FUNDER[r["category"]], ew, "funder is not the category owner")
            if e["eventType"] == "ROUTED_TO_AGENT_OCR_REVIEW":
                check(e["actor"]["name"] == ENGINE[r["category"]], ew, "routing actor is not the category engine")
                check(e["summary"].endswith(f"assigned to {FUNDER[r['category']]}"), ew, "summary names the wrong funder")
        elif e["eventType"] in ("STIPULATION_SENT", "ROUTED_TO_AGENT_OCR_REVIEW"):
            check(False, ew, "task event without relatedRequirementId")

for name, roles in actor_roles.items():
    check(len(roles) == 1, "actors", f"{name} has several actorTypes {roles}")

if fails:
    print(f"FAILED: {len(fails)} problem(s) in {SRC}")
    for f in fails[:200]:
        print("  -", f)
    sys.exit(1)
print(f"PASSED: {len(apps)} applications in {SRC} meet every MUST rule")
