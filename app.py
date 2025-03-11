import asyncio
import aiohttp
import time
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from typing import Any

app = FastAPI()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Simple in-memory cache dictionary
cache = {}
CACHE_TIMEOUT = 300  # seconds

def set_cache(key: str, data: Any):
    cache[key] = {"data": data, "timestamp": time.time()}

def get_cache(key: str):
    entry = cache.get(key)
    if entry:
        if time.time() - entry["timestamp"] < CACHE_TIMEOUT:
            return entry["data"]
        else:
            del cache[key]
    return None

# Functions to extract product details from a product page
def get_title(soup):
    try:
        title = soup.find('h1', class_='x-item-title__mainTitle')\
                    .find('span', class_='ux-textspans ux-textspans--BOLD').text.strip()
    except AttributeError:
        title = ""
    return title

def get_price(soup):
    try:
        price = soup.find('div', class_='x-price-primary').text.strip()
    except AttributeError:
        price = ""
    return price

def get_availability(soup):
    try:
        available = soup.find('div', class_='d-quantity__availability').text.strip()
    except AttributeError:
        available = ""
    return available

def get_rating(soup):
    try:
        rating = soup.find('div', class_='x-sellercard-atf__info')\
                     .find('span', class_='ux-textspans ux-textspans--PSEUDOLINK').text.strip()
    except AttributeError:
        rating = "No rating"
    return rating

def get_review(soup):
    try:
        review = soup.find('li', attrs={'data-testid': 'x-sellercard-atf__about-seller'})\
                     .find('span', class_='ux-textspans ux-textspans--SECONDARY').text.strip()
    except AttributeError:
        review = "No review"
    return review

async def fetch(session, url, headers):
    async with session.get(url, headers=headers) as response:
        response.raise_for_status()  # immediately raise an error for bad responses
        return await response.text()

async def fetch_product_data(session, url, req_headers):
    try:
        html = await fetch(session, url, req_headers)
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return None
    # Offload BeautifulSoup parsing to a thread using lxml for speed
    prod_soup = await asyncio.to_thread(BeautifulSoup, html, "lxml")
    product_data = {
        "title": get_title(prod_soup),
        "price": get_price(prod_soup),
        "availability": get_availability(prod_soup),
        "rating": get_rating(prod_soup),
        "review": get_review(prod_soup)
    }
    return product_data

# Helper function to include the index with each fetch
async def fetch_with_index(idx, url, req_headers, session):
    data = await fetch_product_data(session, url, req_headers)
    return idx, data

async def scrape_ebay(search_term: str):
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/123.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US, en;q=0.5'
    }
    search_url = f'https://www.ebay.com/sch/i.html?_nkw={search_term}'
    
    async with aiohttp.ClientSession() as session:
        search_html = await fetch(session, search_url, req_headers)
        # Offload search page parsing to a thread
        search_soup = await asyncio.to_thread(BeautifulSoup, search_html, "lxml")
        
        link_elements = search_soup.find_all("a", class_="s-item__link")
        product_urls = [elem.get('href') for elem in link_elements[1:]] if link_elements else []
        
        watcher_elements = search_soup.find_all("span", class_="s-item__dynamic s-item__watchCountTotal")
        watchers_list = [span.text.strip() for span in watcher_elements] if watcher_elements else []
        
        tasks = [fetch_with_index(idx, url, req_headers, session) for idx, url in enumerate(product_urls)]
        products_info = []
        
        # Process tasks as they complete
        for future in asyncio.as_completed(tasks):
            idx, product_data = await future
            if product_data and product_data.get("title"):
                product_data["watchers"] = watchers_list[idx] if idx < len(watchers_list) else ""
                products_info.append(product_data)
                
        return products_info

@app.get("/scrape")
async def scrape_endpoint(term: str = "shoes"):
    # Check if the search term is in cache
    cached_data = get_cache(term)
    if cached_data is not None:
        logger.info("Loading from cache")
        return JSONResponse(content=cached_data)
    
    # Otherwise, scrape and update the cache
    products_info = await scrape_ebay(term)
    set_cache(term, products_info)
    return JSONResponse(content=products_info)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
