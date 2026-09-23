-- Invariant: pending (censored) deals must carry no realized break label.
-- Fails on any pending deal that leaked a ground-truth outcome.
select deal_id, status, ground_truth_break_label
from {{ ref('mart_deal_scorecard') }}
where status = 'pending'
  and ground_truth_break_label is not null
