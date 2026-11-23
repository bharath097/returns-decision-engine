-- severity: error
select item_id from {{ ref('stg_items') }} where (channel = 'fixed_price') <> (premium_pct > 0)
