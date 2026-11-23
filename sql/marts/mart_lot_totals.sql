-- Lot-level totals used to allocate purchase cost to items.
select lot_id, count(*) as lot_items, sum(retail_value) as lot_retail_total
from {{ ref('stg_items') }}
group by 1
