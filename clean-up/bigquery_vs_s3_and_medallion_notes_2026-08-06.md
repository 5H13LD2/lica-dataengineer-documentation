# BigQuery Notes: BigQuery vs S3, Physical Tables, Stored Procedures, at Medallion Mapping

Date: `2026-08-06`

## Context

Ito ang summary ng napag-usapan natin mula doon sa out-of-topic na usapan about:

- paano gumagana ang BigQuery
- paano siya i-compare sa AWS S3
- ano ang role ng physical tables / stored procedures sa current setup
- saan pumapasok ang mga ito sa medallion architecture


## 1. Ano ba talaga ang BigQuery

Short version:

- Ang `BigQuery` ay hindi lang storage.
- Isa siyang:
  - serverless data warehouse
  - SQL query engine
  - analytics platform
  - may built-in scheduling / refresh patterns for some workloads

Mas tama isipin na:

- `BigQuery` = warehouse + compute + analytics serving layer
- `S3` = object/file storage lang

So hindi direct 1:1 comparison ang `BigQuery` vs `S3`.


## 2. BigQuery vs AWS S3

Mas magandang comparison:

- `BigQuery` is closer to `Redshift` plus some `Athena`-like convenience
- `Google Cloud Storage` ang mas direct counterpart ng `Amazon S3`

### `S3`

- bodega ng files
- good for raw CSV / Parquet / JSON / logs / archive
- walang native warehouse behavior by itself
- usually kailangan pa ng ibang tools for analytics and orchestration

Typical AWS stack:

- `S3`
- `Glue`
- `Athena`
- `Redshift`
- `Airflow` or ibang orchestration layer

### `BigQuery`

- managed analytical tables
- SQL-native
- built-in query engine
- puwedeng warehouse + transform layer + reporting layer
- may scheduled queries, views, procedures, partitions, clusters

Typical GCP analytics path:

1. load data into BigQuery
2. transform using SQL
3. build reporting tables/views
4. connect BI tools like Looker Studio


## 3. May sarili bang pipeline/orchestration si BigQuery

Partly yes.

Tama ang intuition na sa maraming analytics use cases, mas plug-and-play si BigQuery kaysa classic data-lake stack.

### Kayang gawin ni BigQuery directly

- store analytical tables
- run SQL transforms
- create views
- create physical reporting tables
- schedule SQL refreshes
- run procedures

### Pero hindi ibig sabihin nito na wala ka nang orchestration forever

Kapag simple ang use case:

- scheduled query
- SQL-only transforms
- dashboard refresh

madalas enough na si BigQuery.

Kapag mas complex:

- maraming dependent jobs
- retries and alerting
- branching workflows
- cross-system logic
- Python-heavy transforms
- data quality gates

doon pa rin useful ang:

- Airflow / Cloud Composer
- dbt orchestration
- Dagster / Prefect
- Cloud Workflows

Best framing:

- hindi “pinapalitan ni BigQuery lahat”
- mas tama na “binabawasan ni BigQuery ang dami ng infra na kailangan mo para sa analytics”


## 4. Views vs Physical Tables vs Procedures

### Views

Examples sa repo:

- `v_looker_first_reply_detail`
- `v_looker_first_reply_detail_all_cs`

Why they feel “auto-refresh”:

- live SQL objects sila
- every query, latest upstream data ang binabasa

So by definition, hindi mo sila “nirerefresh” like a physical table.

### Physical tables

Examples sa repo:

- `t_moderate_followup_detail`
- `t_moderate_followup_coverage`
- `t_moderate_booking_reconstruction`
- `t_actual_inquiry_booking_conversion_detail`
- `t_actual_inquiry_booking_conversion_daily`
- `t_actual_inquiry_booking_conversion_monthly`
- `cs_inquiries_breakdown_gold`
- `p_looker_agent_daily_conversion`

Why ginagamit sila:

- para bumilis ang dashboards
- para hindi live recompute lagi ang heavy SQL
- para may stable reporting snapshot / serving layer

### Stored procedure

Ginawa natin:

- `gulong_reporting.refresh_moderate_reporting_tables()`

Purpose:

- i-refresh in order ang tatlong physical reporting tables:
  - `t_moderate_followup_detail`
  - `t_moderate_followup_coverage`
  - `t_moderate_booking_reconstruction`

Scheduler entrypoint:

```sql
CALL `gulong-chatbot-459723.gulong_reporting.refresh_moderate_reporting_tables`();
```


## 5. Ano ang actual na na-apply natin

Na-apply natin:

- physical reporting tables
- stored procedure

Hindi natin na-apply:

- `CREATE MATERIALIZED VIEW`

Important distinction:

- sa strict BigQuery terms, ang `materialized view` ay special object type
- ang ginawa natin ay regular `CREATE OR REPLACE TABLE ... AS SELECT ...`

