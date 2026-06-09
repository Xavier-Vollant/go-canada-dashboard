# Paper Verification Review Exports

These CSV files come from the GO-Canada DOI post-processing review workflow.

## Files

- `paper_verification_summary.csv`: one row per paper DOI, with the full instrument list and paper-level review status.
- `paper_instrument_verification_status.csv`: one row per paper and instrument/component assignment, including the review decision when that assignment has been checked.

## Status Values

- `verified`: every instrument assignment for the paper has been reviewed.
- `partially_verified`: at least one instrument assignment for the paper has been reviewed, but others remain unchecked.
- `unverified`: no reviewed decision has been recorded yet.

The detailed file also includes `review_status`, `review_decision`, `corrected_instrument`, notes, evidence text, and `reviewed_at` where available.
