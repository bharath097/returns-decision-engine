-- severity: warn
-- Not a failure: reports duplicate / revised lot rows that staging resolved.
select lot_id, count(*) as n from {{ ref('raw_lots') }} group by 1 having count(*) > 1
