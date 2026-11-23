-- severity: error
select item_id, count(*) as n from {{ ref('stg_items') }} group by 1 having count(*) > 1
