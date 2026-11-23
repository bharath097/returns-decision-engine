-- Staging: ONE outcome row per item.
select * exclude (rn)
from (
    select *, row_number() over (partition by item_id order by status desc) as rn
    from {{ ref('raw_outcomes') }}
)
where rn = 1
