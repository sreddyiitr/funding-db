# Auto Funding Test Data PRD

Nov 24, 2026 · @Reddy

## Purpose and scope

This PRD defines how to generate synthetic auto-loan funding applications for the Funder Dashboard test database, so any new batch loads cleanly and stays internally consistent. The current baseline is 110 scenarios in `scenarios.txt`, loaded into 10 Postgres tables by `generate_dml.py`.

**Users:** developers and QA who need more deals for the funder queue, stipulation workflows, OCR review and SLA tests.

**In scope**

- The JSON shape of one application record and every field rule.
- Scenario families, their target statuses and the tasks and events each must produce.
- Business rules that tie fields together: contract math, ownership, statuses, dates.
- How JSON maps to the database, and the checks a batch must pass before load.

**Out of scope**

- Real customer data. Every name, SSN, VIN, phone and email is fictitious; emails use `example.com`.
- Credit decisioning logic and underwriting rules beyond what the scenarios state.
- UI behavior of the dashboard.

**Rule language:** MUST = the loader or acceptance checks reject the batch if broken. SHOULD = keep it unless the scenario says otherwise.

## Generation approach

New data is always produced in six steps: plan the scenario mix, assign IDs, build each record from its scenario, derive the tasks and events, validate, then load. Never write SQL by hand; JSON is the source of truth and `generate_dml.py` produces the SQL.

1. **Plan the batch.** Choose how many records per scenario code from the catalog below, keeping the status mix close to the baseline unless the test needs otherwise. Record the plan in `datasetDescription`, `totalScenarios` and `statusBreakdown`.
2. **Reserve IDs.** Continue every sequence from the highest existing value (see Record structure). IDs MUST NOT collide with existing rows.
3. **Build the clean record first.** Generate applicant, vehicle, dealer, loan terms and contract itemization as a fully passing deal, with all five tasks VERIFIED and all math reconciled.
4. **Inject the scenario defect.** Apply only the change the scenario code describes, to the one task it targets: flip that task's status, add the stipulation or low OCR confidence, and break only the fields that the defect touches.
5. **Derive the activity log.** Emit the events the scenario family requires, with the owning actors and timestamps from the rules below.
6. **Validate and load.** Save as `scenarios.txt` (or a new file), run `python3 validate_scenarios.py scenarios.txt`, then load with `./daily_load.sh`. Under the hood it runs:

```bash
python3 generate_dml.py scenarios.txt init/02-data.sql
docker exec -i funder-postgres psql -U funder_admin -d auto_funding_db -v ON_ERROR_STOP=1 < init/02-data.sql
```

The load runs in one transaction and starts with a TRUNCATE of all seed tables, so it replaces the whole dataset. To add to existing data instead, generate a combined file that includes the old records.

## Scenario catalog

Every record carries one `scenarioCode` from 59 codes in 8 families; the code's prefix fixes the target status and which task is open. The baseline has 2 records per code (1 for the rare families), 110 in total.

| Family prefix | `overallFundingStatus` | Codes | Baseline records | Open tasks |
| --- | --- | --- | --- | --- |
| `AUTO_APPROVED_` | READY\_TO\_FUND | 10 | 20 | none, all 5 VERIFIED |
| `FUNDED_` | FUNDED | 4 | 8 | none, all 5 VERIFIED |
| `STIP_DEALER_` | STIPULATION\_ACTION\_REQUIRED | 15 | 30 | exactly 1, STIPULATED, target DEALER |
| `STIP_CUSTOMER_` | STIPULATION\_ACTION\_REQUIRED | 10 | 20 | exactly 1 Income task, STIPULATED, target CUSTOMER |
| `AGENT_VERIFY_` | PENDING\_AGENT\_VERIFICATION | 10 | 20 | exactly 1, PENDING\_AGENT\_VERIFICATION |
| `EXPIRED_` | EXPIRED | 4 | 6 | 0 or 1, EXPIRED |
| `EXCEPTION_HOLD_` | EXCEPTION\_HOLD | 4 | 4 | none (the hold is an underwriting decision) |
| `WITHDRAWN_` / `DECLINED_` | WITHDRAWN / DECLINED | 1 each | 1 each | none |

**Catalog rules**

- A new code MUST start with one of the 8 prefixes above and inherit that family's rules.
- A new code MUST name its target task category in this table before it is used.
- `scenarioDescription` MUST follow `[Scenario #NNN | CODE | Variant N] <Lead>: <defect>. (State: XX, Channel: X, Amount Financed: $N, Status: X)`. Lead is `Stipped to Dealer`, `Stipped to Customer`, `Agent Review Needed`, `Application Expired`, `Exception Hold`, `Application Withdrawn` or `Funding Declined`; clean families describe the deal.
- Variants of the same code MUST differ in applicant, vehicle, dealer and amounts, and keep the same defect.

**All codes and the task each one opens**

