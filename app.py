import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException
from bs4 import BeautifulSoup

app = FastAPI()

# Extraction functions for auction details (synchronous)
def get_title(item):
    try:
        title = item.find("div", class_="s-item__title").text.strip()
    except AttributeError:
        title = ""
    return title

def get_price(item):
    try:
        price = item.find("span", class_="s-item__price").text.strip()
    except AttributeError:
        price = ""
    return price

def get_bid_count(item):
    try:
        bid_elem = item.select_one("span.s-item__bids.s-item__bidCount")
        bid_count = bid_elem.text.strip() if bid_elem else ""
    except AttributeError:
        bid_count = ""
    return bid_count

def get_time_left(item):
    try:
        time_left = item.find("span", class_="s-item__time-left").text.strip()
    except AttributeError:
        time_left = ""
    return time_left

def get_best_offer(item):
    try:
        bo_elem = item.select_one("div.s-item__dynamic.s-item__formatBestOfferEnabled a span")
        best_offer = bo_elem.text.strip() if bo_elem else ""
    except AttributeError:
        best_offer = ""
    return best_offer

def get_delivery_cost(item):
    try:
        delivery_elem = item.select_one("span.s-item__shipping.s-item__logisticsCost")
        delivery_cost = delivery_elem.text.strip() if delivery_elem else ""
    except AttributeError:
        delivery_cost = ""
    return delivery_cost

def get_authenticity(item):
    try:
        auth_elem = item.select_one("span.s-item__hotness.s-item__authorized-seller")
        authenticity = auth_elem.text.strip() if auth_elem else ""
    except AttributeError:
        authenticity = ""
    return authenticity

def get_product_image(item):
    try:
        image_wrapper = item.find("div", class_="s-item__image-wrapper image-treatment")
        if image_wrapper:
            img = image_wrapper.find("img")
            prod_img = img['src'].strip() if img and img.has_attr('src') else ""
        else:
            prod_img = ""
    except AttributeError:
        prod_img = ""
    return prod_img

def get_product_link(item):
    try:
        a_tag = item.find("a", href=True)
        product_link = a_tag['href'].strip() if a_tag else ""
    except AttributeError:
        product_link = ""
    return product_link

def get_seller_info(item):
    try:
        seller_info = item.find("span", class_="s-item__seller-info-text").text.strip()
    except AttributeError:
        seller_info = ""
    return seller_info

# Asynchronous function to fetch a single page
async def fetch_page(session: aiohttp.ClientSession, url: str, headers: dict) -> str:
    async with session.get(url, headers=headers) as response:
        if response.status != 200:
            raise HTTPException(status_code=response.status, detail=f"Error fetching {url}")
        return await response.text()

@app.get("/auctions")
async def get_auctions(search_term: str = "iphone", pages: int = 3):
    """
    Scrape eBay auctions for a given search term across a specified number of pages.
    Default is 3 pages.
    """
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                      'AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/123.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US, en;q=0.5'
    }
    
    tasks = []
    # Create URLs for pages 1 to `pages`
    for page in range(1, pages + 1):
        search_url = f'https://www.ebay.com/sch/i.html?_nkw={search_term}&LH_Auction=1&_pgn={page}'
        tasks.append(search_url)
    
    auctions = []
    async with aiohttp.ClientSession() as session:
        # Fetch all pages concurrently
        pages_content = await asyncio.gather(*[fetch_page(session, url, req_headers) for url in tasks])
        
        # Process each fetched page
        for content in pages_content:
            soup = BeautifulSoup(content, "html.parser")
            items = soup.find_all("li", class_="s-item s-item__pl-on-bottom")
            for item in items:
                title = get_title(item)
                if not title or title == "Shop on eBay":
                    continue
                price = get_price(item)
                bid_count = get_bid_count(item)
                time_left = get_time_left(item)
                best_offer = get_best_offer(item)
                delivery_cost = get_delivery_cost(item)
                authenticity = get_authenticity(item)
                prod_img = get_product_image(item)
                product_link = get_product_link(item)
                seller_info = get_seller_info(item)
                
                auction_data = {
                    "title": title,
                    "price": price,
                    "bid_count": bid_count,
                    "time_left": time_left,
                    "best_offer": best_offer,
                    "delivery_cost": delivery_cost,
                    "authenticity": authenticity,
                    "prod_img": prod_img,
                    "product_link": product_link,
                    "seller_info": seller_info
                }
                auctions.append(auction_data)
                
    return auctions

# To run the app, save this file (e.g., app.py) and run:
# uvicorn app:app --reload
