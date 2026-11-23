-- severity: error
select i.item_id from {{ ref('stg_items') }} i left join {{ ref('stg_outcomes') }} o using (item_id) where o.item_id is null
