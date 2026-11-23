-- severity: warn
-- Not a failure: reports exact duplicate item rows that staging removed.
select item_id, count(*) as n from {{ ref('raw_items') }} group by 1 having count(*) > 1
