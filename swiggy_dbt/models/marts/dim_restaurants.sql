select 
restaurant_id, 
restaurant_name, 
city, cuisine, 
rating, 
rating_count, 
cost
from {{ ref('stg_restaurants') }}