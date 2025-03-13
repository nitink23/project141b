import re
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from pydantic import BaseModel
from typing import List, Dict
import time
import hashlib
import json

app = FastAPI()

# Global caches with timestamps
# Format: {key: {"data": result_dict, "timestamp": time_added}}
product_cache: Dict[str, dict] = {}
auction_cache: Dict[str, dict] = {}
product_data_cache: Dict[str, dict] = {}

# Cache expiry time in seconds (10 minutes)
CACHE_EXPIRY_TIME = 600

# Request headers for all requests
req_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/123.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US, en;q=0.5'
}

# Precompiled regex pattern for seller info (for efficiency)
SELLER_INFO_REGEX = r'^(.*?)\s*\(([\d,]+)\)\s*([\d.]+%)$'

##############################################
# Helper Extraction Functions for Product Pages
# (These remain synchronous because they are CPU-bound and lightweight;
#  however, we offload them using asyncio.to_thread to prevent blocking.)
##############################################
def get_title(soup):
    try:
        title_tag = soup.find("h1", id="itemTitle")
        if title_tag:
            return title_tag.get_text(strip=True).replace("Details about  \xa0", "")
    except Exception:
        pass
    return ""

def get_price(soup):
    try:
        price_tag = soup.find("span", id="prcIsum")
        if not price_tag:
            price_tag = soup.find("span", id="mm-saleDscPrc")
        if price_tag:
            return price_tag.get_text(strip=True)
    except Exception:
        pass
    return ""

def get_images(soup):
    buttons = soup.find_all("button", class_="ux-image-grid-item image-treatment rounded-edges")
    images = []
    for btn in buttons:
        img = btn.find('img')
        if img and img.get('src'):
            images.append(img.get('src'))
    return images

def get_watchers(soup):
    try:
        divs = soup.find_all("div", class_="ux-section-icon-with-details__data-item-text")
        if divs:
            text = divs[0].text.strip()
            numbers = re.findall(r'\d+', text)
            return numbers[0] if numbers else ""
    except Exception:
        pass
    return ""

def get_condition(soup):
    try:
        condition_div = soup.find("div", class_='x-item-condition-text')
        if condition_div:
            span = condition_div.find("span", class_="clipped")
            if span:
                return span.text.strip()
    except Exception:
        pass
    return ""

def get_item_features(soup):
    features = {}
    try:
        container = soup.find("div", id="viTabs_0_is")
        if container:
            container = container.find("div", class_="ux-layout-section-evo__item ux-layout-section-evo__item--table-view")
            if container:
                rows = container.find_all("div", class_="ux-layout-section-evo__row")
                for row in rows:
                    dls = row.find_all("dl")
                    for dl in dls:
                        dt = dl.find("dt")
                        dd = dl.find("dd")
                        if dt and dd:
                            label = dt.get_text(strip=True)
                            value_container = dd.find("div", class_="ux-labels-values__values-content")
                            value = value_container.get_text(strip=True) if value_container else dd.get_text(strip=True)
                            features[label] = value
    except Exception:
        pass
    return features

##############################################
# Auction Detail Extraction Functions (for auction listings)
##############################################
def auction_get_title(item):
    try:
        return item.find("div", class_="s-item__title").text.strip()
    except Exception:
        return ""

def auction_get_price(item):
    try:
        return item.find("span", class_="s-item__price").text.strip()
    except Exception:
        return ""

def auction_get_bid_count(item):
    try:
        bid_elem = item.select_one("span.s-item__bids.s-item__bidCount")
        return bid_elem.text.strip() if bid_elem else ""
    except Exception:
        return ""

def auction_get_time_left(item):
    try:
        return item.find("span", class_="s-item__time-left").text.strip()
    except Exception:
        return ""

def auction_get_best_offer(item):
    try:
        bo_elem = item.select_one("div.s-item__dynamic.s-item__formatBestOfferEnabled a span")
        return bo_elem.text.strip() if bo_elem else ""
    except Exception:
        return ""

def auction_get_delivery_cost(item):
    try:
        delivery_elem = item.select_one("span.s-item__shipping.s-item__logisticsCost")
        return delivery_elem.text.strip() if delivery_elem else ""
    except Exception:
        return ""