| Code | Status | Baseline | Open task | Defect |
| --- | --- | --- | --- | --- |
| `AUTO_APPROVED_READY_TO_FUND_PRIME` | READY\_TO\_FUND | 2 | none | All five checks passed by automation at OCR confidence 0.97 or higher |
| `AUTO_APPROVED_NO_ANCILLARY_PRODUCTS` | READY\_TO\_FUND | 2 | none | No front-end or back-end products, so no GAP task |
| `AUTO_APPROVED_WITH_COAPPLICANT_JOINT_INCOME` | READY\_TO\_FUND | 2 | none | Joint W-2 income clears DTI |
| `AUTO_APPROVED_CPO_VEHICLE_WITH_VSC_AND_GAP` | READY\_TO\_FUND | 2 | none | CPO vehicle with paint protection, GAP and VSC all reconciled |
| `AUTO_APPROVED_HIGH_DOWN_PAYMENT_LOW_LTV` | READY\_TO\_FUND | 2 | none | 35% down, 65% LTV, GAP waived so no GAP task |
| `AUTO_APPROVED_MILITARY_MLA_COMPLIANT` | READY\_TO\_FUND | 2 | none | MAPR under the 36% MLA cap |
| `AUTO_APPROVED_PRIOR_LIEN_PAYOFF_VERIFIED` | READY\_TO\_FUND | 2 | none | Negative-equity trade with verified payoff |
| `AUTO_APPROVED_SELF_EMPLOYED_BANK_STATEMENT_OCR` | READY\_TO\_FUND | 2 | none | Bank deposits read at 97% OCR |
| `AUTO_APPROVED_EV_FEDERAL_POS_REBATE` | READY\_TO\_FUND | 2 | none | EV tax credit applied as down payment |
| `AUTO_APPROVED_AFTER_DEALER_RESUBMISSION` | READY\_TO\_FUND | 2 | none | Earlier license stip cleared by a new scan |
| `FUNDED_ACH_DISBURSED_SAME_DAY` | FUNDED | 2 | none | ACH released to dealer and providers |
| `FUNDED_WITH_AGENT_OVERRIDE_APPROVED` | FUNDED | 2 | none | Funder verified a 78% OCR utility bill |
| `FUNDED_SPLIT_PAYEE_DISBURSEMENT` | FUNDED | 2 | none | Separate payouts to dealer, GAP and VSC providers |
| `FUNDED_SENIOR_FUNDER_EXCEPTION_SIGNED_OFF` | FUNDED | 2 | none | $12 title fee variance waived under the $25 tolerance |
| `STIP_DEALER_GAP_OUTDATED_FORM_NUMBER` | STIPULATION\_ACTION\_REQUIRED | 2 | GAP | Superseded GAP form number |
| `STIP_DEALER_GAP_FEE_EXCEEDS_STATE_CAP` | STIPULATION\_ACTION\_REQUIRED | 2 | GAP | GAP fee $1,150 over the $900 state cap |
| `STIP_DEALER_WRONG_LENDER_ASSIGNEE_NAME` | STIPULATION\_ACTION\_REQUIRED | 2 | Title & lien | Assignee 'Apex Bank' instead of 'Apex Auto Finance NA' |
| `STIP_DEALER_VIN_DIGIT_MISMATCH_TITLE_VS_RIC` | STIPULATION\_ACTION\_REQUIRED | 2 | VIN | 11th VIN character differs between title form and contract |
| `STIP_DEALER_TILA_AMOUNT_FINANCED_MISMATCH` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Items do not sum to Amount Financed ($450 variance) |
| `STIP_DEALER_TILA_APR_FINANCE_CHARGE_OUT_OF_TOLERANCE` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Finance charge outside the Reg Z 1/8% APR tolerance |
| `STIP_DEALER_MISSING_COAPPLICANT_SIGNATURE_RIC` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Co-applicant signature missing on the contract |
| `STIP_DEALER_ODOMETER_DISCLOSURE_MISSING` | STIPULATION\_ACTION\_REQUIRED | 2 | VIN | Odometer disclosure unsigned |
| `STIP_DEALER_ELT_LIENHOLDER_CODE_INCORRECT` | STIPULATION\_ACTION\_REQUIRED | 2 | Title & lien | Paper title instead of the ELT code |
| `STIP_DEALER_BACKEND_PRODUCT_EXCEEDS_APPROVAL_CAP` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Back-end products $3,400 over the $2,500 tier cap |
| `STIP_DEALER_MISSING_BUYERS_ORDER_BREAKDOWN` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | $1,495 accessories not itemized |
| `STIP_DEALER_STALE_CONTRACT_DATE_OVER_15_DAYS` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Contract date 18 days old |
| `STIP_DEALER_TRADE_IN_PAYOFF_LETTER_EXPIRED` | STIPULATION\_ACTION\_REQUIRED | 2 | TILA | Payoff quote expired 4 days ago |
| `STIP_DEALER_MISSING_DEALER_ASSIGNMENT_ENDORSEMENT` | STIPULATION\_ACTION\_REQUIRED | 2 | Title & lien | Dealer assignment block blank |
| `STIP_DEALER_VSC_FORM_NOT_APPROVED_IN_STATE` | STIPULATION\_ACTION\_REQUIRED | 2 | GAP (TILA if no GAP task) | VSC form registered in another state |
| `STIP_CUSTOMER_MISSING_YTD_PAYSTUB` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Paystub without YTD earnings |
| `STIP_CUSTOMER_INCOME_VARIANCE_BELOW_STATED` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Verified income 18% below stated |
| `STIP_CUSTOMER_EXPIRED_DRIVERS_LICENSE` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Driver's license expired |
| `STIP_CUSTOMER_INSURANCE_BINDER_MISSING_LIENHOLDER` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Lender not loss payee on binder |
| `STIP_CUSTOMER_INSURANCE_DEDUCTIBLE_TOO_HIGH` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | $2,500 deductible over the $1,000 max |
| `STIP_CUSTOMER_RESIDENCE_PROOF_PO_BOX_ONLY` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | PO Box only |
| `STIP_CUSTOMER_BANK_STATEMENT_PAGE_MISSING` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | 2 of 4 statement pages uploaded |
| `STIP_CUSTOMER_COAPPLICANT_PROOF_OF_RESIDENCE` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Co-applicant address unproven |
| `STIP_CUSTOMER_SSN_MISMATCH_CREDIT_BUREAU` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | SSN digit transposition |
| `STIP_CUSTOMER_EMPLOYMENT_GAP_EXPLANATION` | STIPULATION\_ACTION\_REQUIRED | 2 | Income | Job change within 30 days |
| `AGENT_VERIFY_OCR_LOW_CONFIDENCE_UTILITY_BILL` | PENDING\_AGENT\_VERIFICATION | 2 | Income | Address read at 64% OCR |
| `AGENT_VERIFY_OCR_FAILED_HANDWRITTEN_VIN_130U` | PENDING\_AGENT\_VERIFICATION | 2 | VIN | Handwritten VIN at 0% OCR |
| `AGENT_VERIFY_OCR_BLURRY_GAP_FORM_FOOTER` | PENDING\_AGENT\_VERIFICATION | 2 | GAP | GAP footer at 68% OCR |
| `AGENT_VERIFY_OCR_PARTIAL_PAYSTUB_GLARE` | PENDING\_AGENT\_VERIFICATION | 2 | Income | YTD pay at 59% OCR |
| `AGENT_VERIFY_NAME_SUFFIX_MISMATCH_JR_SR` | PENDING\_AGENT\_VERIFICATION | 2 | Income | 'Jr.' on credit app, missing on contract |
| `AGENT_VERIFY_ADDRESS_ABBREVIATION_DIFF` | PENDING\_AGENT\_VERIFICATION | 2 | Income | Address abbreviated differently on utility bill |
| `AGENT_VERIFY_EMPLOYER_DBA_VS_PAYROLL_PARENT` | PENDING\_AGENT\_VERIFICATION | 2 | Income | Employer DBA vs payroll parent name |
| `AGENT_VERIFY_OVERTIME_BONUS_INCOME_CONSISTENCY` | PENDING\_AGENT\_VERIFICATION | 2 | Income | Base pay below stated, bonus makes it up |
| `AGENT_VERIFY_INSURANCE_VIN_ONE_CHAR_OCR_AMBIGUITY` | PENDING\_AGENT\_VERIFICATION | 2 | VIN | '8' vs 'B' at 71% OCR |
| `AGENT_VERIFY_BACKEND_PRODUCT_BUNDLE_PRICING` | PENDING\_AGENT\_VERIFICATION | 2 | TILA | Two products bundled in one line |
| `EXPIRED_DEALER_NO_DOCS_7_DAYS` | EXPIRED | 2 | GAP (EXPIRED) | Dealer sent no docs in 7 days |
| `EXPIRED_CUSTOMER_NO_STIP_RESPONSE_10_DAYS` | EXPIRED | 2 | Income (EXPIRED) | Borrower sent no docs |
| `EXPIRED_APPROVAL_LOCK_WINDOW_LAPSED` | EXPIRED | 1 | none | 30-day rate lock lapsed |
| `EXPIRED_BOTH_DEALER_AND_CUSTOMER_INCOMPLETE` | EXPIRED | 1 | Income (EXPIRED) | Dealer and customer stips both open past SLA |
| `EXCEPTION_HOLD_LTV_EXCEEDS_MAX_AFTER_FEE_AUDIT` | EXCEPTION\_HOLD | 1 | none | LTV 121.4% over the 115% max |
| `EXCEPTION_HOLD_FRAUD_ALERT_SYNTHETIC_ID_FLAG` | EXCEPTION\_HOLD | 1 | none | Bureau fraud alert and VOIP phone |
| `EXCEPTION_HOLD_STRAW_PURCHASE_INDICATOR` | EXCEPTION\_HOLD | 1 | none | Insured driver not on the loan |
| `EXCEPTION_HOLD_VEHICLE_BRANDED_SALVAGE_TITLE` | EXCEPTION\_HOLD | 1 | none | Salvage brand on a vehicle sold as clean CPO |
| `WITHDRAWN_DEALER_UNWOUND_DEAL` | WITHDRAWN | 1 | none | Customer returned the vehicle |
| `DECLINED_UNVERIFIABLE_INCOME_POST_AUDIT` | DECLINED | 1 | none | Paystubs failed payroll verification |

