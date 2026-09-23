-- Invariant: a deal's resolution can never precede its announcement.
-- Fails (returns rows) on any impossible lifecycle ordering.
select deal_id, announce_date, resolution_date
from {{ source('silver_sources', 'silver_sat_deal') }}
where resolution_date is not null
  and resolution_date < announce_date
