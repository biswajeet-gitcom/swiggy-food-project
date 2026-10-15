select 
    user_id::number as customer_id, 
    name as customer_name, 
    lower(email) as email,
    try_to_number(age) as age, 
    gender, 
    marital_status, 
    occupation,
    monthly_income,
    education,
    try_to_number(family_size) as family_size
from {{ source('raw', 'USERS') }} where try_to_number(user_id) is not null