## Record structure

A batch is one JSON file with a header and an `applications` array; every application has the same 16 top-level keys, all required. Every ID derives from the scenario number `N` (1-based, `NNN` = zero-padded to 3 digits), so one counter drives the whole record.

**File header:** `datasetDescription`, `generatedAt` (ISO 8601 with offset), `totalScenarios` (MUST equal the array length), `statusBreakdown` (MUST equal the count per `overallFundingStatus`), `applications`.

**Application keys, in order**

```text
scenarioDescription, scenarioCode, applicationId, dealNumber, stateCode,
submittedAt, expiresAt, overallFundingStatus,
sla              { cutoffAt, minutesRemaining, isAtRisk }
applicant        { applicantId, role, fullName, ssnLast4, dateOfBirth, email, phone,
                   creditSummary { ficoAutoScore, bureauSource, dtiRatioPercent },
                   statedIncome { monthlyGrossAmount, annualGrossAmount, employmentStatus,
                                  employerName, monthsWithEmployer, incomeSourceType },
                   statedResidence { streetLine1, streetLine2, city, state, postalCode,
                                     housingStatus, monthlyHousingPayment, monthsAtAddress } }
vehicle          { vehicleId, condition, year, make, model, trim, vin, mileage,
                   titleAndLien { titleState, eltLienholderCode, expectedLenderName,
                                  lienPosition, titleBrand } }
dealer           { dealerId, dealerCode, legalName, dbaName, channel, achAccountMasked }
loanTermsApproved { approvalId, lenderName, programTier, approvedAprPercent,
                    approvedTermMonths, maxAmountFinanced, maxLtvPercent,
                    maxBackEndProductCap, calculatedLtvPercent, estimatedMonthlyPayment,
                    contractSummary {...}, amountFinancedReconciliation {...},
                    tilaMathCheck {...} }
riscItemization  { contractDocumentId, contractFormNumber,
                   frontEndProducts[], backEndProducts[], amountsPaidToOthers[] }
requirements[]   { requirementId, code, category, title, description, status,
                   fulfillment { mode, automatedEngine, resolvedAt },
                   stipulation | null, ocrEvidence[], fieldComparisons[] }
activityLog[]    { eventId, timestamp, actor { name, actorType }, eventType,
                   summary, relatedRequirementId | null, metadata }
```

