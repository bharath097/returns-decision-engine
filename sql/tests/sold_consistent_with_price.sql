-- severity: error
select item_id from {{ ref('stg_outcomes') }}
where (sold and sale_price <= 0) or ((not sold) and sale_price > 0)
