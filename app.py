import re
import logging
from typing import TypedDict, List, Optional, Tuple
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup, Tag
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import urllib.parse
import os
import sys
import webbrowser

# ====================================================================
# 1. CONFIGURATION & TYPES
# ====================================================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

MAX_PAGES_ALLOWED = 50


class ProductData(TypedDict):
    title: str
    total_price: float
    unit_price_raw: Optional[str]
    unit_price_kg: float
    link: str
    product_id: str


class AppConfig:
    URL_BASE_AMAZON = "https://www.amazon.fr"
    MAX_TITLE_LENGTH = 50
    API_PORT = 5001

    SELECTORS = {
        "PRODUCT_BLOCK": 'div[data-component-type="s-search-result"]',
        "TITLE": 'h2 span',
        "LINK": 'a',
        "TOTAL_PRICE": '.a-price .a-offscreen',
        "UNIT_PRICE_BLOCK": "span.a-size-base.a-color-secondary",
    }


REGEX_UNIT_PRICE = r"([\d.,\s]+)€\s*(?:/|/\s*|/)?\s*(kg|100\s*g)"

# ====================================================================
# 2. CLASSE DE CALCUL ET TRANSFORMATION
# ====================================================================


class PriceCalculator:
    @staticmethod
    def clean_total_price(price_text: str) -> float:
        try:
            cleaned = price_text.replace('€', '').replace('\xa0', '').replace(' ', '').replace(',', '.').strip()
            return float(cleaned)
        except ValueError:
            return 0.0

    @staticmethod
    def calculate_price_per_kg(value: float, unit: str) -> float:
        if value <= 0:
            return 0.0
        unit = unit.lower().strip()
        if unit == 'kg':
            return value
        if unit == '100g':
            return value * 10.0
        return 0.0

    @staticmethod
    def extract_amazon_unit_price(product_tag: Tag) -> Tuple[float, str, str]:
        price_blocks = product_tag.select(AppConfig.SELECTORS["UNIT_PRICE_BLOCK"])

        for span in price_blocks:
            text = span.get_text(strip=True)
            match = re.search(REGEX_UNIT_PRICE, text)

            if match:
                raw_text = text
                value_str = match.group(1).replace(',', '.').replace(' ', '').strip()
                unit_str = match.group(2).replace(' ', '').strip()

                try:
                    unit_price_value = float(value_str)
                    return unit_price_value, unit_str, raw_text
                except ValueError:
                    continue

        return 0.0, "N/A", "N/A"


# ====================================================================
# 3. CLASSE DE SCRAPING AVEC SELENIUM
# ====================================================================


