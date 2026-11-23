-- severity: error
select item_id from {{ ref('stg_outcomes') }} where status = 'closed' and close_date is null