**ID formats** (the next batch continues at N = 111)

| Field | Format | Example for N = 1 |
| --- | --- | --- |
| `applicationId` | `app_` + (9084700 + N) | `app_9084701` |
| `dealNumber` | `AL-2026-` + (88400 + N) | `AL-2026-88401` |
| `applicant.applicantId` | `apl_` + (4400 + N) | `apl_4401` |
| `vehicle.vehicleId` | `veh_` + (7700 + N) | `veh_7701` |
| `loanTermsApproved.approvalId` | `apr_` + (55900 + N) | `apr_55901` |
| `requirementId` | `req_NNN_` + slot: 01 VIN, 02 lender, 03 TILA, 04 GAP, 05 income | `req_001_04` |
| `eventId` | `evt_NNN_01` for submission, `_02` onward in time order | `evt_001_02` |
| `stipulationId` | `stip_NNN_` + suffix: `cust`, `gap`, `tila`, `lender`, `vin`, `vin_ocr`, `gap_ocr`, `agent_borr` | `stip_032_cust` |
| Contract line items | `fe_NNN_1`, `be_NNN_gap`, `be_NNN_vsc`, `oth_NNN_1`, `oth_NNN_2` | `be_001_gap` |
| Documents | `doc_ric_NNN`, `doc_title_NNN`, `doc_gap_NNN`, `doc_borr_NNN` | `doc_ric_001` |
| ACH trace | `ACH-99` + 4 digits, unique | `ACH-990011` |

**Rules**

- Every ID MUST be unique across the whole dataset, old and new records together.
- A requirement slot keeps its number even when absent: a deal with no GAP task has 01, 02, 03 and 05.
- `scenarioDescription` MUST start with `[Scenario #NNN` using the same N as the IDs.
- Any `dealNumber` inside event metadata MUST equal the application's `dealNumber`. The `2026` in `dealNumber` is a fixed prefix and does not change on daily refresh.

## Entity rules

A clean record MUST reconcile exactly: the contract items sum to the totals, the totals produce Amount Financed, and LTV, DTI and payment are computed from them, never typed. Only a scenario's defect may break one of these, and only the one it names.

### Rotation

State and dealer rotate with N so every batch spreads evenly.

- `stateCode` = position (N − 1) mod 10 in `TX, CA, FL, GA, NC, OH, IL, AZ, WA, CO`.
- Dealer = position (N − 1) mod 8 in the dealer table; `vehicle.make` MUST be that dealer's make.
- `dealer.dealerCode` = `<stateCode>-DLR-` + (99 + N); `achAccountMasked` = `••••` + (6099 + N).
- `dealer.channel` is one of `DEALERTRACK` (50%), `ROUTEONE` (37%), `CUDL` (13%).

