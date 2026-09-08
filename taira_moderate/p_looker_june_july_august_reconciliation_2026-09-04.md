# Jeanel Co / Taira gold-layer reconciliation — June to August 2026

## Gold-layer slice

- Table: `gulong-chatbot-459723.gulong_reporting.p_looker_agent_daily_conversion`
- Agent: `agent_key = 'chatbot/jco'`
- Agent group/name: `chatbot_jeanel` / `Chatbot/JCo`
- CSV mapping: `total_inquiries` → `inquiries_assigned`; `total_moderate_intents` → `moderate_high`; `total_bookings` → `bookings`
- Latest physical-layer refresh observed: 2026-09-04 16:07:05 (Asia/Manila)

## June gold-layer result

All 30 dates from June 1–30 are present.

| Metric | Total |
|---|---:|
| Inquiries | 2,912 |
| Moderate intents | 588 |
| Bookings | 32 |

Daily rows were exported to `jeanel_co_june_2026_gold.csv`.

## Daily-row reconciliation against local CSVs

The CSV totals below are recomputed from dated daily rows. A positive difference means the gold layer is higher.

| Month | Metric | CSV daily sum | Gold | Gold − CSV | Matching days | Mismatching days |
|---|---|---:|---:|---:|---:|---:|
| July | Inquiries | 3,913 | 3,911 | -2 | 29 | 2 |
| July | Moderate/High | 713 | 793 | +80 | 3 | 28 |
| July | Bookings | 41 | 41 | 0 | 15 | 16 |
| August | Inquiries | 4,226 | 4,227 | +1 | 30 | 1 |
| August | Moderate/High | 751 | 689 | -62 | 4 | 27 |
| August | Bookings | 34 | 41 | +7 | 11 | 20 |

## Verdict

The gold layer does **not** match either CSV at daily grain.

- July inquiry differences occur on July 6 and July 26 (gold is lower by 1 on each).
- August inquiry difference occurs on August 2 (gold is higher by 1).
- July booking monthly totals happen to match, but 16 daily values differ; offsetting differences make the month total equal.
- Moderate counts differ materially because `p_looker_agent_daily_conversion.total_moderate_intents` is a staged official reporting metric with corrected chatbot logic. It is not definitionally identical to `t_inquiry_funnel_conversion_daily_v2.moderate_high_inquiries` used by the July/August CSV reports.
- Booking attribution also differs by layer, so equal or near-equal totals do not establish daily parity.

## August stale total row

`jeanel_co_aug_2026.csv` contains a final `Total` row of **3,966 inquiries, 634 Moderate/High, and 33 bookings**. Its 31 dated rows actually sum to **4,226 inquiries, 751 Moderate/High, and 34 bookings**. The embedded total row and the corresponding methodology totals are stale and must not be used for reconciliation.
