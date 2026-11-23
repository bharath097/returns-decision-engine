-- One row per lot: what it cost and what it has returned so far.
select
    lot_id,
    any_value(source_id) as source_id,
    any_value(source_type) as source_type,
    any_value(manifest_flag) as manifest_flag,
    any_value(acquisition_basis) as acquisition_basis,
    min(receipt_date) as receipt_date,
    count(*) as items,
    count(*) filter (where status = 'closed') as closed_items,
    (count(*) filter (where status = 'open') = 0) as lot_complete,
    any_value(lot_price) as lot_price,
    any_value(inbound_freight) as inbound_freight,
    any_value(lot_retail_total) as lot_retail_total,
    any_value(lot_price) / nullif(any_value(lot_retail_total), 0) as acquisition_rate,
    sum(net_revenue) as net_revenue,
    sum(final_net_value) as final_net_value,
    sum(contribution_margin) as lot_profit,
    sum(contribution_margin) / nullif(any_value(lot_retail_total), 0) as profit_per_retail_dollar
from {{ ref('mart_item') }}
group by lot_id