def auction_get_authenticity(item):
    try:
        auth_elem = item.select_one("span.s-item__hotness.s-item__authorized-seller")
        return auth_elem.text.strip() if auth_elem else ""
    except Exception:
        return ""

def auction_get_product_image(item):
    try:
        image_wrapper = item.find("div", class_="s-item__image-wrapper image-treatment")
        if image_wrapper:
            img = image_wrapper.find("img")
            return img['src'].strip() if img and img.get('src') else ""
    except Exception:
        return ""
    return ""

def auction_get_product_link(item):
    try:
        a_tag = item.find("a", href=True)
        return a_tag['href'].strip() if a_tag else ""
    except Exception:
        return ""


def auction_get_seller_info(item):
    try:
        seller_info = item.find("span", class_="s-item__seller-info-text").text.strip()
    except AttributeError:
        seller_info = ""
    return seller_info

def parse_seller_info(seller_info):
    """
    Uses a precompiled regex for efficiency.
    Expected format: "seller_name (number) rating"
    """
    match = re.search(SELLER_INFO_REGEX, seller_info)
    if match:
        seller_name = match.group(1).strip()
        seller_no_reviews = match.group(2).replace(',', '')
        seller_rating = match.group(3)
        return seller_name, seller_no_reviews, seller_rating
    return seller_info, "", ""

##############################################
# Asynchronous Fetching Functions
##############################################
async def fetch_page(session: aiohttp.ClientSession, url: str, headers: dict) -> str:
    async with session.get(url, headers=headers, timeout=10) as response:
        if response.status != 200:
            raise HTTPException(status_code=response.status, detail=f"Error fetching {url}")
        return await response.text()

##############################################
# Endpoints
##############################################
@app.get("/auctions")
async def get_auctions(search_term: str = "iphone", pages: int = 3):
    """
    Asynchronously search eBay auctions for a given search term across the specified number of pages.
    Returns detailed auction data concurrently. Uses caching to speed up repeated requests.
    """
    # Create cache key based on search parameters
    cache_key = f"{search_term}_{pages}"
    
    # Check cache first
    cached_data = get_from_cache(auction_cache, cache_key)
    if cached_data:
        return JSONResponse(content=cached_data)
    
    # Fetch data if not in cache or expired
    tasks = []
    async with aiohttp.ClientSession() as session:
        for page in range(1, pages + 1):
            search_url = f'https://www.ebay.com/sch/i.html?_nkw={search_term}&LH_Auction=1&_pgn={page}'
            tasks.append(fetch_page(session, search_url, req_headers))
        pages_content = await asyncio.gather(*tasks)
    
    auctions = []
    for content in pages_content:
        # Offload parsing to a thread to avoid blocking the event loop.
        soup = await asyncio.to_thread(BeautifulSoup, content, "html.parser")
        items = soup.find_all("li", class_="s-item s-item__pl-on-bottom")
        for item in items:
            title = await asyncio.to_thread(auction_get_title, item)
            if not title or title == "Shop on eBay":
                continue
            price = await asyncio.to_thread(auction_get_price, item)
            product_link = await asyncio.to_thread(auction_get_product_link, item)
            bid_count = await asyncio.to_thread(auction_get_bid_count, item)
            time_left = await asyncio.to_thread(auction_get_time_left, item)
            best_offer = await asyncio.to_thread(auction_get_best_offer, item)
            delivery_cost = await asyncio.to_thread(auction_get_delivery_cost, item)
            authenticity = await asyncio.to_thread(auction_get_authenticity, item)
            product_image = await asyncio.to_thread(auction_get_product_image, item)
            seller_info_raw = await asyncio.to_thread(auction_get_seller_info, item)
            seller_name, seller_no_reviews, seller_rating = parse_seller_info(seller_info_raw)
            
            auctions.append({
                "title": title,
                "price": price,
                "product_link": product_link,
                "bid_count": bid_count,
                "time_left": time_left,
                "best_offer": best_offer,
                "delivery_cost": delivery_cost,
                "authenticity": authenticity,
                "product_image": product_image,
                "seller_info": seller_info_raw,
                "seller_name": seller_name,
                "seller_no_reviews": seller_no_reviews,
                "seller_rating": seller_rating
            })
    
    # Store in cache
    store_in_cache(auction_cache, cache_key, auctions)
    return JSONResponse(content=auctions)

