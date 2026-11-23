-- Staging: one row per source.
select source_id, source_name, source_type, region, cast(active_from as date) as active_from
from {{ ref('raw_sources') }}
