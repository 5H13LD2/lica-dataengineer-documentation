# 2026-07-29 Updates

> **Companion data workbook:** `gulong_july_booking_conversion_audit_2026-07-29.xlsx`
> Every section below carries a **↳ Backed by** line pointing to the sheet(s) that source its numbers.
> A full [Data Lineage — Report ↔ Workbook](#data-lineage--report--workbook) crosswalk is at the end.

---

## Executive Summary

- **Taira sustained a 21.04% Moderate/High intent rate in Jul 22–28:** 235 qualified inquiries from 1,117 total. This was 0.87 pp below Jul 15–21, but 4.04 pp above Jul 1–7.
- **Taira-origin inquiries converted better than the four selected Human CS** in the current inquiry cohort: 12 traceable bookings from 1,117 Taira inquiries (1.07%) versus 14 from 2,141 inquiries owned by Rem Reyes, Aira L. Garcia, Rolyn Ang, and Sarah (0.65%). This is a 1.64× current-week rate advantage, but the Jul 22–28 cohort is still maturing and Jul 28 is still partial.
- **Human CS booking conversion weakened in the latest cohort:** the combined booking rate moved from 1.29% in Jul 8–14 to 1.09% in Jul 15–21 and 0.65% in Jul 22–28. The latest period is less mature and Jul 28 is partial, but the decline is visible across all four agents and requires continued monitoring.
- **Sarah's weekly handoff service was mixed:** one-hour coverage improved from 73.68% to 79.04% and average business response time improved from 58.9 to 36.5 minutes, but the median slowed from 13.0 to 27.5 minutes and the 30-minute share fell from 62.41% to 51.53%. The setup improved parts of the distribution, not every SLA threshold.
- **Concurrent workload remains the strongest response-time constraint:** qualified-handoff median response previously rose from 11 minutes at 0–17 open cases to 134.5 minutes at 39+ open cases; one-hour coverage fell from 86.05% to 22.79%.
- **Guided selections reveal customer readiness:** Moderate/High intent increased from 12.93% with no guided selections to 25.38% with one and 61.54% with two. Contact capture remained near 5–6% at every depth and is the clearest funnel leak.

---

## 1. Chatbot Performance Snapshot

Bookings below are traceable to ManyChat inquiries and are attributed to the **inquiry date**, not the order-creation date. There is no arbitrary conversion window; bookings observed through Jul 28 are included. The latest Jul 28 assignment snapshot was extracted at **22:38 Asia/Manila** and remains partial.

| Inquiry cohort | Inquiries | Moderate/High | Moderate rate | Bookings | Bookings / Moderate | Bookings / Inquiries |
|---|---:|---:|---:|---:|---:|---:|
| Jul 1–7 | 647 | 110 | 17.00% | 9 | 8.18% | 1.39% |
| Jul 8–14 | 934 | 183 | 19.59% | 3 | 1.64% | 0.32% |
| Jul 15–21 | 972 | 213 | 21.91% | 13 | 6.10% | 1.34% |
| Jul 22–28 | 1,117 | 235 | 21.04% | 12 | 5.11% | 1.07% |
| **Jul 1–28** | **3,670** | **741** | **20.19%** | **37** | **4.99%** | **1.01%** |

**Management readout**

- Moderate/High intent quality remained above 20% in the latest two weeks.
- Weekly booking rates fluctuate because bookings often occur several days after the inquiry. Jul 22–28 should be revisited after additional maturation.
- The Jul 15–21 and Jul 22–28 booking cohorts are materially stronger than Jul 8–14, despite similar Moderate/High rates. This indicates that downstream selling activity and customer readiness, not intent classification alone, drive bookings.

> **↳ Backed by:** `Lane_Summary` (Taira lane), `Inquiry_Cohorts` (is_chatbot_jeanel = TRUE), `Bookings_All` (is_taira_origin, is_reportable_booked_order). Moderate flag = `validated_moderate` from `gulong_core.moderate_intent_sessions`.
> **Scope note:** The report is **inquiry-date, weekly-cohort** scoped through Jul 28. The workbook `Lane_Summary` is **booking-date, whole-month** scoped Jul 1–29 (partial) — so its Taira total (32/3,699 = 0.87%) is *not* meant to equal this section's Jul 1–28 chatbot total (37/3,670 = 1.01%). See [reconciliation notes](#reconciliation-notes).

---

## 2. Human CS Inquiry Conversion

Human CS is limited to **Rem Reyes, Aira L. Garcia, Rolyn Ang, and Sarah**. Each cell shows *booking orders / inquiries (booking rate)*. Ownership is based on the **original inquiry owner**; booking creator is not used for conversion attribution. Jul 22–28 inquiry counts use the live original-assignment snapshot extracted Jul 28 at 22:38 Asia/Manila.

| Agent | Jul 1–7 | Jul 8–14 | Jul 15–21 | Jul 22–28 | Jul 1–28 |
|---|---|---|---|---|---|
| Aira L. Garcia | 9/539 (1.67%) | 8/647 (1.24%) | 7/684 (1.02%) | 5/666 (0.75%) | 29/2,536 (1.14%) |
| Rem Reyes | 6/540 (1.11%) | 9/647 (1.39%) | 7/678 (1.03%) | 5/668 (0.75%) | 27/2,533 (1.07%) |
| Rolyn Ang | 3/325 (0.92%) | 2/391 (0.51%) | 7/463 (1.51%) | 3/459 (0.65%) | 15/1,638 (0.92%) |
| Sarah | 5/541 (0.92%) | 11/646 (1.70%) | 3/376 (0.80%) | 1/348 (0.29%) | 20/1,911 (1.05%) |
| **Four-CS team** | **23/1,945 (1.18%)** | **30/2,331 (1.29%)** | **24/2,201 (1.09%)** | **14/2,141 (0.65%)** | **91/8,618 (1.06%)** |

**Management readout**

- Aira led Jul 1–7; Sarah led Jul 8–14; Rolyn led Jul 15–21. No agent exceeded 0.75% in the still-maturing Jul 22–28 cohort.
- The latest cohort should be refreshed in subsequent reports because bookings created after Jul 28 will continue to accrue to these inquiry dates.

> **↳ Backed by:** `Lane_Summary` (Sarah, Aira, Rolyn, Rem lanes), `Inquiry_Cohorts` (reporting_lane, converted_inquiry, qualifying_booking_count), `Bookings_All` (original_owner_lane, in_scope_original_owner). Owner logic uses `original_owner_lane`, **not** `creator_lane` — the 56 creator/original-owner mismatches in `Validation` are expected handoffs.

---

## 3. Sarah / Taira Qualified Handoff Performance

Response time is measured in **business minutes, 09:00–18:00 Asia/Manila**. For handoffs outside business hours, the clock begins at 09:00 the next business day rather than excluding the handoff.

| Inquiry cohort | Qualified handoffs | Sarah responded | Response rate | Within 30 min | Within 1 hour | Median business response | Average business response | Customer replied after Sarah |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Jul 15–21 | 133 | 130 | 97.74% | 62.41% | 73.68% | 13.0 min | 58.9 min | 41.54% |
| Jul 22–28 | 229 | 224 | 97.82% | 51.53% | 79.04% | 27.5 min | 36.5 min | 44.64% |

**Interpretation**

- Response coverage remained essentially flat at about 98%.
- The latest week had fewer very long delays, reducing the average by 22.4 minutes and improving one-hour coverage by 5.36 points.
- The typical handoff was answered later: the median increased by 14.5 minutes and the 30-minute share fell by 10.88 points. The operational target should therefore be **consistent early coverage, not only a lower average**.
- In the clean **Jul 25–26 full-Chatbot subset**, the median improved from 28 to 23 business minutes versus Jul 20–23 and the 30-minute share increased from 50.65% to 57.89%, while one-hour coverage decreased from 80.52% to 78.07%. This supports better early prioritization for some leads, not a blanket SLA improvement.

**Workload and commercial value**

- With **0–17 open** qualified cases, median response was 11 minutes and one-hour coverage was 86.05%.
- At **39+ open** cases, median response increased to 134.5 minutes and one-hour coverage fell to 22.79%.
- Open queue and response delay had a Spearman correlation of **0.596 (p<0.001)**. Queue size is the clearest operating control for response performance.
- In mature historical cohorts, Chatbot Moderate/High handoffs converted at **3.13%** versus **0.84%** for Sarah-direct inquiries. Median time-to-book was **18.0 h** for qualified handoffs versus **20.6 h** for Sarah-direct inquiries. This is evidence of lead-stage quality, not proof that the assignment setup alone caused the difference.

> **↳ Backed by:** `Assignment_History` (assignment/handoff events + timestamps), `Bookings_All` time-to-book fields. Response timing derives from `manychat_data.agent_assignment_events`, `manychat_data.messages`, and `gulong_core.inquiry_assignments`. **Note:** business-minute SLA math and the queue-depth buckets are *not* pre-computed columns in the workbook — they are report-side calculations on top of the assignment/message timestamps.

---

## 4. Guided Surfaces and Inquiry Progression

Cohorts cover **Jul 20–28**. A click identifies self-selected engagement and should **not** be interpreted as a randomized causal lift.

**Behavioral signals**

- **Location is the strongest progression signal:** 60.19% of clickers reached Moderate/High intent versus 11.18% of customers shown the buttons without clicking.
- Location capture was 66.99% among clickers versus 10.56% among shown-no-click customers.
- Price-category clickers reached Moderate/High intent at 39.24%, 17.16 points above shown-no-click customers.
- Choices skewed toward **Budget (54.78%)**, followed by Mid Range (20.87%), Premium (18.26%), and Economy (6.09%).
- Product-choice engagement was low at 8.48%, but customers who clicked were more advanced in the journey.
- Card-position clicks concentrated on the first card (53.85%), then the second (26.92%).
- Promo action events were primarily Check Price (82.35%), then Promo Details (16.91%).
- Promo brand actions were Michelin 42.86%, Apollo 36.61%, and Yokohama 20.54%.

**Surface engagement**

Moderate/High rates use conversations with sufficient analysis coverage; field rates use the inquiry cohort shown.

| Surface | Shown | Clicked | Click rate | M/H: all shown | M/H: clicked | M/H: shown, no click | M/H: not shown |
|---|---:|---:|---:|---:|---:|---:|---:|
| Promo carousel | 103 | 67 | 65.05% | 18.45% | 20.90% | 13.89% | 18.40% |
| Price category | 157 | 80 | 50.96% | 30.77% | 39.24% | 22.08% | 16.04% |
| Location buttons | 269 | 103 | 38.29% | 30.30% | 60.19% | 11.18% | 13.38% |
| Product choices | 224 | 19 | 8.48% | 28.25% | 47.37% | 26.47% | 14.64% |

**Inquiry progression by guided selections**

| Guided selections | Inquiries | Moderate/High | Size captured | Brand captured | Location captured | Contact captured |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 696 | 12.93% | 61.84% | 40.03% | 20.72% | 5.92% |
| 1 | 131 | 25.38% | 92.31% | 71.54% | 33.85% | 5.38% |
| 2 | 52 | 61.54% | 94.23% | 80.77% | 63.46% | 5.77% |
| 3+ | 7 | 57.14% | 100.00% | 85.71% | 71.43% | 0.00% |

**Actions**

1. Make the next guided step explicit after every selection: size → price range, price range → product, product → location or schedule.
2. Preserve previous selections and avoid asking customers to repeat captured information.
3. Move contact capture to a clear value exchange such as reserving stock, confirming branch availability, or sending the final quotation.
4. Keep the strongest default choices visible and instrument each impression, click, downstream field, handoff, and booking consistently.
5. Treat the 3+ selection cohort as directional only because it contains seven inquiries.

> **↳ Backed by:** `Chat_Analysis_Raw` (sales_stages_completed, funnel_path, tire_size/brand/location/contact extraction), `Intent_Evidence`, plus guided-surface event logs. **Note:** guided-surface impression/click tables are report-side aggregations from the ManyChat guided-surface event logs; the workbook retains the per-user analysis rows, not the surface-level pivot.

---

## 5. Conversation and Sales-Journey Insights

Human CS below includes only **Rem Reyes, Aira L. Garcia, Rolyn Ang, and Sarah**. The analysis covers **Jul 22–28** conversations with semantic-analysis coverage.

**Inquiry progression by guided selections** (contact capture at depth)

| Guided selections | Inquiries | Moderate/High | Size captured | Brand captured | Location captured | Contact captured |
|---|---:|---:|---:|---:|---:|---:|
| 0 | 696 | 12.93% | 61.84% | 40.03% | 20.72% | 5.92% |
| 1 | 131 | 25.38% | 92.31% | 71.54% | 33.85% | 5.38% |
| 2 | 52 | 61.54% | 94.23% | 80.77% | 63.46% | 5.77% |
| 3+ | 7 | 57.14% | 100.00% | 85.71% | 71.43% | 0.00% |

**Channel comparison**

| Metric | Selected Human CS | Taira |
|---|---:|---:|
| Inquiries | 2,141 | 1,117 |
| Conversations analyzed | 1,283 (59.93%) | 1,010 (90.42%) |
| Semantic Moderate/High rate | 15.12% | 18.22% |
| Average exchanges | 1.51 | 2.09 |
| Reached pricing/quotation | 25.33% | 38.22% |
| Reached installation-partner stage | 6.47% | 9.21% |
| Reached scheduling stage | 7.40% | 10.20% |
| Captured contact information | 5.53% | 5.94% |
| Traceable inquiry-date booking rate | 0.65% | 1.07% |

**Interpretation**

- Taira conversations had 38% more exchanges and were more likely to reach quotation, installation-partner, and scheduling stages. The current inquiry cohort also had a 1.64× booking rate. These are **associated** stage-depth signals; they do not establish that chatbot origin alone caused conversion.
- Both channels have nearly the same low contact-capture rate. The shared commercial opportunity is to convert completed product/location discovery into a low-friction contact or reservation step.
- Human CS analysis coverage (59.93%) is lower than Taira's (90.42%). Coverage should be improved before using semantic rates as a complete productivity ranking.
- The most actionable near-misses are conversations that capture size, brand, price preference, and location but stop before contact, stock confirmation, quotation, or scheduling.

> **↳ Backed by:** `Chat_Analysis_Raw` (num_exchanges, sales_stages_completed, funnel_path), `Inquiry_Cohorts` (validated_moderate, converted_inquiry), `Bookings_All` (booking rates by lane). The 0.65% vs 1.07% booking rates tie directly to §1 and §2.

---

## 6. GCP Cost Monitoring

Costs use the Cloud Billing export with the GCP UI's **Pacific charge-date basis** (`America/Los_Angeles`) and net cost after credits. Gulong uses project **`gulong-chatbot-459723`** only.

### Gulong

| Service | Jul 1–7 | Jul 8–14 | Jul 15–21 | Jul 22–28 | Jul 1–28 |
|---|---:|---:|---:|---:|---:|
| Gemini API | $91.25 | $73.98 | $74.93 | $84.72 | $324.88 |
| BigQuery | $48.10 | $101.41 | $24.87 | $37.64 | $212.02 |
| Cloud Run | $15.79 | $0.86 | $0.96 | $1.37 | $18.98 |
| Compute Engine | $20.41 | $18.42 | $16.95 | $13.01 | $68.79 |
| Cloud SQL | $3.05 | $3.16 | $3.53 | $3.20 | $12.94 |
| **Total** | **$178.60** | **$197.83** | **$121.24** | **$139.94** | **$637.61** |

Jul 22–28 cost increased **15.4% WoW**, driven mainly by Gemini API and BigQuery, partly offset by lower Compute Engine cost. Straight-line Jul 1–28 projection for these five services is approximately **$706** for July.

### Mechanigo

| Service | Jul 1–7 | Jul 8–14 | Jul 15–21 | Jul 22–28 | Jul 1–28 |
|---|---:|---:|---:|---:|---:|
| Gemini API | $25.35 | $16.47 | $11.22 | $15.33 | $68.37 |
| BigQuery | $5.00 | $5.58 | $5.04 | $5.51 | $21.13 |
| Cloud Run | $1.11 | $0.73 | $0.08 | $0.06 | $1.98 |
| Compute Engine | $3.57 | $3.61 | $4.44 | $3.90 | $15.52 |
| Cloud SQL | $0.00 | $0.09 | $0.06 | $6.32 | $6.47 |
| **Total** | **$35.03** | **$26.48** | **$20.84** | **$31.12** | **$113.47** |

Jul 22–28 cost increased **49.3% WoW**, mainly from Cloud SQL (+$6.26) and Gemini API (+$4.11). Straight-line July projection ≈ **$126**.

### Carmax

| Service | Jul 1–7 | Jul 8–14 | Jul 15–21 | Jul 22–28 | Jul 1–28 |
|---|---:|---:|---:|---:|---:|
| Gemini API | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |
| BigQuery | $1.49 | $1.79 | $1.79 | $1.58 | $6.65 |
| Cloud Run | $1.01 | $0.94 | $1.01 | $0.86 | $3.82 |
| Compute Engine | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |
| Cloud SQL | $0.00 | $0.00 | $0.00 | $0.00 | $0.00 |
| **Total** | **$2.50** | **$2.73** | **$2.80** | **$2.44** | **$10.47** |

Carmax remained stable and decreased **12.9% WoW**. Straight-line July projection ≈ **$12**.

> **↳ Backed by:** Not sourced from this workbook — GCP costs come from the Cloud Billing detailed export (Pacific charge date, net-of-credits). Included in the report for completeness.

---

## 7. Other Updates

### RFID Inventory Warehouse

**Detection hit rate and scanning duration**

| Date | Time | Actual Count | SKU | Scan Count | Scan time (s) | Hit % |
|---|---|---:|---|---:|---:|---:|
| 7/22/2026 | 16:30:00 | 75 | MAX POWER OIL FILTER MC415 | 75 | 5 | 100.00% |
| 7/23/2026 | 16:00:00 | 175 | MAX POWER OIL FILTER MC415 | 175 | 5.5 | 100.00% |
| 7/25/2026 | 8:07 | 169 | MAX POWER OIL FILTER MC415 | 169 | 3.4 | 100.00% |
| 7/27/2026 | 8:10 | 169 | MAX POWER OIL FILTER MC415 | 169 | 7.6 | 100.00% |
| 7/28/2026 | 8:13 | 169 | MAX POWER OIL FILTER MC415 | 169 | 7.6 | 100.00% |

*(Source PDF listed the last row's year as "7/28/22026" — corrected to 7/28/2026 here.)*

**Next steps**

- Retest tagged inventory and document detection tolerance and hit rate.
- Compare internal printing against bulk supplier printing, including maintenance, ink, and printing-error costs.
- Evaluate the Android version for a custom bridge application that sends data to the internal system rather than directly to SIA.
- Pilot a phased rollout using oil filters, with a daily RFID count compared with SIA inventory.
- Consolidate supplier and operating documentation into an operations manual and use AI-assisted review to identify process optimizations.

> **↳ Backed by:** Not in this workbook — RFID pilot data is tracked separately.

---

## Reporting Definitions and Data Sources

- **Weekly periods:** Wednesday–Tuesday; Jul 1–7, Jul 8–14, Jul 15–21, and Jul 22–28.
- **Observation cutoff:** Jul 28, 2026; assignment snapshot extracted at 22:38 Asia/Manila. Jul 28 remains partial and recent inquiry cohorts are not fully mature.
- **Inquiry and Moderate/High metrics:** `gulong_reporting.p_looker_agent_daily_conversion` and `gulong_core.moderate_intent_sessions`.
- **Response timing:** `manychat_data.agent_assignment_events`, `manychat_data.messages`, and `gulong_core.inquiry_assignments`; business hours 09:00–18:00 Asia/Manila.
- **Booking truth:** qualifying orders reconciled to `gulong_core.orders_booked`, with bounded transcript-supported recovery for missing curated links.
- **Booking attribution:** original inquiry owner and inquiry date; no fixed conversion window. Order creator is retained only as a closing-workload view.
- **Guided journey and conversation analysis:** ManyChat messages, guided-surface event logs, inquiry evidence, and semantic conversation analysis tables.
- **Cost source:** Cloud Billing detailed export; Pacific charge date and net cost after credits.

---

## Data Lineage — Report ↔ Workbook

Crosswalk from each report section to the sheet(s) in `gulong_july_booking_conversion_audit_2026-07-29.xlsx` that source or corroborate it.

| Report section | Primary sheet(s) | Key columns / how to reproduce |
|---|---|---|
| §1 Chatbot Performance Snapshot | `Lane_Summary`, `Inquiry_Cohorts`, `Bookings_All` | Filter `Inquiry_Cohorts` where `is_chatbot_jeanel = TRUE`; count rows for inquiries, `validated_moderate = TRUE` for Moderate/High, `qualifying_booking_count > 0` for bookings. Taira roll-up is in `Lane_Summary` row *Taira (Chatbot/JCo)*. |
| §2 Human CS Inquiry Conversion | `Lane_Summary`, `Inquiry_Cohorts`, `Bookings_All` | Group `Inquiry_Cohorts` by `reporting_lane` ∈ {Rem, Aira, Rolyn, Sarah}; conversion = `converted_inquiry` / inquiry rows. Owner = `original_owner_lane` in `Bookings_All`, **not** `creator_lane`. |
| §3 Sarah/Taira Qualified Handoff | `Assignment_History`, `Bookings_All` | Handoff events + timestamps in `Assignment_History` (`assignment_at`, `session_start_at`, `previous_agent_name`). Business-minute SLA and queue-depth buckets are computed report-side. |
| §4 Guided Surfaces & Progression | `Chat_Analysis_Raw`, `Intent_Evidence` | Field capture (`analysis_tire_size`, `analysis_primary_brand`, `analysis_location`, `analysis_contact_number`), `sales_stages_completed`, `funnel_path`. Surface impression/click pivots are report-side from ManyChat event logs. |
| §5 Conversation & Sales-Journey | `Chat_Analysis_Raw`, `Inquiry_Cohorts`, `Bookings_All` | `num_exchanges`, stage flags, `validated_moderate`; booking rates 0.65% / 1.07% tie back to §1–§2. |
| §6 GCP Cost Monitoring | *(external)* | Cloud Billing detailed export — not in workbook. |
| §7 RFID Inventory | *(external)* | RFID pilot log — not in workbook. |
| Governance / audit trail | `README`, `Validation`, `Denominator_Recon`, `Data_Dictionary`, `SQL_Log` | Scope, caveats, PASS/REVIEW checks, denominator choice, column definitions, and the exact BigQuery jobs behind each sheet. |

### Reconciliation notes

The report and the workbook are **deliberately scoped differently**, so several headline numbers relate without being equal. Read these before comparing cells directly:

1. **Date basis differs.** The report attributes on **inquiry date** in weekly cohorts through **Jul 28**. The workbook `Lane_Summary` attributes on **booking date** across the **whole month, Jul 1–29** (partial). This is the main reason per-lane totals don't line up 1:1 (e.g. report Aira Jul 1–28 = 29/2,536 = 1.14%; workbook Aira booking-scoped = 26/2,567 = 1.01%).

2. **Denominator source.** Inquiry counts use `gulong_core.inquiry_assignments` **deduplicated to one original assignment per `silver_session_id`**, *not* the `inquiry_sessions` view — because that view currently has **zero Rolyn-owned sessions** and misses other owners. `Denominator_Recon` quantifies the gap (assignment-minus-view difference of 2,488 rows overall; +1,656 for Rolyn alone). This is flagged **REVIEW / High** in `Validation`.

3. **Booking rule.** Numerator uses `is_reportable_booked_order = TRUE`, **excludes CALL** orders from chat-inquiry conversion, and applies **no 72-hour / 7-day cap**. `Validation` shows 190 inclusive FB/Chatbot orders → 174 reportable booked.

4. **Moderate/High = validated only.** The official Moderate KPI uses `validated_moderate` from `gulong_core.moderate_intent_sessions`. ManyChat tags and `chat_analysis` are retained as **supporting evidence only** (`Intent_Evidence`, `Chat_Analysis_Raw`) and should not be summed into the official rate.

5. **Open review items** (`Validation`): 15 ManyChat-linked rows missing inquiry date, 56 creator/original-owner mismatches (expected handoffs), and **live MCP order verification not completed (HTTP 401)** — current status/payment/value come from the BigQuery backend mirror and should be re-checked against the live backend where material.

---

*Workbook extraction: 2026-07-29 12:07:58 Asia/Manila · Attribution view freshness: 2026-07-29 12:08:14 · Report observation cutoff: 2026-07-28 22:38 Asia/Manila.*
