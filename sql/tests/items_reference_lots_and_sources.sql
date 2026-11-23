-- severity: error
select i.item_id from {{ ref('stg_items') }} i
left join {{ ref('stg_lots') }} l using (lot_id)
left join {{ ref('stg_sources') }} s on s.source_id = i.source_id
where l.lot_id is null or s.source_id is null
