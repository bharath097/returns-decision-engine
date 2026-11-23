-- Category x month KPIs (closed items only).
select category, listing_ym,
       count(*) as items_closed,
       avg(cast(sold as int)) as sell_through,
       sum(sale_price) / nullif(sum(retail_value), 0) as gross_recovery_all_listed,
       sum(net_revenue) / nullif(sum(retail_value), 0) as net_recovery_all_listed,
       avg(final_net_value) as final_net_value_per_item
from {{ ref('mart_item') }}
where status = 'closed'
group by 1, 2