| `dealerId` | Legal name | DBA | Make |
| --- | --- | --- | --- |
| `dlr_300` | Apex Metro Honda LLC | Apex Metro Honda | Honda |
| `dlr_301` | Bluebonnet Ford & Lincoln | Bluebonnet Ford | Ford |
| `dlr_302` | Hill Country Hyundai | Hill Country Hyundai | Hyundai |
| `dlr_303` | Sunbelt Toyota Center | Sunbelt Toyota | Toyota |
| `dlr_304` | Pacific Coast Subaru | Pacific Coast Subaru | Subaru |
| `dlr_305` | Peachtree Chevrolet | Peachtree Chevy | Chevrolet |
| `dlr_306` | Buckeye Kia Motors | Buckeye Kia | Kia |
| `dlr_307` | Desert Ridge Nissan | Desert Ridge Nissan | Nissan |

A new dealer MUST get the next ID (`dlr_308`), a unique make and an entry in this table.

### Applicant

- `role` = `PRIMARY`. `ssnLast4` is exactly 4 digits. `dateOfBirth` gives an age of 21 to 75 at submission.
- `email` = `first.last<N>@example.com`; `phone` = `(512) 555-` + (999 + N). Names are fictitious and diverse.
- `ficoAutoScore` 640 to 812, `bureauSource` = `Experian`.
- `annualGrossAmount` MUST equal 12 × `monthlyGrossAmount`.
- `incomeSourceType` = `W2_SALARY`, or `1099_BANK_STATEMENTS` when `employmentStatus` = `SELF_EMPLOYED`.
- `housingStatus` is `OWN` or `RENT`; `postalCode` is 5 digits.

### Vehicle

| `condition` | `year` | `mileage` |
| --- | --- | --- |
| NEW | submission year (2026) | 8 to 19 |
| CPO | 1 to 2 years old | 12,800 to 21,450 |
| USED | 3 to 4 years old | 34,120 to 41,900 |

- `vin` MUST be 17 characters, uppercase, no I, O or Q, unique across the dataset.
- `titleAndLien`: `titleState` = `stateCode`, `eltLienholderCode` = `ELT-88410`, `expectedLenderName` = `Apex Auto Finance NA`, `lienPosition` = 1, `titleBrand` = `CLEAN` (only the salvage-title exception scenario uses `SALVAGE_REBUILT`).

### Loan terms

- `lenderName` = `Apex Auto Finance NA` on every record.
- `programTier` is `TIER_A_PRIME` or `TIER_B_NEAR_PRIME`, split 50/50; `maxLtvPercent` = 115, `maxBackEndProductCap` = 2,500.
- `approvedAprPercent` comes from the ladder 4.49 to 8.09 in steps of 0.45. `approvedTermMonths` is 60 or 72.
- `cashPriceOfVehicle` ranges from 31,800 to 48,500. `maxAmountFinanced` = cash price × 1.15.

Amount Financed is built from the contract, and the contract totals MUST equal the sum of their line items:

```latex
\text{AmountFinanced} = \text{CashPrice} - \text{Down} - \text{NetTrade} + \text{FrontEnd} + \text{BackEnd} + \text{PaidToOthers}
```

```latex
\text{TotalOfPayments} = \text{AmountFinanced} + \text{FinanceCharge} = \text{MonthlyPayment} \times \text{TermMonths}
```

```latex
\text{TotalSalePrice} = \text{TotalOfPayments} + \text{Down} + \text{NetTrade}
```

- `calculatedLtvPercent` = AmountFinanced ÷ CashPrice × 100, rounded to 1 decimal.
- `dtiRatioPercent` = (MonthlyPayment + `monthlyHousingPayment`) ÷ `monthlyGrossAmount` × 100, rounded to 1 decimal.
- AmountFinanced MUST NOT exceed `maxAmountFinanced`; BackEnd total MUST NOT exceed 2,500 unless the scenario is the back-end cap stip.
- `amountFinancedReconciliation`: `expectedAmountFinanced` = the formula, `contractAmountFinanced` = the contract value, `varianceAmount` = their difference, `isReconciled` = variance is 0.
- `tilaMathCheck.status` = `PASSED` unless the scenario is a TILA stip (`FAILED`); `aprToleranceBps` = 12.5.

### Contract itemization

| Bucket | Item | Default amount | Form number | Payee |
| --- | --- | --- | --- | --- |
| Front end | Ceramic and interior protection | 695 | `FE-<ST>-104` | the dealer, `ACH_FUNDING_BUNDLE` |
| Back end | GAP waiver | 750 (state cap 900) | the state's active GAP form | SafeGuard GAP Administration Inc., `ACH_SEPARATE` |
| Back end | Vehicle service contract | 705 | `VSC-<ST>-4410-B` | Summit Auto Warranties LLC, `ACH_SEPARATE` |
| Paid to others | Title, registration and plates | 260 | none | `<ST>` Department of Motor Vehicles, `DEALER_REMIT_VERIFIED` |
| Paid to others | Documentary fee | 125 | none | the dealer, `ACH_FUNDING_BUNDLE` |