##############################################
# Product Data Endpoint for a List of Auctions (POST /product-data)
##############################################
class AuctionItem(BaseModel):
    product_link: str
    class Config:
        extra = "ignore"

async def fetch_product_data(session: aiohttp.ClientSession, url: str, headers: dict) -> dict:
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status != 200:
                return {"product_link": url, "error": f"Status code {response.status}"}
            html = await response.text()
            # Offload parsing to a thread.
            soup = await asyncio.to_thread(BeautifulSoup, html, "html.parser")
            return {
                "images": await asyncio.to_thread(get_images, soup),
                "watchers": await asyncio.to_thread(get_watchers, soup),
                "condition": await asyncio.to_thread(get_condition, soup),
                "item_features": await asyncio.to_thread(get_item_features, soup),
                "product_link": url
            }
    except Exception as e:
        return {"product_link": url, "error": str(e)}

@app.post("/product-data")
async def get_product_data_endpoint(auction_list: List[AuctionItem]):
    """
    Given a JSON array of auctions (each with a product_link),
    fetch product details concurrently. Uses caching where possible.
    """
    # Create a cache key based on sorted list of URLs
    urls = sorted([auction.product_link for auction in auction_list if auction.product_link])
    cache_key = hashlib.md5(json.dumps(urls).encode()).hexdigest()
    
    # Check if we have this exact collection cached
    cached_data = get_from_cache(product_data_cache, cache_key)
    if cached_data:
        return JSONResponse(content=cached_data)
    
    # If not found in cache, fetch each URL (checking individual URL cache)
    product_data = []
    tasks = []
    to_fetch = []
    url_to_index = {}
    
    # First check individual URLs in product_cache
    for i, auction in enumerate(auction_list):
        url = auction.product_link
        if not url:
            continue
        
        # Check if this URL is already in the single product cache
        cached_product = get_from_cache(product_cache, url)
        if cached_product:
            product_data.append(cached_product)
        else:
            # Save the URL to fetch and its position
            to_fetch.append(url)
            url_to_index[url] = i
    
    # Fetch URLs not in cache
    if to_fetch:
        async with aiohttp.ClientSession() as session:
            for url in to_fetch:
                tasks.append(fetch_product_data(session, url, req_headers))
            
            new_data = await asyncio.gather(*tasks)
            
            # Cache individual results
            for url, result in zip(to_fetch, new_data):
                store_in_cache(product_cache, url, result)
                product_data.append(result)
    
    # Sort the results to match original order
    sorted_data = sorted(product_data, key=lambda x: urls.index(x["product_link"]))
    
    # Store the entire collection in cache
    store_in_cache(product_data_cache, cache_key, sorted_data)
    return JSONResponse(content=sorted_data)

##############################################
# Single Product Endpoint (GET /single-product)
##############################################
@app.get("/single-product")
async def single_product(product_link: str):
    """
    Given a product_link, asynchronously scrape its details.
    Uses caching to speed up repeated requests (cache expires after 10 minutes).
    """
    # Check cache
    cached_data = get_from_cache(product_cache, product_link)
    if cached_data:
        return JSONResponse(content=cached_data)
    
    # Fetch new data if not in cache or expired
    async with aiohttp.ClientSession() as session:
        result = await fetch_product_data(session, product_link, req_headers)
        # Store result with timestamp
        store_in_cache(product_cache, product_link, result)
        return JSONResponse(content=result)

# Function to clean expired cache entries for all caches
async def clean_expired_cache():
    while True:
        current_time = time.time()
        
        # Clean each cache
        for cache in [product_cache, auction_cache, product_data_cache]:
            expired_keys = [
                key for key, value in cache.items() 
                if current_time - value["timestamp"] > CACHE_EXPIRY_TIME
            ]
            for key in expired_keys:
                cache.pop(key, None)
            
        # Check every minute
        await asyncio.sleep(60)

# Start the cache cleaning task when app starts
@app.on_event("startup")
async def start_cache_cleaner():
    asyncio.create_task(clean_expired_cache())

# Helper function to check if cache entry is valid
def get_from_cache(cache, key):
    if key in cache:
        if time.time() - cache[key]["timestamp"] <= CACHE_EXPIRY_TIME:
            return cache[key]["data"]
    return None

# Helper function to store in cache
def store_in_cache(cache, key, data):
    cache[key] = {
        "data": data,
        "timestamp": time.time()
    }
