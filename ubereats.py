import json
import time
import re
import logging
from flask import Flask, request, jsonify, Blueprint
from selenium.webdriver.common.by import By
from seleniumbase import Driver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
ubereats_bp = Blueprint('ubereats', __name__)

class UberEatsSpider:
    def __init__(self):
        # Initialize the driver with undetectable mode enabled
        self.driver = Driver(uc=True, undetectable=True, headless=True)
        self.driver.set_window_size(1024, 768)  # Set window size for consistency
        self.data = {}  # Initialize a dictionary to store the data
        self.section_names = set()  # Initialize a set to store unique section names

    def parse(self, url, menu_id):
        # Load the URL using Selenium
        self.driver.get(url)
        # Try reloading the page after initial load to ensure it functions properly
        time.sleep(5)  # Give it a moment to load the initial elements
        self.driver.refresh()  # Manually refresh the page
        self.handle_delivery_popup()

        # Wait for the necessary elements to load
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li[data-testid^="store-item-"]'))
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

            items = self.driver.find_elements(By.CSS_SELECTOR, 'li[data-testid^="store-item-"]')
            logging.info(f"Item name extracted: {items}")

            for item in items:
                try:
                    item.click()
                    logging.info(f"Item name extracted: {item}")
                    self.handle_popup()

                    details = self.extract_item_details()

                    if details:
                        menu_data = self.append_item_details_to_menu(menu_data, details)
                    self.driver.back()
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'li[data-testid^="store-item-"]'))
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
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
            close_button = self.driver.find_element(By.CSS_SELECTOR, 'button[data-testid="close-button"]')
            close_button.click()
            WebDriverWait(self.driver, 10).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
        except Exception as e:
            logging.info(f"Popup not found or already closed: {e}")

    def handle_delivery_popup(self):
        try:
            # Wait for the delivery dialog to become visible
            WebDriverWait(self.driver, 10).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
            # Locate and click the close button for the delivery popup
            close_button = self.driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Close"]')
            close_button.click()
            # Wait for the dialog to become invisible after closing
            WebDriverWait(self.driver, 10).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div[role="dialog"]'))
            )
        except Exception as e:
            logging.info(f"Delivery popup not found or already closed: {e}")

    def extract_item_details(self):
        details = []
        item_name = ''
        image_url = ''
        time.sleep(10)

        # Check if the dialog is present
        try:
            dialog = self.driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"][aria-label="dialog"]')
            logging.info(f"Dialog tag visible: {dialog}")
            if not dialog:
                logging.warning("Dialog not found.")
                return ''
        except Exception as e:
            logging.error(f"Error finding dialog: {e}")
            return ''

        # Extract item name
        try:
            logging.info("Attempting to extract item name.")
            item_name_element = dialog.find_element(By.CSS_SELECTOR, 'h1')
            item_name = item_name_element.text.strip() if item_name_element else ''
            logging.info(f"Item name extracted: {item_name}")
        except Exception as e:
            logging.error(f"Error extracting item name: {e}")

        # Extract image URL
        try:
            logging.info("Attempting to extract image URL.")
            image_element = dialog.find_element(By.CSS_SELECTOR, 'img[role="presentation"]')
            image_url = image_element.get_attribute('src') if image_element else ''
            logging.info(f"Image URL extracted: {image_url}")
        except Exception as e:
            logging.error(f"Error extracting image URL: {e}")

        # Extract "pick many" options
        try:
            logging.info("Attempting to extract 'pick many' options.")
            detail_elements = dialog.find_elements(By.CSS_SELECTOR, 'div[data-testid="customization-pick-many"]')

            for element in detail_elements:
                logging.info("Processing a 'pick many' element.")
                category_names = \
                element.find_elements(By.CSS_SELECTOR, 'div[data-testid="customization-pick-many"] > div > div > div')[
                    0]
                category_name = category_names.find_elements(By.CSS_SELECTOR, 'div')[0].text
                text = element.find_element(By.CSS_SELECTOR,
                                            'div[data-testid="customization-pick-many"] > div > div > div').text
                match = re.search(r'(\d+)', text)
                requires_selection_max = int(match.group(1)) if match else 0
                logging.info(f"Category name: {category_name}, Requires selection max: {requires_selection_max}")

                options = element.find_elements(By.CSS_SELECTOR, 'label')
                option_details = []

                for option in options:
                    logging.info("Processing an option in 'pick many'.")
                    try:
                        name = option.find_elements(By.CSS_SELECTOR, 'label > div > div > div > div > div')[0].text
                        logging.info(f"Option name extracted: {name}")
                    except Exception as e:
                        logging.error(f"Error extracting option name: {e}")
                        name = ''

                    try:
                        price_text = option.find_elements(By.CSS_SELECTOR, 'label > div > div > div > div > div')[
                            2].text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        price = float(price_cleaned) if price_cleaned else 0.0
                        logging.info(f"Option price extracted: {price}")
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        price = 0.0
                    cleaned_price = price * 2

                    option_details.append(
                        {'name': name.strip() if name else '', 'possibleToAdd': 1, 'price': cleaned_price,
                         'leftHalfPrice': price, 'rightHalfPrice': price})

                details.append({
                    'item_name': item_name,
                    'category_name': category_name.strip() if category_name else '',
                    'requiresSelectionMin': 0,
                    'requiresSelectionMax': requires_selection_max,
                    'options': option_details
                })

        except Exception as e:
            logging.error(f"Error extracting details (pick many): {e}")

        # Extract "pick one" options similarly
        try:
            logging.info("Attempting to extract 'pick one' options.")
            pick_one_elements = dialog.find_elements(By.CSS_SELECTOR, 'div[data-testid="customization-pick-one"]')

            for element in pick_one_elements:
                logging.info("Processing a 'pick one' element.")

                category_names = \
                element.find_elements(By.CSS_SELECTOR, 'div[data-testid="customization-pick-one"] > div > div > div')[0]
                category_name = category_names.find_elements(By.CSS_SELECTOR, 'div')[0].text
                text = element.find_element(By.CSS_SELECTOR,
                                            'div[data-testid="customization-pick-one"] > div > div > div').text
                match = re.search(r'(\d+)', text)
                requires_selection_max = int(match.group(1)) if match else 0
                logging.info(f"Category name: {category_name}, Requires selection max: {requires_selection_max}")

                options = element.find_elements(By.CSS_SELECTOR, 'label')
                option_details = []

                for option in options:
                    logging.info("Processing an option in 'pick one'.")
                    try:
                        name = option.find_elements(By.CSS_SELECTOR, 'label > div > div > div > div > div')[0].text
                        logging.info(f"Option name extracted: {name}")
                    except Exception as e:
                        logging.error(f"Error extracting option name: {e}")
                        name = ''

                    try:
                        price_text = option.find_elements(By.CSS_SELECTOR, 'label > div > div > div > div > div')[
                            2].text
                        price_cleaned = re.sub(r'[^\d.]+', '', price_text).strip()
                        price = float(price_cleaned) if price_cleaned else 0.0
                        logging.info(f"Option price extracted: {price}")
                    except Exception as e:
                        logging.error(f"Error extracting option price: {e}")
                        price = 0.0
                    cleaned_price = price * 2

                    option_details.append(
                        {'name': name.strip() if name else '', 'possibleToAdd': 1, 'price': cleaned_price,
                         'leftHalfPrice': price, 'rightHalfPrice': price})

                details.append({
                    'item_name': item_name,
                    'category_name': category_name.strip() if category_name else '',
                    'requiresSelectionMin': 0,
                    'requiresSelectionMax': requires_selection_max,
                    'options': option_details
                })

        except Exception as e:
            logging.error(f"Error extracting details (pick one): {e}")

        if details or item_name:
            logging.info("Item details extraction completed successfully.")
            return {'item_name': item_name, 'image_url': image_url, 'item_details': details}
        else:
            logging.warning("No details were extracted.")
            return ''

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

@ubereats_bp.route('/ubereats_get_menu', methods=['POST'])
def scrape():
    url = request.args.get('url')
    menu_id = request.args.get('menu_id')

    if not url or not menu_id:
        return jsonify({'error': 'URL and menu_id are required'}), 400

    spider = UberEatsSpider()
    try:
        restaurant_data = spider.parse(url, menu_id)
        if restaurant_data:
            spider.save_data_to_file(f"ubereats_menu_{menu_id}.json")
            return jsonify({
                'restaurant_data': restaurant_data
            }), 200
        else:
            return jsonify({'error': 'Failed to scrape the menu data'}), 500
    finally:
        spider.close()


# Register the Blueprint
app.register_blueprint(ubereats_bp)


if __name__ == '__main__':
    app.run(debug=True)