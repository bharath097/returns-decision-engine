-- Staging: ONE row per item (the raw listing extract contains exact duplicates).
select * exclude (rn, loaded_at)
from (
    select *, row_number() over (partition by item_id order by loaded_at) as rn
    from {{ ref('raw_items') }}
)
where rn = 1
