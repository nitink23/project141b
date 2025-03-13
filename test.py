import requests
import time

BASE_URL = "https://project141b.onrender.com"

def test_auctions():
    print("Testing GET /auctions...")
    url = f"{BASE_URL}/auctions"
    params = {"search_term": "shoes", "pages": 1}  # You can adjust search_term and pages as needed.
    start_time = time.time()
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        auctions = response.json()
        elapsed = time.time() - start_time
        print(f"GET /auctions took {elapsed:.2f} seconds and returned {len(auctions)} items.")
        return auctions
    except Exception as e:
        print("Error during GET /auctions:", e)
        return []

def test_product_data(auctions):
    print("Testing POST /product-data...")
    # Build a JSON array from the auctions data
    payload = [ {"product_link": auction["product_link"]} for auction in auctions if auction.get("product_link") ]
    if not payload:
        print("No valid product links found in auctions to test POST /product-data.")
        return []
    
    url = f"{BASE_URL}/product-data"
    start_time = time.time()
    try:
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        product_data = response.json()
        elapsed = time.time() - start_time
        print(f"POST /product-data took {elapsed:.2f} seconds and returned {len(product_data)} items.")
        return product_data
    except Exception as e:
        print("Error during POST /product-data:", e)
        return []

def test_single_product(product_link):
    print("Testing GET /single-product...")
    url = f"{BASE_URL}/single-product"
    params = {"product_link": product_link}
    start_time = time.time()
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        elapsed = time.time() - start_time
        print(f"GET /single-product took {elapsed:.2f} seconds.")
        return data
    except Exception as e:
        print("Error during GET /single-product:", e)
        return {}

def main():
    auctions = test_auctions()
    if auctions:
        product_data = test_product_data(auctions)
        # Test single product using the first valid product link from auctions
        first_link = auctions[0].get("product_link")
        if first_link:
            single_product = test_single_product(first_link)
            print("Single product data:")
            print(single_product)
        else:
            print("No valid product link found in first auction to test single product.")
    else:
        print("No auctions data returned.")

if __name__ == "__main__":
    main()
