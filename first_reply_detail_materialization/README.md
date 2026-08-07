# First Reply Detail Materialization

Draft rollout package for moving `gulong_reporting.v_looker_first_reply_detail` off the live heavy query path.

## Purpose

This package implements the production-safe pattern:

1. build `gulong_reporting.t_first_reply_detail`
2. refresh it on a rolling window
3. replace `v_looker_first_reply_detail` with a thin passthrough view
4. keep the main scheduler entrypoint the same

## Files

- `00_bootstrap_t_first_reply_detail.sql`
- `01_refresh_t_first_reply_detail_procedure.sql`
- `02_swap_v_looker_first_reply_detail_to_passthrough.sql`
- `03_refresh_moderate_reporting_tables_with_first_reply.sql`
- `04_validation_queries.sql`

## Recommended Rollout Order

1. Run `00_bootstrap_t_first_reply_detail.sql`
2. Run `04_validation_queries.sql` and compare against the current live view
3. Run `01_refresh_t_first_reply_detail_procedure.sql`
4. Run `02_swap_v_looker_first_reply_detail_to_passthrough.sql`
5. Run `03_refresh_moderate_reporting_tables_with_first_reply.sql`
6. Re-run `04_validation_queries.sql`

## Notes

- This package does not remove business logic.
- Booking attribution should still live in precomputed physical tables downstream.
- The heavy raw-message logic remains, but it moves from dashboard time to scheduled refresh time.