class AmazonScraper:
    def __init__(self, headless: bool = True):
        self._headless = headless

    def _create_driver(self):
        """Crée un driver Selenium avec les options appropriées"""
        chrome_options = Options()
        if self._headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # User agent pour éviter la détection
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except Exception as e:
            logger.error(f"Erreur création driver: {e}")
            raise

    def _extract_title(self, product_tag: Tag) -> str:
        title_element = product_tag.select_one(AppConfig.SELECTORS["TITLE"])
        full_title = title_element.text.strip() if title_element else "Titre non trouvé"
        if len(full_title) > AppConfig.MAX_TITLE_LENGTH:
            return full_title[:AppConfig.MAX_TITLE_LENGTH].strip() + '...'
        return full_title

    def _extract_total_price(self, product_tag: Tag) -> float:
        total_price_element = product_tag.select_one(AppConfig.SELECTORS["TOTAL_PRICE"])
        total_price_text = total_price_element.text.strip() if total_price_element else "0,00 €"
        return PriceCalculator.clean_total_price(total_price_text)

    def _extract_link(self, product_tag: Tag) -> str:
        all_links = product_tag.select(AppConfig.SELECTORS["LINK"])
        for link_element in all_links:
            href = link_element.get('href', '')
            if href.startswith('/') and ('/dp/' in href or '/gp/product/' in href):
                link = AppConfig.URL_BASE_AMAZON + href
                return link.split('?')[0] if '?' in link else link
        return "Lien non trouvé"

    def _process_product_block(self, product_tag: Tag, index: int) -> ProductData:
        title = self._extract_title(product_tag)
        total_price = self._extract_total_price(product_tag)
        link = self._extract_link(product_tag)

        value_amz, unit_amz, text_amz = PriceCalculator.extract_amazon_unit_price(product_tag)
        unit_price_kg = PriceCalculator.calculate_price_per_kg(value_amz, unit_amz)

        product_id = f"prod_{index}_{hash(title + str(total_price))}"

        return ProductData(
            title=title,
            total_price=total_price,
            unit_price_raw=text_amz,
            unit_price_kg=unit_price_kg,
            link=link,
            product_id=product_id
        )

    def scrape(self, term: str, pages_count: int = 1) -> List[ProductData]:
        all_results: List[ProductData] = []
        encoded_term = urllib.parse.quote_plus(term)

        logger.info(f"Starting scrape for: '{term}' over {pages_count} pages.")

        driver = None
        try:
            driver = self._create_driver()

            for page_num in range(1, pages_count + 1):
                logger.info(f"Scraping Page {page_num}...")

                search_url = f"{AppConfig.URL_BASE_AMAZON}/s?k={encoded_term}"
                if page_num > 1:
                    search_url += f"&page={page_num}"

                driver.get(search_url)
                
                try:
                    # Attendre que les produits se chargent
                    WebDriverWait(driver, 15).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, AppConfig.SELECTORS["PRODUCT_BLOCK"]))
                    )
                except Exception:
                    logger.warning(f"No product blocks found on page {page_num}. Ending pagination.")
                    break

                html_content = driver.page_source
                soup = BeautifulSoup(html_content, 'html.parser')
                product_blocks = soup.select(AppConfig.SELECTORS["PRODUCT_BLOCK"])

                if not product_blocks:
                    logger.info(f"Page {page_num} seems empty. Stopping search.")
                    break

                for i, block in enumerate(product_blocks):
                    try:
                        unique_index = (page_num - 1) * 60 + i
                        product_data = self._process_product_block(block, unique_index)
                        if product_data["title"] != "Titre non trouvé":
                            all_results.append(product_data)
                    except Exception as e:
                        logger.error(f"Failed to process product #{i} page {page_num}. Error: {e}")
                        continue

        except Exception as e:
            logger.critical(f"Critical error during scraping: {e}")
            return []
        finally:
            if driver:
                driver.quit()

        logger.info(f"Scraping completed. {len(all_results)} results.")
        return all_results


# ====================================================================
# 4. FLASK CONFIGURATION
# ====================================================================

if getattr(sys, 'frozen', False):
    BASE_DIR = getattr(sys, '_MEIPASS', os.path.abspath("."))
    app = Flask(__name__, 
                template_folder=os.path.join(BASE_DIR, 'templates'),
                static_folder=os.path.join(BASE_DIR, 'static'))
else:
    app = Flask(__name__)

CORS(app)
scraper = AmazonScraper(headless=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    if getattr(sys, 'frozen', False):
        base_dir = getattr(sys, '_MEIPASS', os.path.abspath("."))
        static_dir = os.path.join(base_dir, "static")
    else:
        static_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "static")
    
    return send_from_directory(static_dir, filename)


@app.route('/api/search', methods=['GET'])
def search_api():
    term = request.args.get('query', '').strip()
    pages_param = request.args.get('pages')

    if not term:
        return jsonify({"error": "Missing 'query' parameter"}), 400

    try:
        pages_count = int(pages_param) if pages_param else MAX_PAGES_ALLOWED
        pages_count = min(max(pages_count, 1), MAX_PAGES_ALLOWED)
    except ValueError:
        pages_count = 1

    products = scraper.scrape(term, pages_count)
    valid_products = [p for p in products if p['total_price'] > 0.0 and p['unit_price_kg'] > 0.0]
    return jsonify(valid_products)


# ====================================================================
# 5. EXECUTION
# ====================================================================

if __name__ == '__main__':
    print(f"Serveur Flask sur http://127.0.0.1:{AppConfig.API_PORT}")
    webbrowser.open(f'http://127.0.0.1:{AppConfig.API_PORT}/')
    app.run(host='0.0.0.0', port=AppConfig.API_PORT, debug=False, use_reloader=False)