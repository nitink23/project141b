from flask import Flask, request, jsonify
import asyncio
import aiohttp
from bs4 import BeautifulSoup

app = Flask(__name__)

# Functions to extract product details from a product page
def get_title(soup):
    try:
        title = soup.find('h1', class_='x-item-title__mainTitle')\
                    .find('span', class_='ux-textspans ux-textspans--BOLD').text
    except AttributeError:
        title = ""
    return title

def get_price(soup):
    try:
        price = soup.find('div', class_='x-price-primary').text
    except AttributeError:
        price = ""
    return price

def get_availability(soup):
    try:
        available = soup.find('div', class_='d-quantity__availability').text
    except AttributeError:
        available = ""
    return available

def get_rating(soup):
    try:
        rating = soup.find('div', class_='x-sellercard-atf__info')\
                     .find('span', class_='ux-textspans ux-textspans--PSEUDOLINK').text
    except AttributeError:
        rating = "No rating"
    return rating

def get_review(soup):
    try:
        review = soup.find('li', attrs={'data-testid': 'x-sellercard-atf__about-seller'})\
                     .find('span', class_='ux-textspans ux-textspans--SECONDARY').text
    except AttributeError:
        review = "No review"
    return review

async def fetch(session, url, headers):
    async with session.get(url, headers=headers) as response:
        return await response.text()

async def fetch_product_data(session, url, req_headers):
    try:
        html = await fetch(session, url, req_headers)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return None
    prod_soup = BeautifulSoup(html, "html.parser")
    product_data = {
        "title": get_title(prod_soup),
        "price": get_price(prod_soup),
        "availability": get_availability(prod_soup),
        "rating": get_rating(prod_soup),
        "review": get_review(prod_soup)
    }
    return product_data

async def scrape_ebay(search_term):
    req_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US, en;q=0.5'
    }
    search_url = f'https://www.ebay.com/sch/i.html?_nkw={search_term}'
    
    async with aiohttp.ClientSession() as session:
        # Fetch and parse the search results page asynchronously
        search_html = await fetch(session, search_url, req_headers)
        search_soup = BeautifulSoup(search_html, "html.parser")
        
        # Extract product links (skip the first link if necessary)
        link_elements = search_soup.find_all("a", class_="s-item__link")
        product_urls = [elem.get('href') for elem in link_elements[1:]]
        
        # Extract watchers count directly from the search page
        watcher_elements = search_soup.find_all("span", class_="s-item__dynamic s-item__watchCountTotal")
        watchers_list = [span.text.strip() for span in watcher_elements]
        
        # Create asynchronous tasks for fetching product pages concurrently
        tasks = [fetch_product_data(session, url, req_headers) for url in product_urls]
        results = await asyncio.gather(*tasks)
        
        # Compile the product data with the corresponding watchers count
        products_info = []
        for idx, product_data in enumerate(results):
            if product_data and product_data["title"]:
                product_data["watchers"] = watchers_list[idx] if idx < len(watchers_list) else ""
                products_info.append(product_data)
                
        return products_info

@app.route('/scrape', methods=['GET'])
async def scrape_endpoint():
    # Accept a query parameter "term" for search term (default: "shoes")
    search_term = request.args.get('term', 'shoes')
    products_info = await scrape_ebay(search_term)
    return jsonify(products_info)

if __name__ == '__main__':
    app.run(debug=True)
