-- severity: error
select item_id from {{ ref('stg_items') }} where cast(listed_date as date) < cast(receipt_date as date)
