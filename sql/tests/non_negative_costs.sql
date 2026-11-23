-- severity: error
select item_id from {{ ref('stg_outcomes') }} where fees < 0 or shipping_cost < 0 or handling_minutes < 0 or holding_days < 0
