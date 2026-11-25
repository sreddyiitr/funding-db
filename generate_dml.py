#!/usr/bin/env python3
"""Generate DML (INSERT statements) from scenarios.txt for the schema in init/01-schema.sql.

Usage:
    python3 generate_dml.py [scenarios.txt] [init/02-data.sql] [--as-of YYYY-MM-DD] [--dump-json PATH]

--as-of (default: today) rebases every timestamp by whole days so the file's generatedAt date
lands on that date. All date rules are relative to generatedAt, so they keep holding; times of
day (e.g. the 17:00 SLA cutoff) are unchanged. NEW-vehicle model years move with the year.
--dump-json writes the rebased JSON so it can be checked with validate_scenarios.py.

Besides mapping fields, this applies a few data rules:
  * Each task category has exactly one owning funder (FUNDER_BY_CATEGORY) and one
    automated engine. Every task-related activity event uses that category's actor.
  * Every VERIFIED task gets a TASK_VERIFIED event whose actor equals verified_by.
  * Source events that point a stipulation / agent review at an already-VERIFIED task
    are re-pointed to the task the scenario is actually about (SCENARIO_TARGET), and
    that task is flagged accordingly.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

_ap = argparse.ArgumentParser(description="Generate seed DML from a scenarios JSON file.")
_ap.add_argument("src", nargs="?", default="scenarios.txt")
_ap.add_argument("out", nargs="?", default="init/02-data.sql")
_ap.add_argument("--as-of", type=date.fromisoformat, default=date.today(),
                 help="date the data should look current on (default: today)")
_ap.add_argument("--dump-json", help="also write the rebased scenarios JSON here")
ARGS = _ap.parse_args()
SRC, OUT = ARGS.src, ARGS.out

# --- Enum mappings: source values -> schema enums ---------------------------
APP_STATUS = {
    "READY_TO_FUND": "READY_TO_FUND",
    "FUNDED": "FUNDED",
    "EXPIRED": "EXPIRED",
    "EXCEPTION_HOLD": "EXCEPTION_HOLD",
    "WITHDRAWN": "WITHDRAWN",
    "DECLINED": "DECLINED",
    "STIPULATION_ACTION_REQUIRED": "PENDING_STIPULATIONS",
    "PENDING_AGENT_VERIFICATION": "PENDING_AGENT_VERIFICATION",
}
TASK_STATUS = {
    "VERIFIED": "VERIFIED",
    "PENDING_AGENT_VERIFICATION": "PENDING_REVIEW",
    "STIPULATED": "DISCREPANCY_FLAGGED",
    "EXPIRED": "EXPIRED",
}
TASK_CATEGORY = {
    "VEHICLE_CROSS_DOC": "VIN_VERIFICATION",
    "GAP_COMPLIANCE": "GAP_FORM_VERIFICATION",
    "BORROWER_STIPULATION": "INCOME_VERIFICATION",
    "LENDER_IDENTITY": "TITLE_AND_LIEN",
    "TILA_AND_ITEMIZATION": "TILA_RECONCILIATION",
}
ACTOR_ROLE = {
    "SYSTEM": "SYSTEM",
    "FUNDER_AGENT": "FUNDER",
    "DEALER_FI": "DEALER_FI",
    "UNDERWRITER": "UNDERWRITER",
}

# --- Ownership: one funder per task category (keyed by source category) -----
FUNDER_BY_CATEGORY = {
    "VEHICLE_CROSS_DOC": "S. Chen",
    "LENDER_IDENTITY": "R. Patel",
    "TILA_AND_ITEMIZATION": "J. Morales",
    "GAP_COMPLIANCE": "A. Brooks",
    "BORROWER_STIPULATION": "M. Vance-Kerr",
}

# Scenarios whose source events point at the wrong (already VERIFIED) task:
# scenario code -> categories to target, first one present wins.
SCENARIO_TARGET = {
    "STIP_DEALER_MISSING_COAPPLICANT_SIGNATURE_RIC": ["TILA_AND_ITEMIZATION"],
    "STIP_DEALER_ODOMETER_DISCLOSURE_MISSING": ["VEHICLE_CROSS_DOC"],
    "STIP_DEALER_ELT_LIENHOLDER_CODE_INCORRECT": ["LENDER_IDENTITY"],
    "STIP_DEALER_MISSING_BUYERS_ORDER_BREAKDOWN": ["TILA_AND_ITEMIZATION"],
    "STIP_DEALER_STALE_CONTRACT_DATE_OVER_15_DAYS": ["TILA_AND_ITEMIZATION"],
    "STIP_DEALER_TRADE_IN_PAYOFF_LETTER_EXPIRED": ["TILA_AND_ITEMIZATION"],
    "STIP_DEALER_MISSING_DEALER_ASSIGNMENT_ENDORSEMENT": ["LENDER_IDENTITY"],
    "STIP_DEALER_VSC_FORM_NOT_APPROVED_IN_STATE": ["GAP_COMPLIANCE", "TILA_AND_ITEMIZATION"],
    "AGENT_VERIFY_NAME_SUFFIX_MISMATCH_JR_SR": ["BORROWER_STIPULATION"],
    "AGENT_VERIFY_BACKEND_PRODUCT_BUNDLE_PRICING": ["TILA_AND_ITEMIZATION"],
}


# --- SQL literal helpers -----------------------------------------------------
def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def qj(v):
    if v is None:
        return "NULL"
    return q(json.dumps(v, ensure_ascii=False)) + "::jsonb"


def qe(v, enum):
    return f"{q(v)}::{enum}"


def display(ts):
    """'2026-11-24T08:00:00-06:00' -> 'Nov 24, 2026 8:00 AM'."""
    if not ts:
        return None
    d = datetime.fromisoformat(ts)
    return d.strftime("%b %d, %Y ") + d.strftime("%I:%M %p").lstrip("0")


def money(s):
    if not s:
        return None
    m = re.search(r"[\d,]+(?:\.\d+)?", s)
    return float(m.group().replace(",", "")) if m else None


def insert(table, cols, rows):
    if not rows:
        return ""
    body = ",\n".join("  (" + ", ".join(r) + ")" for r in rows)
    return f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{body};\n\n"


# --- Load ---------------------------------------------------------------------
with open(SRC, encoding="utf-8") as f:
    dataset = json.load(f)

# --- Rebase dates: generatedAt's date -> --as-of, by whole days -----------------
TS_KEYS = {"generatedAt", "submittedAt", "expiresAt", "cutoffAt", "resolvedAt", "requestedAt",
           "dueAt", "checkedAt", "timestamp"}
anchor = datetime.fromisoformat(dataset["generatedAt"])
SHIFT = timedelta(days=(ARGS.as_of - anchor.date()).days)
YEAR_SHIFT = ARGS.as_of.year - anchor.year


def _rebase(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in TS_KEYS and isinstance(v, str):
                o[k] = (datetime.fromisoformat(v) + SHIFT).isoformat()
            else:
                _rebase(v)
    elif isinstance(o, list):
        for v in o:
            _rebase(v)


_rebase(dataset)
for _a in dataset["applications"]:
    if YEAR_SHIFT:
        _a["vehicle"]["year"] += YEAR_SHIFT  # keep vehicle age relative to submission
if ARGS.dump_json:
    with open(ARGS.dump_json, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2)
apps = dataset["applications"]

# One engine per category, derived from the data (and checked to be unique).
engines = defaultdict(set)
for a in apps:
    for r in a["requirements"]:
        eng = (r.get("fulfillment") or {}).get("automatedEngine")
        if eng:
            engines[r["category"]].add(eng)
assert all(len(v) == 1 for v in engines.values()), f"multiple engines per category: {dict(engines)}"
ENGINE_BY_CATEGORY = {k: next(iter(v)) for k, v in engines.items()}

actors = {}  # name -> role


def actor(name, role):
    prev = actors.setdefault(name, role)
    assert prev == role, f"actor {name!r} has conflicting roles {prev}/{role}"
    return name


for name in FUNDER_BY_CATEGORY.values():
    actor(name, "FUNDER")
for name in ENGINE_BY_CATEGORY.values():
    actor(name, "SYSTEM")


def fix_misdirected_events(a):
    """Re-point stip / agent-review events that target an already-VERIFIED task."""
    reqs = {r["requirementId"]: r for r in a["requirements"]}
    by_cat = {r["category"]: r for r in a["requirements"]}
    fixes = 0
    for e in a["activityLog"]:
        rid = e.get("relatedRequirementId")
        if not rid or reqs[rid]["status"] != "VERIFIED":
            continue
        if e["eventType"] == "APPLICATION_EXPIRED":
            # link the expiry to the task that lapsed, if any; otherwise it is deal-level
            exp = next((r for r in a["requirements"] if r["status"] == "EXPIRED"), None)
            e["relatedRequirementId"] = exp["requirementId"] if exp else None
            fixes += 1
            continue
        targets = SCENARIO_TARGET.get(a["scenarioCode"])
        assert targets, f"unmapped misdirected event in {a['scenarioCode']}"
        target = next(by_cat[c] for c in targets if c in by_cat)
        e["relatedRequirementId"] = target["requirementId"]
        fixes += 1
        if target["status"] != "VERIFIED":
            continue  # already open; just re-link
        if e["eventType"] == "STIPULATION_SENT":
            target["status"] = "STIPULATED"
            target["fulfillment"] = {"mode": "STIPULATION", "automatedEngine": None, "resolvedAt": None}
            target["stipulation"] = target.get("stipulation") or {
                "reasonCode": a["scenarioCode"],
                "reasonSummary": a["scenarioDescription"].split("] ", 1)[-1].split(" (State:")[0],
                "actionTarget": (e.get("metadata") or {}).get("actionTarget"),
                "requestedAt": e["timestamp"],
            }
            e["summary"] = re.sub(r":.*$", f": {target['title']}", e["summary"])
        elif e["eventType"] == "ROUTED_TO_AGENT_OCR_REVIEW":
            target["status"] = "PENDING_AGENT_VERIFICATION"
            target["fulfillment"] = {"mode": "AGENT_REVIEW", "automatedEngine": None, "resolvedAt": None}
        target["dataCorrected"] = True
    return fixes


dealers, applications, applicants, vehicles, loan_terms = {}, [], [], [], []
tasks, events, risc = [], [], []
dealer_states = defaultdict(Counter)
total_fixes = 0

for a in apps:
    total_fixes += fix_misdirected_events(a)
    app_id = a["applicationId"]
    dl, ap, vh, lt = a["dealer"], a["applicant"], a["vehicle"], a["loanTermsApproved"]
    cs = lt["contractSummary"]
    reqs = {r["category"]: r for r in a["requirements"]}
    req_by_id = {r["requirementId"]: r for r in a["requirements"]}

    # dealers (deduplicated; state = most common application state for dealer)
    dealer_states[dl["dealerId"]][a["stateCode"]] += 1
    dealers.setdefault(dl["dealerId"], {
        "legal_name": dl["legalName"],
        "dba_name": dl.get("dbaName"),
        "elt": vh["titleAndLien"].get("eltLienholderCode"),
    })

    # applications
    funded = next((e["timestamp"] for e in a["activityLog"] if e["eventType"] == "ACH_DISBURSED"), None)
    applications.append([
        q(app_id), q(a["dealNumber"]), q(dl["dealerId"]), q(dl.get("dbaName") or dl["legalName"]),
        q(a["stateCode"]), q(a["submittedAt"]), q(display(a["submittedAt"])),
        q(a["sla"]["minutesRemaining"]), q(a["sla"].get("cutoffAt")), q(a.get("expiresAt")),
        qe(APP_STATUS[a["overallFundingStatus"]], "application_funding_status"), q(funded),
    ])

    # applicants
    res, inc = ap["statedResidence"], ap["statedIncome"]
    addr = ", ".join(p for p in (res.get("streetLine1"), res.get("streetLine2")) if p)
    income_req = reqs.get("BORROWER_STIPULATION")
    verified_income = None
    if income_req and income_req["status"] == "VERIFIED":
        for c in income_req["fieldComparisons"]:
            if c["fieldName"] == "statedVsVerifiedMonthlyIncome":
                verified_income = money(c["comparedValue"])
    co = ap.get("coApplicant")
    applicants.append([
        q(app_id), q(ap["fullName"]), q(co.get("fullName") if isinstance(co, dict) else co),
        q(ap["ssnLast4"]), q(ap["dateOfBirth"]), q(ap.get("phone")), q(ap.get("email")),
        q(addr), q(res.get("city")), q(res.get("state")), q(res.get("postalCode")),
        q(ap["creditSummary"].get("ficoAutoScore")), q(inc["monthlyGrossAmount"]), q(verified_income),
    ])

    # vehicles
    vehicles.append([
        q(app_id), q(vh["year"]), q(vh["make"]), q(vh["model"]), q(vh.get("trim")),
        q(vh["vin"]), q(vh.get("mileage") or 0), qe(vh["condition"], "vehicle_condition"),
    ])

    # loan_terms
    ri = a.get("riscItemization") or {}
    gap = [i for i in ri.get("backEndProducts", []) if i["productType"] == "BACK_END_GAP"]
    loan_terms.append([
        q(app_id), q(cs["amountFinanced"]), q(cs["cashPriceOfVehicle"]), q(cs.get("downPaymentCash") or 0),
        q(cs.get("netTradeInAllowance") or 0), q(sum(i["amount"] for i in gap)),
        q(gap[0]["formNumber"] if gap else None), q(lt["approvedAprPercent"]), q(lt["approvedTermMonths"]),
        q(lt["estimatedMonthlyPayment"]), q(lt.get("calculatedLtvPercent")),
        q(ap["creditSummary"].get("dtiRatioPercent")),
    ])

    # funding_tasks (+ a TASK_VERIFIED event for each verified task)
    for r in a["requirements"]:
        ful = r.get("fulfillment") or {}
        stip = r.get("stipulation")
        comps = r.get("fieldComparisons") or []
        sc = {}
        if comps:
            c0 = comps[0]
            sc = {
                "fieldName": c0["fieldName"],
                "labelA": c0["expectedOrBaselineLabel"], "valueA": c0["expectedOrBaselineValue"],
                "labelB": c0["comparedSourceLabel"], "valueB": c0["comparedValue"],
                "isMatch": c0["isMatch"],
            }
            if len(comps) > 1:
                sc["comparisons"] = comps
        sc["sourceRequirementCode"] = r["code"]
        sc["sourceStatus"] = r["status"]
        sc["fulfillment"] = ful
        if r.get("dataCorrected"):
            sc["dataCorrected"] = "status set from misdirected source event"

        verified_by = None
        if r["status"] == "VERIFIED":
            verified_by = actor(ENGINE_BY_CATEGORY[r["category"]], "SYSTEM")
            assert ful.get("automatedEngine") == verified_by and ful.get("resolvedAt"), r["requirementId"]
            events.append([
                q(f"evt_{r['requirementId']}_verified"), q(app_id), q(r["requirementId"]),
                q(ful["resolvedAt"]), q(display(ful["resolvedAt"])), q(verified_by), qe("SYSTEM", "actor_role"),
                q("TASK_VERIFIED"), q(f"{r['title']} verified automatically"), "NULL",
            ])

        upd = ful.get("resolvedAt") or (stip or {}).get("requestedAt")
        tasks.append([
            q(r["requirementId"]), q(app_id), qe(TASK_CATEGORY.get(r["category"], "OTHER"), "funding_task_category"),
            q(r["title"]), q(r["description"]), qe(TASK_STATUS[r["status"]], "funding_task_status"),
            q(verified_by), q(display(upd)), qj(sc), qj(r.get("ocrEvidence") or None), qj(stip),
        ])

    # activity_events: task events use the task category's owning actor
    for e in a["activityLog"]:
        md = dict(e.get("metadata") or {})
        if "dealNumber" in md:
            md["dealNumber"] = a["dealNumber"]  # source is off by one; event must match its application
        rid = e.get("relatedRequirementId")
        role = ACTOR_ROLE[e["actor"]["actorType"]]
        name = e["actor"]["name"]
        if rid:
            cat = req_by_id[rid]["category"]
            if role == "FUNDER":
                name = FUNDER_BY_CATEGORY[cat]
            elif e["eventType"] == "ROUTED_TO_AGENT_OCR_REVIEW":
                name = ENGINE_BY_CATEGORY[cat]
                # summary text names the assignee: keep it in line with the category owner
                e["summary"] = re.sub(r"assigned to .+$", f"assigned to {FUNDER_BY_CATEGORY[cat]}", e["summary"])
        events.append([
            q(e["eventId"]), q(app_id), q(rid), q(e["timestamp"]), q(display(e["timestamp"])),
            q(actor(name, role)), qe(role, "actor_role"),
            q(e["eventType"]), q(e.get("summary")), qj(md or None),
        ])

    # risc_line_items
    tila_ok = (reqs.get("TILA_AND_ITEMIZATION") or {}).get("status") == "VERIFIED"
    gap_ok = (reqs.get("GAP_COMPLIANCE") or {}).get("status") == "VERIFIED"
    for key, bucket in (("frontEndProducts", "FRONT_END"), ("backEndProducts", "BACK_END"),
                        ("amountsPaidToOthers", "PAID_TO_OTHERS")):
        for n, i in enumerate(ri.get(key, []), start=1):
            item_type = i.get("productType") or i.get("category")
            verified = gap_ok and tila_ok if item_type == "BACK_END_GAP" else tila_ok
            risc.append([
                q(i["itemId"]), q(app_id), qe(bucket, "risc_item_bucket"), q(item_type),
                q(i.get("name") or i.get("description")), q(i.get("formNumber")),
                q((i.get("payee") or {}).get("name")), q(i["amount"]), q(n), q(verified),
            ])

dealer_rows = [
    [q(k), q(v["legal_name"]), q(v["dba_name"]), q(v["elt"]), q(dealer_states[k].most_common(1)[0][0])]
    for k, v in dealers.items()
]
actor_rows = [[q(n), qe(r, "actor_role")] for n, r in sorted(actors.items())]
owner_rows = [
    [qe(TASK_CATEGORY[c], "funding_task_category"), q(FUNDER_BY_CATEGORY[c]), q(ENGINE_BY_CATEGORY.get(c))]
    for c in FUNDER_BY_CATEGORY
]

# --- Write -------------------------------------------------------------------
with open(OUT, "w", encoding="utf-8") as f:
    f.write(f"-- Generated by generate_dml.py from {SRC} ({len(apps)} applications), "
            f"dates rebased to {ARGS.as_of} (shift {SHIFT.days:+d} days)\n")
    f.write("BEGIN;\n\n")
    f.write("-- Re-runnable: clear existing seed data first (whole load is one transaction).\n")
    f.write("TRUNCATE risc_line_items, activity_events, funding_tasks, loan_terms, vehicles, applicants,\n"
            "         applications, dealers, task_category_owners, actors;\n\n")
    f.write(insert("actors", ["actor_name", "role"], actor_rows))
    f.write(insert("task_category_owners", ["category", "funder_name", "engine_name"], owner_rows))
    f.write(insert("dealers", ["dealer_id", "legal_name", "dba_name", "elt_lienholder_code", "state_code"], dealer_rows))
    f.write(insert("applications", ["application_id", "deal_number", "dealer_id", "dealer_name_snapshot",
                                    "state_code", "submitted_at", "submitted_display", "sla_minutes_remaining",
                                    "sla_cutoff_at", "expires_at", "status", "funded_at"], applications))
    f.write(insert("applicants", ["application_id", "full_name", "co_applicant_name", "ssn_last4", "date_of_birth",
                                  "phone", "email", "address_line1", "city", "state_code", "postal_code",
                                  "fico_score", "stated_monthly_income", "verified_monthly_income"], applicants))
    f.write(insert("vehicles", ["application_id", "model_year", "make", "model", "trim", "vin", "mileage",
                                "condition"], vehicles))
    f.write(insert("loan_terms", ["application_id", "amount_financed", "cash_price", "down_payment",
                                  "trade_allowance", "gap_product_price", "gap_form_number", "apr", "term_months",
                                  "monthly_payment", "ltv_percent", "dti_percent"], loan_terms))
    f.write(insert("funding_tasks", ["task_id", "application_id", "category", "title", "description", "status",
                                     "verified_by", "updated_display", "source_comparison", "ocr_evidence",
                                     "stipulation"], tasks))
    f.write(insert("activity_events", ["event_id", "application_id", "task_id", "occurred_at", "timestamp_display",
                                       "actor", "role", "action", "details", "metadata"], events))
    f.write(insert("risc_line_items", ["line_item_id", "application_id", "bucket", "item_type", "description",
                                       "form_number", "payee_name", "amount", "line_order", "is_verified"], risc))
    f.write("COMMIT;\n")

print(f"As of {ARGS.as_of} (dates shifted {SHIFT.days:+d} days)")
print(f"Wrote {OUT}: actors={len(actor_rows)} owners={len(owner_rows)} dealers={len(dealer_rows)} "
      f"applications={len(applications)} funding_tasks={len(tasks)} activity_events={len(events)} "
      f"risc_line_items={len(risc)} misdirected_event_fixes={total_fixes}")