- Every record has both paid-to-others items. Products are omitted only by the no-ancillary scenario (no front end, no back end) and the low-LTV scenario (no GAP).
- `contractFormNumber` = `LAW-553-<ST>-0724`.
- Active GAP forms: TX `GAP-TX-9940-REV25`, CA `GAP-CA-4410-2026`, FL `GAP-FL-7721-REV24`, GA `GAP-GA-3019-2025`, NC `GAP-NC-5512-REV25`, OH `GAP-OH-8801-2026`, IL `GAP-IL-6190-REV25`, AZ `GAP-AZ-2294-2026`, WA `GAP-WA-9104-REV25`, CO `GAP-CO-1188-2026`. The outdated-form stip uses `GAP-<ST>-1001-REV19`.

### SLA and dates

- `submittedAt` falls within the 14 days before `generatedAt`, in US Central time (`-06:00`).
- `expiresAt` = `submittedAt` + 7 days.
  - Open records (READY\_TO\_FUND, STIPULATION\_ACTION\_REQUIRED, PENDING\_AGENT\_VERIFICATION) MUST have `expiresAt` after `generatedAt`, i.e. be submitted within the last 7 days. Terminal records may be older.
- `sla.cutoffAt` = 17:00 local on the `generatedAt` date (the dashboard's "today"), for every record.
- `minutesRemaining` = 0 for FUNDED, EXPIRED, WITHDRAWN and DECLINED; 15 to 174 otherwise.
- `isAtRisk` SHOULD be true only for STIPULATION\_ACTION\_REQUIRED or PENDING\_AGENT\_VERIFICATION records with fewer than 40 minutes remaining.

## Task rules

Every application has the same five requirements (four when the deal has no GAP product), and at most one of them is open. The scenario decides which one opens and how. The rest MUST be VERIFIED by their category's engine.

| Slot | `code` | `category` | `title` | DB category |
| --- | --- | --- | --- | --- |
| 01 | `VIN_MULTI_DOC_CONSISTENCY` | `VEHICLE_CROSS_DOC` | Cross-Document Vehicle & VIN Verification | VIN\_VERIFICATION |
| 02 | `LENDER_NAME_ACCURACY` | `LENDER_IDENTITY` | Approved Lender Name Verification | TITLE\_AND\_LIEN |
| 03 | `RISC_TILA_AND_FINANCED_MATH` | `TILA_AND_ITEMIZATION` | RISC TILA Math & Product Fee Reconciliation | TILA\_RECONCILIATION |
| 04 | `GAP_STATE_FORM_NUMBER` | `GAP_COMPLIANCE` | `<ST>` State-Specific GAP Form Number & Fee Cap Check | GAP\_FORM\_VERIFICATION |
| 05 | `INCOME_AND_RESIDENCE_VERIFICATION` | `BORROWER_STIPULATION` | Stated Income & Residence Proof Verification | INCOME\_VERIFICATION |

### What each status requires

| Source `status` | `fulfillment.mode` | `automatedEngine` / `resolvedAt` | `stipulation` | OCR evidence | `fieldComparisons[].isMatch` | DB status |
| --- | --- | --- | --- | --- | --- | --- |
| VERIFIED | AUTOMATION | the category's engine / `submittedAt` | null | every item 0.97 to 0.99, no agent confirmation | true | VERIFIED |
| STIPULATED | STIPULATION | null / null | required, target DEALER or CUSTOMER | 0.97 to 0.99 | false | DISCREPANCY\_FLAGGED |
| PENDING\_AGENT\_VERIFICATION | AGENT\_REVIEW | null / null | required, target INTERNAL\_AGENT | at least one item with `requiresAgentOcrConfirmation` = true | false (true allowed when only OCR is in doubt) | PENDING\_REVIEW |
| EXPIRED | STIPULATION | null / null | required, `dueAt` already past | 0.97 to 0.99 | false | EXPIRED |

### Stipulation object

| Field | Rule |
| --- | --- |
| `stipulationId` | `stip_NNN_<suffix>` (see Record structure) |
| `reasonCode` | `STIP_<TARGET>_<DEFECT>`, matching the scenario |
| `reasonSummary` | The scenario's lead and defect, e.g. `Stipped to Dealer: ...` |
| `actionTarget` | `DEALER`, `CUSTOMER` or `INTERNAL_AGENT` |
| `assignedQueue` | DEALER → `DEALER_PORTAL_RECONTRACT`; CUSTOMER → `BORROWER_UPLOAD_PORTAL`; INTERNAL\_AGENT → `FUNDER_MANUAL_OCR_REVIEW` |
| `requiredDocumentType` | The document that clears it, e.g. `RECENT_30_DAY_PAYSTUBS`, `SIGNED_GAP_ADDENDUM`, `CORRECTED_RISC_ITEMIZATION` |
| `requestedAt` | `submittedAt` |
| `dueAt` | `requestedAt` + 7 days |
| `customerOrDealerInstructions` | One sentence telling the target what to upload and where |

### Rules

- An open task MUST be the one the scenario is about (Scenario catalog, Open task column). A signature, odometer or payoff defect never opens the income task.
- STIP\_DEALER scenarios MUST target DEALER and STIP\_CUSTOMER scenarios CUSTOMER. AGENT\_VERIFY scenarios MUST target INTERNAL\_AGENT.
- An OCR scenario's low-confidence item MUST carry the confidence its description states, e.g. 0.64 for the 64% utility bill; a failed read is 0.0.
- `ocrEvidence` lists only documents the task reads. TILA has none unless it is under agent review; VIN reads the contract and the `<ST>_Title_Application.pdf`.
- `fieldComparisons` holds exactly one comparison per task: baseline label and value, compared source label and value, `isMatch`.
- READY\_TO\_FUND, FUNDED, EXCEPTION\_HOLD, WITHDRAWN and DECLINED records MUST have all tasks VERIFIED.
- A defect changes only the fields it touches. A GAP fee over the cap changes the GAP amount, the back-end total and Amount Financed together; an Amount Financed mismatch leaves a variance of exactly the stated amount.

## Actor and ownership rules

Each task category has exactly one owning funder and one engine, and every action on a task uses one of those two names. This is stored in `task_category_owners` and MUST hold for every task and task event.

| Category | Owning funder | Engine | Routing / verify actor |
| --- | --- | --- | --- |
| VIN | S. Chen | DocCrossCheck-OCR-v4 | engine |
| Title & lien | R. Patel | ContractRuleEngine-v2 | engine |
| TILA | J. Morales | TilaMathVerifier-v3 | engine |
| GAP | A. Brooks | ComplianceFormMatrix-v2 | engine |
| Income | M. Vance-Kerr | Equifax-TWN-Payroll-v3 | engine |

**Deal-level actors** (not tied to a task)

| Actor | `actorType` | Emits |
| --- | --- | --- |
| `DEALERTRACK Intake Gateway`, `ROUTEONE Intake Gateway`, `CUDL Intake Gateway` | SYSTEM | APPLICATION\_SUBMITTED, matching `dealer.channel` |
| `Originations Rules Engine` | SYSTEM | AUTO\_APPROVED\_FOR\_FUNDING |
| `SLA Expiration Daemon` | SYSTEM | APPLICATION\_EXPIRED |
| Any of the 5 funders | FUNDER\_AGENT | ACH\_DISBURSED, STATUS\_UPDATED |

**Rules**

- `actorType` is `SYSTEM` or `FUNDER_AGENT` in JSON; the database role is SYSTEM or FUNDER.
- An actor name MUST always carry the same `actorType`. A new actor MUST be added to the tables above first.
- A STIPULATION\_SENT event MUST use the owning funder of the task it points at.
- A ROUTED\_TO\_AGENT\_OCR\_REVIEW event MUST use the task's engine, and its summary MUST name the owning funder: `Automation confidence below threshold; assigned to <funder>`.
- A VERIFIED task's `automatedEngine` MUST be its category's engine, and its `TASK_VERIFIED` event uses the same name.
- Deal-level funder events (ACH\_DISBURSED, STATUS\_UPDATED) SHOULD rotate across the 5 funders.
- To reassign a category, change its owner here and in `FUNDER_BY_CATEGORY` in `generate_dml.py`, then reload. Never hand-edit names in individual records.

## Activity log rules

Every record has exactly two source events: the submission, then one outcome event that matches its family. The loader adds one `TASK_VERIFIED` event per verified task; do not put those in the JSON.

| Family | Outcome event | Offset from `submittedAt` | Actor | `relatedRequirementId` | `metadata` | Summary pattern |
| --- | --- | --- | --- | --- | --- | --- |
| all | APPLICATION\_SUBMITTED (`evt_NNN_01`) | 0 min | channel's intake gateway | null | `{dealNumber}` | `Contract package received from <DBA> (<ST>)` |
| AUTO\_APPROVED | AUTO\_APPROVED\_FOR\_FUNDING | +2 min | Originations Rules Engine | null | `{amountFinanced}` | `All verification requirements passed automatically; queued for ACH release` |
| AGENT\_VERIFY | ROUTED\_TO\_AGENT\_OCR\_REVIEW | +4 min | the task's engine | the open task | `{}` | `Automation confidence below threshold; assigned to <owning funder>` |
| STIP\_DEALER, STIP\_CUSTOMER | STIPULATION\_SENT | +8 min | the task's owning funder | the open task | `{actionTarget}` | `Sent stipulation to <TARGET>: <task title>` |
| EXCEPTION\_HOLD, WITHDRAWN, DECLINED | STATUS\_UPDATED | +12 min | a funder | null | `{status}` | the scenario's lead and defect sentence |
| FUNDED | ACH\_DISBURSED | +120 min | a funder | null | `{achTraceId}` | `Disbursed $<amount financed> via ACH to <dealer legal name>` |
| EXPIRED | APPLICATION\_EXPIRED | +7 days | SLA Expiration Daemon | the expired task, or null if none | `{daysElapsed: 7}` | the scenario's lead and defect sentence |
| (loader) | TASK\_VERIFIED | `resolvedAt` | the task's engine | the verified task | none | `<task title> verified automatically` |

**Rules**

- `activityLog` MUST be ordered newest first in the JSON.
- Every event timestamp MUST fall between `submittedAt` and `generatedAt`, so an EXPIRED record MUST be submitted at least 7 days before `generatedAt`.
- `relatedRequirementId` MUST point at a requirement in the same record. A stip or review event MUST NOT point at a VERIFIED task.
- Amounts in summaries use `$` with thousands separators and 2 decimals, e.g. `$42,235.00`.
- `metadata.dealNumber` MUST equal the record's `dealNumber`; `amountFinanced` MUST equal the contract value.

## Database mapping

`generate_dml.py` maps each JSON record into 8 data tables plus 2 reference tables; the schema is `init/01-schema.sql`. A field not listed here is kept only inside a JSONB column.

| Table | One row per | Key source fields |
| --- | --- | --- |
| `actors` | distinct actor name | every `actor.name`, owning funders, engines |
| `task_category_owners` | task category | the ownership table in this PRD |
| `dealers` | `dealer.dealerId` | `legalName`, `dbaName`, `eltLienholderCode`; `state_code` = the dealer's most common deal state |
| `applications` | record | `applicationId`, `dealNumber`, `submittedAt`, `expiresAt`, `sla.*`, status; `funded_at` = the ACH\_DISBURSED time |
| `applicants` | record | name, SSN last 4, DOB, contact; `address_line1` = street lines 1 and 2 joined; `verified_monthly_income` only when the income task is VERIFIED |
| `vehicles` | record | year, make, model, trim, VIN, mileage, condition |
| `loan_terms` | record | contract amounts, APR, term, payment; `gap_product_price` = sum of GAP items; `ltv_percent` = `calculatedLtvPercent`; `dti_percent` = `dtiRatioPercent` |
| `funding_tasks` | requirement | `task_id` = `requirementId`; `verified_by` = the engine when VERIFIED; `source_comparison`, `ocr_evidence` and `stipulation` as JSONB |
| `activity_events` | event, plus 1 TASK\_VERIFIED per verified task | `task_id` = `relatedRequirementId`; `action` = `eventType`; `details` = `summary` |
| `risc_line_items` | contract line item | bucket from the array; `item_type` = `productType` or `category`; `line_order` restarts at 1 per bucket |

**Enum mappings**

| JSON value | Column | DB value |
| --- | --- | --- |
| STIPULATION\_ACTION\_REQUIRED | `applications.status` | PENDING\_STIPULATIONS |
| PENDING\_AGENT\_VERIFICATION | `applications.status` | PENDING\_AGENT\_VERIFICATION |
| other statuses | `applications.status` | same name |
| STIPULATED | `funding_tasks.status` | DISCREPANCY\_FLAGGED |
| PENDING\_AGENT\_VERIFICATION | `funding_tasks.status` | PENDING\_REVIEW |
| VERIFIED, EXPIRED | `funding_tasks.status` | same name |
| FUNDER\_AGENT | `activity_events.role` | FUNDER |
| frontEndProducts / backEndProducts / amountsPaidToOthers | `risc_line_items.bucket` | FRONT\_END / BACK\_END / PAID\_TO\_OTHERS |

**Rules**

- A new JSON enum value MUST get a mapping here and in `generate_dml.py` before use; the loader fails on unmapped values.
- `risc_line_items.is_verified` = the TILA task is VERIFIED, and for GAP items the GAP task too.
- A load replaces all rows: the generated SQL truncates the 10 tables, then inserts, in one transaction.

## Acceptance checks and daily refresh

A batch is accepted only when `validate_scenarios.py` reports PASSED; the daily load refuses to touch the database otherwise. The baseline `scenarios.txt` passes all checks as of this date.

**Daily refresh.** Dates in the file are a template anchored on `generatedAt`. Each load moves every timestamp forward by the whole days between that date and the load date, so all date rules keep holding and times of day stay put. New and used model years move with the calendar year.

```bash
./daily_load.sh              # wipe and reload, dated today
./daily_load.sh 2026-12-01   # dated a chosen day
```

The script rebases, validates, then truncates and reloads in one transaction. Run it after 08:10 US Central, because the latest baseline event sits at 08:08 on the anchor day. New records keep being written against the file's own `generatedAt`; never edit dates by hand to "refresh" them.

**What the checker enforces** (each is a MUST rule from this PRD)

| Area | Checks |
| --- | --- |
| File header | `totalScenarios` and `statusBreakdown` match the records |
| Uniqueness | application, deal number, VIN, requirement, event and line-item IDs |
| IDs | every ID follows N; requirement slots 01 to 05; description starts `[Scenario #NNN \| CODE \|` |
| Family | status and outcome event match the code prefix; open-task count fits the family |
| Dates | `expiresAt` = submitted + 7 days; open records not yet expired; cutoff 17:00 on the run date; every event between submission and `generatedAt` |
| Contract math | item sums equal totals; Amount Financed formula; reconciliation variance; total of payments, sale price, LTV; caps; TILA status agrees with the math |
| Tasks | fulfillment mode per status; verified tasks use their engine with no stip and no mismatch; open tasks have a stipulation with the right queue and a 7-day due date; agent reviews carry an OCR item needing confirmation |
| Actors and events | newest first; gateway matches channel; task events never point at a VERIFIED task; funder and engine are the category owners; one `actorType` per name |

**Before using a new batch, also confirm by hand:** the defect in each new record matches its scenario description, and new codes, dealers or actors were added to the tables in this PRD first.
