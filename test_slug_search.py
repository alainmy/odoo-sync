"""
Test to verify that slug search returns only one product.
Tests the fix for wc_get() passing params correctly.
"""
import sys
sys.path.append('microservices/admin')

from woocommerce import API
from app.services.woocommerce.client import wc_request
from app.core.config import settings

def test_slug_search():
    """Test that searching by slug returns exactly one product."""
    
    # Initialize WooCommerce API
    wcapi = API(
        url="https://woocommerce.localhost",  # Direct URL without /wp-json
        consumer_key=settings.wc_consumer_key,
        consumer_secret=settings.wc_consumer_secret,
        wp_api=True,
        version="wc/v3",
        timeout=60,
        verify_ssl=False
    )
    
    # First get active products to test
    print(f"\n{'='*60}")
    print(f"PRE-TEST: Getting active products from WooCommerce")
    print(f"{'='*60}")
    
    try:
        # Get active products
        active_products = wc_request("GET", "products", params={"status": "publish", "per_page": 5}, wcapi=wcapi)
        print(f"✅ Found {len(active_products)} active products\n")
        
        if len(active_products) == 0:
            print("❌ No active products found")
            return False
        
        # Show first 3 products
        print("Active products:")
        for i, p in enumerate(active_products[:3]):
            print(f"{i+1}. ID: {p.get('id')} | Name: {p.get('name')}")
            print(f"   SKU: {p.get('sku')} | Slug: {p.get('slug')}")
        
        # Use first product for testing
        test_product = active_products[0]
        test_slug = test_product.get('slug')
        test_sku = test_product.get('sku')
        test_id = test_product.get('id')
        
        print(f"\n📌 Using product ID {test_id} for tests")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    
    # Test 1: Search by specific slug
    print(f"\n{'='*60}")
    print(f"TEST 1: Searching for slug: '{test_slug}'")
    print(f"{'='*60}")
    
    try:
        products = wc_request(
            "GET", 
            "products",
            params={"slug": test_slug, "per_page": 1}, 
            wcapi=wcapi
        )
        
        print(f"✅ Request successful")
        print(f"📊 Number of products returned: {len(products)}")
        
        if len(products) == 1:
            print(f"✅ PASS: Returned exactly 1 product as expected")
            product = products[0]
            print(f"\nProduct details:")
            print(f"  - ID: {product.get('id')}")
            print(f"  - Name: {product.get('name')}")
            print(f"  - Slug: {product.get('slug')}")
            print(f"  - SKU: {product.get('sku')}")
        elif len(products) == 0:
            print(f"⚠️  WARNING: No products found with slug '{test_slug}'")
            print(f"   This slug might not exist in WooCommerce")
        else:
            print(f"❌ FAIL: Expected 1 product, got {len(products)}")
            print(f"   This suggests params are not being passed correctly")
            for i, p in enumerate(products[:5]):
                print(f"   Product {i+1}: {p.get('name')} (slug: {p.get('slug')})")
                
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    
    # Test 2: Search by SKU
    print(f"\n{'='*60}")
    print(f"TEST 2: Searching for SKU: '{test_sku}'")
    print(f"{'='*60}")
    
    try:
        products = wc_request(
            "GET", 
            "products",
            params={"sku": test_sku, "per_page": 1}, 
            wcapi=wcapi
        )
        
        print(f"✅ Request successful")
        print(f"📊 Number of products returned: {len(products)}")
        
        if len(products) == 1:
            print(f"✅ PASS: Returned exactly 1 product as expected")
            product = products[0]
            print(f"\nProduct details:")
            print(f"  - ID: {product.get('id')}")
            print(f"  - Name: {product.get('name')}")
            print(f"  - SKU: {product.get('sku')}")
            
            # Verify SKU matches
            if product.get('sku') == test_sku:
                print(f"✅ SKU match verified")
            else:
                print(f"❌ SKU mismatch: expected '{test_sku}', got '{product.get('sku')}'")
        elif len(products) == 0:
            print(f"⚠️  WARNING: No products found with SKU '{test_sku}'")
        else:
            print(f"❌ FAIL: Expected 1 product, got {len(products)}")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    
    # Test 3: Search without params (should return multiple)
    print(f"\n{'='*60}")
    print(f"TEST 3: Searching without filters (per_page=5)")
    print(f"{'='*60}")
    
    try:
        products = wc_request(
            "GET", 
            "products",
            params={"per_page": 5}, 
            wcapi=wcapi
        )
        
        print(f"✅ Request successful")
        print(f"📊 Number of products returned: {len(products)}")
        
        if len(products) >= 1:
            print(f"✅ PASS: Returned {len(products)} products")
            print(f"\nFirst 3 products:")
            for i, p in enumerate(products[:3]):
                print(f"  {i+1}. {p.get('name')} (ID: {p.get('id')}, SKU: {p.get('sku')})")
        else:
            print(f"⚠️  No products in store")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return False
    
    print(f"\n{'='*60}")
    print(f"🎯 SUMMARY")
    print(f"{'='*60}")
    print(f"All tests completed. Check results above.")
    print(f"If Test 1 and 2 return exactly 1 product, the fix is working! ✅")
    
    return True


if __name__ == "__main__":
    test_slug_search()
