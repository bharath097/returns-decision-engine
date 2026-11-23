-- Staging: ONE row per lot. The raw extract contains exact duplicates and late price
-- revisions; the most recently loaded row wins (ties broken by higher price).
select lot_id, source_id, cast(receipt_date as date) as receipt_date, manifest_flag,
       n_items_manifest, manifest_retail_total, lot_price, inbound_freight, acquisition_basis
from (
    select *, row_number() over (partition by lot_id order by loaded_at desc, lot_price desc) as rn
    from {{ ref('raw_lots') }}
)
where rn = 1
