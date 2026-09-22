SELECT DISTINCT id, order_date, date_updated, customer_name, status, payment_status, total_amount_due, quantity, sku, brand, branch_name, remarks
FROM `gulong-chatbot-459723.gulong_backend.orders_raw`
WHERE REGEXP_CONTAINS(LOWER(COALESCE(customer_name,'')), r'pernad|howard|keith|alcantara|salvador|sandique|abucay|buarao|esquivel|angeles|catacutan|manimtim')
OR REGEXP_CONTAINS(LOWER(COALESCE(remarks,'')), r'9930869617|9052228494|9606589180|9171247917|9156589569|9266416672|9476139463|9190871879|9494425470|9959101911|jowelpernadjowea30|maribethsalvador82|shenalyn.esquivel01|ryanrobert.angeles|iamdrew1223|neilmanimtim|nsf.?1966|wqr.?912|ngt.?1580|gbe.?1708|car.?9463|new.?9642|nkp.?2033')
ORDER BY customer_name, order_date
