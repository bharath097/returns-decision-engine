-- severity: error
-- allocated lot cost over a lot's items must equal the lot price (tolerance 1 cent)
select lot_id, sum(allocated_lot_cost) as allocated, any_value(lot_price) as lot_price
from {{ ref('mart_item') }} group by 1 having abs(sum(allocated_lot_cost) - any_value(lot_price)) > 0.01
