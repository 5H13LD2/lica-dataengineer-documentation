# Sarah Followup Tag Logic

## Goal

I-upgrade ang current moderate followup logic para masunod ang actual business process:

- manggagaling ang moderate inquiry sa `Chatbot/JCo`
- later mae-endorse o mahahandle ito ni `sarah gulongph`
- kailangan mabilang kung alin ang tunay na `need followup`
- hindi sapat ang current logic na `may CS reply pero walang followup`

Ang bagong target definition ay tag-driven at assignment-aware.

## Current Problem

Ang existing field na `no_followup_session_count` sa `t_moderate_followup_coverage` ay ito lang ang logic:

- `reply_status = 'Has CS Reply'`
- `followup_count = 0`

Hindi nito kino-consider:

- kung galing ba talaga sa `Chatbot/JCo`
- kung si `sarah gulongph` ba ang current handler
- kung may ManyChat `booked` marker na
- kung may `no need follow` / `Stop Follow Up` marker na
- kung may chatbot moderate labels na nagpapatunay na kabilang ito sa intended moderate followup pool

## New Business Logic

### In Scope

Kasama sa Sarah followup pool ang session kung:

- `source_agent_name = 'Chatbot/JCo'`
- `reporting_agent_name = 'sarah gulongph'`
- may kahit isa sa:
  - `Moderate Intent Tag From Chatbot`
  - `Moderate Intent CF From Chatbot`

### Exclusions

Hindi na dapat isama sa `need followup` kung may kahit isa sa mga ito:

- label: `booked`
- tag: `booked-*`
- label: `no need follow`
- tag: `Stop Follow Up`
- tag: `Stop Chatbot`

### Need Followup Definition

`need followup = yes` kung:

- in-scope Sarah Chatbot/JCo moderate
- may chatbot moderate label
- walang booked marker
- walang no-need-followup marker

## Actual Data Sources

Ginagamit ng upgraded logic ang mga ito:

- `gulong_reporting.v_looker_first_reply_detail`
- `manychat_data.labels_current`
- `manychat_data.tags_current`
- existing followup rollups from `t_moderate_followup_detail`

## Fields Added To Coverage Logic

Idinagdag sa `v_looker_moderate_followup_coverage`:

- `has_moderate_intent_tag_from_chatbot_label`
- `has_moderate_intent_cf_from_chatbot_label`
- `has_moderate_chatbot_label`
- `has_booked_label`
- `has_booked_tag`
- `has_any_booked_marker`
- `has_no_need_follow_label`
- `has_stop_followup_tag`
- `has_followup_stop_marker`
- `has_followup_eligible_tag`
- `sarah_followup_tag_logic_status`
- `needs_followup_by_tag_logic`
- `needs_followup_by_tag_logic_session_count`

## Recommended Metric

Para sa bagong dashboard metric, gamitin:

```sql
SUM(needs_followup_by_tag_logic_session_count)
```

Ito ang bagong count ng:

- moderate na galing `Chatbot/JCo`
- napunta kay `sarah gulongph`
- wala pang booked marker
- wala pang no-need-followup marker

## Important Note

Hindi tinanggal ang legacy field na `no_followup_session_count`.

Reason:

- para hindi masira ang existing dashboards
- para may parallel validation muna between:
  - old reply/followup logic
  - new tag-driven Sarah followup logic

## Suggested Stakeholder Wording

`Need Followup` now means:

> Chatbot/JCo moderate sessions currently handled by Sarah that still do not have a booked marker or a no-need-followup marker.

Hindi na ito simpleng:

> replied but not yet followed up

## Next Step

Pagkatapos i-review ang logic:

1. Rebuild `v_looker_moderate_followup_coverage`
2. Refresh `t_moderate_followup_coverage`
3. Validate sample users against ManyChat labels/tags
4. Update Looker metric to use `needs_followup_by_tag_logic_session_count`
