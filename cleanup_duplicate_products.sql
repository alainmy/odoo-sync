-- Script to identify and clean duplicate WooCommerce IDs in product_sync table
-- Run this BEFORE applying migration 009 to avoid constraint violations

-- Step 1: Find all duplicate WooCommerce IDs
SELECT 
    woocommerce_id, 
    instance_id,
    COUNT(*) as duplicate_count,
    GROUP_CONCAT(odoo_id ORDER BY last_synced_at DESC) as odoo_ids,
    GROUP_CONCAT(last_synced_at ORDER BY last_synced_at DESC) as sync_dates
FROM product_sync
WHERE woocommerce_id IS NOT NULL
GROUP BY woocommerce_id, instance_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC;

-- Step 2: For each duplicate group, keep only the most recently synced record
-- Delete older duplicates (manual cleanup - review the results from Step 1 first)

-- Example cleanup for WooCommerce ID 400, instance 1:
-- DELETE FROM product_sync 
-- WHERE woocommerce_id = 400 
--   AND instance_id = 1 
--   AND odoo_id NOT IN (
--       SELECT odoo_id FROM (
--           SELECT odoo_id 
--           FROM product_sync 
--           WHERE woocommerce_id = 400 AND instance_id = 1
--           ORDER BY last_synced_at DESC 
--           LIMIT 1
--       ) as keeper
--   );

-- Step 3: Verify no duplicates remain
SELECT 
    woocommerce_id, 
    instance_id,
    COUNT(*) as count
FROM product_sync
WHERE woocommerce_id IS NOT NULL
GROUP BY woocommerce_id, instance_id
HAVING COUNT(*) > 1;

-- If Step 3 returns 0 rows, you're ready to apply migration 009
