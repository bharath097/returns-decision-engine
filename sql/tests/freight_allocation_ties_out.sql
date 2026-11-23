-- severity: error
select lot_id from {{ ref('mart_item') }} group by 1
having abs(sum(allocated_freight) - any_value(inbound_freight)) > 0.01
