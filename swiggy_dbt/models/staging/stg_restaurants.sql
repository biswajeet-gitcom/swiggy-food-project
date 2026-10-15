select
    r_id :: number as restaurant_id,
    name as restaurant_name,
    trim(coalesce(regexp_substr(r_city, '[^,]+$'), r_city)) as city,
    try_to_decimal(nullif(rating, ' -- '), 3, 1) as rating,
    try_to_number(regexp_substr(rating_count, '[0-9]+')) as rating_count,
    try_to_number(regexp_substr(cost, '[0-9]+')) as cost,
    cuisine,
    lic_no as license_no
from {{ source('raw', 'RESTAURANTS') }} where try_to_number(r_id) is not null