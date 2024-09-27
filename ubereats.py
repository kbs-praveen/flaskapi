import json
import time
import re
import logging
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class UberEatsSpider:
    def __init__(self):
        # Set up the Selenium driver using Chrome
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
        self.driver.set_window_size(1024, 768)  # Adjust screen size as needed
        self.data = {}  # Initialize a dictionary to store the data
        self.section_names = set()  # Initialize a set to store unique section names

    def parse(self, url, menu_id):
        # Load the URL using Selenium
        self.driver.get(url)
        # Try reloading the page after initial load to ensure it functions properly
        time.sleep(5)  # Give it a moment to load the initial elements
        self.driver.refresh()  # Manually refresh the page

        # Wait for the necessary elements to load
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li[data-test^="store-item-"]'))
            )
        except Exception as e:
            logging.error(f"Error loading page elements: {e}")
            return

        # Extract the JSON data from the <script type="application/ld+json"> tag
        try:
            script_tag = self.driver.find_element(By.XPATH, '//script[@type="application/ld+json"]')
            json_data = script_tag.get_attribute('textContent')
            data = json.loads(json_data) if json_data else {}
        except Exception as e:
            logging.error(f"Error extracting JSON data: {e}")
            return

        if data:
            menu_data = self.parse_menu(data.get('hasMenu', {}))  # Parse initial menu structure
            self.section_names.update(section['title'] for section in menu_data)

            items = self.driver.find_elements(By.CSS_SELECTOR, 'li[data-test^="store-item-"]')
            for item in items:
                try:
                    item.click()
                    self.handle_popup()
                    details = self.extract_item_details()
                    if details:
                        menu_data = self.append_item_details_to_menu(menu_data, details)
                    self.driver.back()
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'li[data-test^="store-item-"]'))
                    )
                except Exception as e:
                    logging.error(f"Error occurred while processing item: {e}")
                    continue

            # Yield the final restaurant data with complete menu details
            restaurant = {
                'data': {
                    "menu_id": menu_id,
                    'titleURL': data.get('@id'),
                    'title_id': '',
                    'Context': data.get('@context'),
                    'title': data.get('name'),
                    'images': data.get('image', []),
                    'LogoURL': '',
                    'restaurantAddress': self.extract_address(data.get('address', {})),
                    'storeOpeningHours': self.parse_opening_hours(data.get('openingHoursSpecification', [])),
                    'priceRange': data.get('priceRange'),
                    'telephone': data.get('telephone'),
                    'ratingValue': data.get('aggregateRating', {}).get('ratingValue'),
                    'ratingCount': data.get('aggregateRating', {}).get('reviewCount'),
                    'latitude': data.get('geo', {}).get('latitude'),
                    'longitude': data.get('geo', {}).get('longitude'),
                    'cuisine': data.get('servesCuisine', []),
                    'menu_groups': list(self.section_names),
                    'categories': menu_data
                }
            }
            self.data = restaurant  # Store the data in the dictionary
            return restaurant

    def extract_address(self, address_data):
        return {
            '@type': address_data.get('@type'),
            'streetAddress': address_data.get('streetAddress'),
            'addressLocality': address_data.get('addressLocality'),
            'addressRegion': address_data.get('addressRegion'),
            'postalCode': address_data.get('postalCode'),
            'addressCountry': address_data.get('addressCountry'),
        }

    # ... (Other methods from your UberEatsSpider remain the same)
    def parse_opening_hours(self, hours_data):
        days_of_week = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        hours_dict = {day: None for day in days_of_week}

        def format_time(time_str):
            if not time_str:
                return "00:00"
            time_parts = time_str.split(':')
            return f"{time_parts[0].zfill(2)}:{time_parts[1].zfill(2)}" if len(time_parts) == 2 else time_str

        for hours in hours_data:
            days = hours.get('dayOfWeek', [])
            if not isinstance(days, list):
                days = [days]
            opens = format_time(hours.get('opens', ''))
            closes = format_time(hours.get('closes', ''))
            for day in days:
                if day in hours_dict:
                    hours_dict[day] = f"{opens}-{closes}"

        return [f"{day} {hours_dict[day]}" for day in days_of_week if hours_dict[day] is not None]

    def parse_menu(self, menu_data):
        menu = []
        for section in menu_data.get('hasMenuSection', []):
            section_name = section.get('name')
            items = section.get('hasMenuItem', [])
            menu_items = []

            for item in items:
                offer_data = item.get('offers', {})
                price = offer_data.get('price')
                menu_item = {
                    'type': item.get('@type'),
                    'name': item.get('name'),
                    'description': item.get('description'),
                    'image_url': '',
                    'price': price,
                    'ingredientsGroups': ''
                }
                menu_items.append(menu_item)

            section_data = {
                'title': section_name,
                'menu': menu_items
            }
            menu.append(section_data)

        return menu

    def handle_popup(self):
        try:
            WebDriverWait(self.driver, 5).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
            close_button = self.driver.find_element(By.CSS_SELECTOR, 'button[data-testid="close-button"]')
            close_button.click()
            WebDriverWait(self.driver, 5).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
        except Exception as e:
            logging.info(f"Popup not found or already closed: {e}")

    def extract_item_details(self):
        details = []
        item_name = ''
        image_url = ''

        try:
            item_name_element = self.driver.find_element(By.CSS_SELECTOR, 'h1.ft.fv.fu.fs.al.cg')
            item_name = item_name_element.text.strip() if item_name_element else ''
        except Exception as e:
            logging.error(f"Error extracting item name: {e}")

        try:
            image_element = self.driver.find_element(By.CSS_SELECTOR, 'div.cj.ae.bl.kx img')
            image_url = image_element.get_attribute('src') if image_element else ''
        except Exception as e:
            logging.error(f"Error extracting image URL: {e}")

            # Extract "pick many" options
        try:
            detail_elements = self.driver.find_elements(By.CSS_SELECTOR,
                                                            'div[data-testid="customization-pick-many"]')

            for element in detail_elements:
                category_name = element.find_element(By.CSS_SELECTOR, 'div.fs.hy.fu.hz.g4').text
                text = element.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g4').text
                # Use regular expression to find the number in the text
                match = re.search(r'(\d+)', text)

                # Extract the number if found, otherwise default to 0
                requires_selection_max = int(match.group(1)) if match else 0

                options = element.find_elements(By.CSS_SELECTOR, 'label')
                option_details = []

                for option in options:
                    try:
                        name = option.find_element(By.CSS_SELECTOR, 'div.be.bf.bg.bh.g3.os').text
                    except Exception as e:
                        logging.error(f"Error extracting option name: {e}")
                        name = ''

                    try:
                        price_text = option.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g3.bn').text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        left_half_price = float(
                            price_cleaned) if price_cleaned else 0.0  # Default to 0.0 if price is not found or is empty
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        left_half_price = 0.0  # Default to 0.0 if price is not found

                    try:
                        price_text = option.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g3.bn').text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        right_half_price = float(
                            price_cleaned) if price_cleaned else 0.0  # Default to 0.0 if price is not found or is empty
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        right_half_price = 0.0  # Default to 0.0 if price is not found

                    try:
                        # Calculate price by summing left_half_price and right_half_price
                        price = left_half_price + right_half_price
                    except Exception as e:
                        logging.error(f"Error calculating total price: {e}")
                        price = 0.0  # Default to 0.0 if price calculation fails

                    option_details.append(
                        {'name': name.strip() if name else '', 'possibleToAdd': 1, 'price': price,
                         'leftHalfPrice': left_half_price, 'rightHalfPrice': right_half_price})

                details.append(
                    {'type': "general", 'name': category_name.strip() if category_name else '',
                     'requiresSelectionMin': 0,
                     'requiresSelectionMax': requires_selection_max if requires_selection_max else '',
                     'ingredients': option_details})

        except Exception as e:
            logging.error(f"Error extracting details (pick many): {e}")

            # Extract "pick one" options
        try:
            pick_one_elements = self.driver.find_elements(By.CSS_SELECTOR,
                                                              'div[data-testid="customization-pick-one"]')

            for element in pick_one_elements:
                category_name = element.find_element(By.CSS_SELECTOR, 'div.fs.hy.fu.hz.g4').text
                text = element.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g4').text

                # Use regular expression to find the number in the text
                match = re.search(r'(\d+)', text)

                # Extract the number if found, otherwise default to 0
                requires_selection_max = int(match.group(1)) if match else 0

                options = element.find_elements(By.CSS_SELECTOR, 'label')
                option_details = []

                for option in options:
                    try:
                        name = option.find_element(By.CSS_SELECTOR, 'div.be.bf.bg.bh.g3.os').text
                    except Exception as e:
                        logging.error(f"Error extracting option name: {e}")
                        name = ''

                    try:
                        price_text = option.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g3.bn').text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        left_half_price = float(
                            price_cleaned) if price_cleaned else 0.0  # Default to 0.0 if price is not found or is empty
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        left_half_price = 0.0  # Default to 0.0 if price is not found

                    try:
                        price_text = option.find_element(By.CSS_SELECTOR, 'div.be.bf.g1.dj.g3.bn').text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        right_half_price = float(
                            price_cleaned) if price_cleaned else 0.0  # Default to 0.0 if price is not found or is empty
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        right_half_price = 0.0  # Default to 0.0 if price is not found

                    try:
                        # Calculate price by summing left_half_price and right_half_price
                        price = left_half_price + right_half_price
                    except Exception as e:
                        logging.error(f"Error calculating total price: {e}")
                        price = 0.0  # Default to 0.0 if price calculation fails

                    option_details.append(
                        {'name': name.strip() if name else '', 'possibleToAdd': 1, 'price': price,
                         'leftHalfPrice': left_half_price, 'rightHalfPrice': right_half_price})

                details.append(
                    {'type': "general", 'name': category_name.strip() if category_name else '',
                     'requiresSelectionMin': 0,
                     'requiresSelectionMax': requires_selection_max if requires_selection_max else '',
                     'ingredients': option_details})

        except Exception as e:
            logging.error(f"Error extracting details (pick one): {e}")



        return {'item_name': item_name, 'image_url': image_url, 'item_details': details} if details or item_name else ''

    def append_item_details_to_menu(self, menu, item_details):
        if not item_details:
            return menu

        item_name = item_details.get('item_name')
        image_url = item_details.get('image_url')
        if not item_name:
            return menu

        for section in menu:
            for menu_item in section['menu']:
                if menu_item['name'] == item_name:
                    menu_item['ingredientsGroups'] = item_details['item_details']
                    if image_url:
                        menu_item['image_url'] = image_url
                    return menu

        return menu

    def save_data_to_file(self, filename='ubereats_data.json'):
        with open(filename, 'w') as f:
            json.dump(self.data, f, indent=4)

    def close(self):
        self.driver.quit()


@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    url = data.get('url')
    menu_id = data.get('menu_id')

    if not url or not menu_id:
        return jsonify({'error': 'URL and menu_id are required'}), 400

    spider = UberEatsSpider()
    try:
        restaurant_data = spider.parse(url, menu_id)
        if restaurant_data:
            spider.save_data_to_file(f"ubereats_menu_{menu_id}.json")
            return jsonify({'message': 'Menu data scraped and saved successfully!', 'menu_id': menu_id}), 200
        else:
            return jsonify({'error': 'Failed to scrape the menu data'}), 500
    finally:
        spider.close()


if __name__ == '__main__':
    app.run(debug=True)