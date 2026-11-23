-- Randomized fixed-price pilot: items assigned to fixed-price-first (with a premium) or to the auction control.
-- `complete_at_horizon` marks items listed early enough that the whole fixed window + rollover has elapsed.
select item_id, category, condition, brand_tier, source_type, pilot_arm as arm, premium_pct,
       listing_date, listing_ym, retail_value, prod_pred_expected_auction_recovery,
       status, sold, sale_channel, sale_price, days_listed, net_revenue, final_net_value, contribution_margin,
       (status = 'closed') as complete_at_horizon
from {{ ref('mart_item') }}
where pilot_arm in ('fixed', 'auction')
