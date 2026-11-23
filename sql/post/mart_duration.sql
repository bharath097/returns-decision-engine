-- Fixed-price items as duration data: time until a fixed-price sale, with right-censoring.
-- An item unsold after the rollover window contributes the full window with event = 0.
select item_id, category, brand_tier, condition, premium_pct, listing_ym, source_type,
       least(days_listed, {{ var('rollover_days') }})::double as duration,
       case when sale_channel = 'fixed' then 1 else 0 end as event,
       status
from {{ ref('mart_item') }}
where channel = 'fixed_price'
