-- severity: error
select item_id from {{ ref('stg_outcomes') }}
where status = 'open' and (sold or sale_price > 0 or close_date is not null)
