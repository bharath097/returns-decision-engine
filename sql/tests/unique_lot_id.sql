-- severity: error
select lot_id, count(*) as n from {{ ref('stg_lots') }} group by 1 having count(*) > 1
