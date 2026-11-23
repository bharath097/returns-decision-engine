-- One row per item with every cost, revenue and recovery definition.
--   gross_recovery       = sale_price / retail_value (0 if unsold; the headline measure)
--   net_revenue          = sale (unless refunded) - fees - shipping + fallback value
--   net_recovery         = net_revenue / retail_value
--   final_net_value_base = net_revenue - handling - holding (shelf + capital)   [before custom costs]
--   contribution_base    = final_net_value_base - allocated lot price - allocated inbound freight
-- Open items (outcome not final) carry NULL outcome economics.
with j as (
    select
        i.*,
        s.source_type, s.region,
        l.manifest_flag, l.acquisition_basis, l.lot_price, l.inbound_freight, l.n_items_manifest,
        t.lot_items, t.lot_retail_total,
        o.status, o.sold, o.sale_channel, o.sale_price, o.days_listed, o.days_to_sale_fixed, o.rolled_to_auction,
        o.bidders, o.watchers, o.refund_flag, o.fallback_value, o.fees, o.shipping_cost, o.handling_minutes,
        o.holding_days, o.close_date,
        w.holding_cost_per_day, w.freight_weight
    from {{ ref('stg_items') }} i
    join {{ ref('stg_outcomes') }} o using (item_id)
    join {{ ref('stg_lots') }} l using (lot_id)
    join {{ ref('stg_sources') }} s on s.source_id = i.source_id
    join {{ ref('mart_lot_totals') }} t using (lot_id)
    join econ_weight_class w on w.weight_class = i.weight_class
),
k as (
    select
        j.*,
        cast(listed_date as date) as listing_date,
        strftime(cast(listed_date as date), '%Y-%m') as listing_ym,
        (status = 'closed') as is_closed,
        j.lot_price * j.retail_value / nullif(j.lot_retail_total, 0) as allocated_lot_cost,
        round(j.inbound_freight * j.freight_weight / nullif(sum(j.freight_weight) over (partition by j.lot_id), 0), 6) as allocated_freight,
        j.handling_minutes * {{ var('labor_cost_per_minute') }} as handling_cost,
        j.holding_days * j.holding_cost_per_day as holding_cost_shelf
    from j
),
m as (
    select
        k.*,
        k.allocated_lot_cost * {{ var('cost_of_capital_annual') }} / 365.0 * k.holding_days as holding_cost_capital,
        case when status = 'closed' then
            (case when refund_flag then 0 else sale_price end) - fees - shipping_cost + fallback_value
        end as net_revenue
    from k
)
select
    m.*,
    m.holding_cost_shelf + m.holding_cost_capital as holding_cost,
    case when status = 'closed' then sale_price / retail_value end as gross_recovery,
    case when status = 'closed' then net_revenue / retail_value end as net_recovery,
    case when status = 'closed' then net_revenue - handling_cost - holding_cost_shelf - holding_cost_capital end as final_net_value_base,
    case when status = 'closed' then net_revenue - handling_cost - holding_cost_shelf - holding_cost_capital
                                     - allocated_lot_cost - allocated_freight end as contribution_margin_base
from m
