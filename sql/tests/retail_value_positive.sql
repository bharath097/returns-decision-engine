-- severity: error
select item_id from {{ ref('stg_items') }} where retail_value is null or retail_value <= 0
