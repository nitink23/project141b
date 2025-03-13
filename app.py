import re
import asyncio
import aiohttp
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from bs4 import BeautifulSoup
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI()

# Global cache for single product data (in-memory)
product_cache: Dict[str, dict] = {}

# Request headers for all requests
req_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/123.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US, en;q=0.5'
}

##############################################
# Helper Extraction Functions for Product Pages
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
        if divs and len(divs) > 0:
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
                            if value_container:
                                value = value_container.get_text(strip=True)
                            else:
                                value = dd.get_text(strip=True)
                            features[label] = value
    except Exception:
        pass
    return features

##############################################
# Auction Search Endpoint (GET /auctions)
##############################################
def get_product_link(item):
    try:
        a_tag = item.find("a", href=True)
        return a_tag['href'].strip() if a_tag else ""
    except Exception:
        return ""

async def fetch_page(session: aiohttp.ClientSession, url: str, headers: dict) -> str:
    async with session.get(url, headers=headers, timeout=10) as response:
        if response.status != 200:
            raise HTTPException(status_code=response.status, detail=f"Error fetching {url}")
        return await response.text()

@app.get("/auctions")
async def get_auctions(search_term: str = "iphone", pages: int = 3):
    tasks = []
    async with aiohttp.ClientSession() as session:
        for page in range(1, pages + 1):
            search_url = f'https://www.ebay.com/sch/i.html?_nkw={search_term}&LH_Auction=1&_pgn={page}'
            tasks.append(fetch_page(session, search_url, req_headers))
        pages_content = await asyncio.gather(*tasks)
    
    auctions = []
    for content in pages_content:
        soup = BeautifulSoup(content, "html.parser")
        items = soup.find_all("li", class_="s-item s-item__pl-on-bottom")
        for item in items:
            title_tag = item.find("div", class_="s-item__title")
            if not title_tag or title_tag.text.strip() == "Shop on eBay":
                continue
            auction_data = {
                "title": title_tag.text.strip(),
                "price": get_price(item),
                "product_link": get_product_link(item)
            }
            auctions.append(auction_data)
    return JSONResponse(content=auctions)

##############################################
# Product Data Endpoint for a List of Auctions (POST /product-data)
##############################################
class AuctionItem(BaseModel):
    product_link: str

# Use a custom root type so the input is a JSON array.
class AuctionList(BaseModel):
    __root__: List[AuctionItem]

async def fetch_product_data(session: aiohttp.ClientSession, url: str, headers: dict) -> dict:
    try:
        async with session.get(url, headers=headers, timeout=10) as response:
            if response.status != 200:
                return {"product_link": url, "error": f"Status code {response.status}"}
            html = await response.text()
            soup = BeautifulSoup(html, "html.parser")
            return {
                "title": get_title(soup),
                "price": get_price(soup),
                "images": get_images(soup),
                "watchers": get_watchers(soup),
                "condition": get_condition(soup),
                "item_features": get_item_features(soup),
                "product_link": url
            }
    except Exception as e:
        return {"product_link": url, "error": str(e)}

@app.post("/product-data")
async def get_product_data_endpoint(auction_list: AuctionList):
    # auction_list.__root__ is a list of AuctionItem.
    tasks = []
    async with aiohttp.ClientSession() as session:
        for auction in auction_list.__root__:
            url = auction.product_link
            if url:
                tasks.append(fetch_product_data(session, url, req_headers))
        product_data = await asyncio.gather(*tasks)
    return JSONResponse(content=product_data)

##############################################
# Single Product Endpoint (GET /single-product)
##############################################
@app.get("/single-product")
async def single_product(product_link: str):
    if product_link in product_cache:
        return JSONResponse(content=product_cache[product_link])
    
    async with aiohttp.ClientSession() as session:
        result = await fetch_product_data(session, product_link, req_headers)
        product_cache[product_link] = result
        return JSONResponse(content=result)

# To run the app, save this file (e.g., app.py) and run:
# uvicorn app:app --reload