So mas accurate tawagin ang current pattern na:

- precomputed physical reporting tables
- refreshed by stored procedure

Informally, puwedeng tawaging “materialized tables” dahil precomputed sila, pero hindi iyon ang official BigQuery object type.


## 6. Ano ang nakita natin locally na precomputed / physical tables

Clear examples from local files:

- `gulong_reporting.cs_inquiries_breakdown_gold`
- `gulong_reporting.t_actual_inquiry_booking_conversion_detail`
- `gulong_reporting.t_actual_inquiry_booking_conversion_daily`
- `gulong_reporting.t_actual_inquiry_booking_conversion_monthly`
- `gulong_reporting.t_moderate_followup_detail`
- `gulong_reporting.t_moderate_followup_coverage`
- `gulong_reporting.t_moderate_booking_reconstruction`
- `gulong_reporting.p_looker_agent_daily_conversion`

Meaning:

- yes, meron talaga kayong materialized/precomputed physical reporting assets
- pero mostly regular tables sila, not BigQuery materialized views


## 7. Medallion Architecture Mapping sa current setup

### Bronze

Raw-ish ingestion / event / source layers.

Examples:

- `manychat_data.messages`
- `manychat_data.users_current`
- `chat_analysis.chat_analysis_data`
- `gulong_chatbot_live.turn_trace_log`

Role:

- raw events
- source extracts
- real-time-ish or near-raw data

### Silver

Curated operational / cleaned / business-usable entities.

Examples:

- `gulong_core.inquiry_assignments`
- `gulong_core.fb_inquiry_sessions`
- `gulong_core.inquiry_sessions`
- `gulong_core.moderate_intent_sessions`
- `gulong_core.orders_all`
- `gulong_core.orders_booked`
- `gulong_core.agent_aliases`

Role:

- normalized business tables
- cleaned keys and mappings
- operational truth layer for analytics

### Gold

Reporting / BI-ready / serving layer.

Examples:

- `gulong_reporting.v_looker_*`
- `gulong_reporting.t_moderate_followup_detail`
- `gulong_reporting.t_moderate_followup_coverage`
- `gulong_reporting.t_moderate_booking_reconstruction`
- `gulong_reporting.t_actual_inquiry_booking_conversion_*`
- `gulong_reporting.cs_inquiries_breakdown_gold`
- `gulong_reporting.p_looker_agent_daily_conversion`

Role:

- dashboard-facing outputs
- aggregated reporting tables
- fast Looker/BI sources
- reconstructed or business-semantic serving models


## 8. Saan pumapasok ang “materialized tables” sa medallion

Sa current repo/setup, karamihan ng tinatawag ninyong materialized or physical tables ay:

- `Gold layer`

Reason:

- built for reporting
- precomputed for speed and stability
- ginagamit as BI/Looker sources
- derived from curated `Silver` operational tables and some `Bronze` enrichments

So practical mapping:

- `Bronze` = raw upstream data
- `Silver` = `gulong_core`
- `Gold` = `gulong_reporting`


## 9. Best mental model for this project

Current project pattern:

```text
raw/event data -> curated operational tables -> reporting views -> physical reporting tables -> BI
```

Mas explicit version:

```text
manychat_data / chat_analysis / gulong_chatbot_live
  -> gulong_core
  -> gulong_reporting.v_*
  -> gulong_reporting.t_* / p_* / *_gold
  -> Looker Studio / reporting
```

Ito ay valid at common BigQuery-centric warehouse design.


## 10. Practical takeaway

- Tama ang intuition na BigQuery can act as more than just a database.
- Sa analytics use cases, kaya niyang i-collapse ang malaking part ng traditional stack.
- Pero ang “automatic” behavior ng views ay iba sa refresh behavior ng physical tables.
- Sa current setup, ang views ay live, habang ang physical reporting tables ay refreshed via SQL/procedure/schedule.
- Yung ginawa nating `refresh_moderate_reporting_tables()` procedure ay bahagi ng Gold serving layer operations.


## 11. Specific outcome from the work we did

Na-set up na ang BigQuery procedure:

- `gulong_reporting.refresh_moderate_reporting_tables()`

This refreshes:

- `t_moderate_followup_detail`
- `t_moderate_followup_coverage`
- `t_moderate_booking_reconstruction`

At ang pattern nito ay:

- keep old historical rows outside the rolling window
- rebuild recent rows from live/raw logic
- serve refreshed physical tables for reporting


## 12. One-line summary

Sa project na ito, ang `BigQuery` ang gumaganap bilang warehouse + SQL transform engine + reporting serving layer, habang ang mga `t_*`, `p_*`, at `*_gold` tables ay mostly `Gold` medallion outputs na precomputed physical tables, hindi BigQuery materialized views.
