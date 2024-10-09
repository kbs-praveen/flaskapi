import json
import time
import re
import logging
from selenium.webdriver.common.by import By
from seleniumbase import Driver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
from re import search
from flask import Flask, request, jsonify,Blueprint

# Set up logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

doorbash_bp = Blueprint('doordash', __name__)

restaurant_detail = {}
all_items_details = []
clicked_items = set()
def extract_store_header(storepage_feed):
    return storepage_feed.get('storeHeader', {})


def convert_to_24hr(time_str):
    try:
        # Convert 12-hour format to 24-hour format
        return datetime.strptime(time_str, '%I:%M %p').strftime('%H:%M')
    except ValueError:
        return time_str  # If conversion fails, return original time string


def convert_to_24hr(time_str):
    # Helper function to convert time to 24-hour format
    from datetime import datetime
    try:
        return datetime.strptime(time_str, "%I %p").strftime("%H:%M")
    except ValueError:
        return datetime.strptime(time_str, "%I:%M %p").strftime("%H:%M")

def extract_store_hours(mx_info):
    store_hours_info = mx_info.get('operationInfo', {}).get('storeOperationHourInfo', {}).get('operationSchedule', [])
    store_opening_hours = []
    for day_info in store_hours_info:
        day = day_info.get('dayOfWeek', '').capitalize()
        time_slots = day_info.get('timeSlotList', [])
        for time_slot in time_slots:
            # Split time slots into start and end times
            try:
                start_time, end_time = time_slot.split(' - ')
                start_time = convert_to_24hr(start_time)
                end_time = convert_to_24hr(end_time)
                store_opening_hours.append(f"{day} {start_time}-{end_time}")
            except ValueError:
                store_opening_hours.append(f"{day} {time_slot}")  # If split fails, append original time slot
    return store_opening_hours



def extract_menu_groups(menu_book):
    menu_categories = menu_book.get('menuCategories', [])
    return [category.get('name') for category in menu_categories]

def transform_item_lists(item_lists):
    transformed_categories = []
    for item_list in item_lists:
        category = {
            "title": item_list.get('name', 'Unknown Category'),
            "menu": []
        }
        for item in item_list.get('items', []):
            try:
                price_str = item.get('displayPrice', '$0.00').replace('$', '').replace(',', '')
                price = float(price_str)
            except ValueError:
                print(f"Warning: Unable to convert price '{price_str}' to float.")
                price = 0.0  # Default value or handle as needed

            menu_item = {
                "name": item.get('name', 'Unnamed Item'),
                "description": item.get('description', 'No Description'),
                "imageUrl": item.get('imageUrl', 'No Image URL'),
                "price": price,
                "ingredientsGroups": []  # Add more details if available
            }
            category["menu"].append(menu_item)
        transformed_categories.append(category)

    return transformed_categories




def compile_restaurant_data(store_header, mx_info, store_opening_hours, menu_groups, transformed_categories):
    # Extract the postal code using a regular expression
    display_address = mx_info.get('address', {}).get('displayAddress', '')
    postal_code_match = re.search(r'\b\d{5}\b', display_address)
    postal_code = postal_code_match.group(0) if postal_code_match else ''
    return {
        'data': {
#            "menu_id": store_header.get('id'),
            'menu_id': 18344,
            'titleURL': '',
            'title_id': '',
            'title': store_header.get('name', ''),
            'ImageURL': store_header.get('businessHeaderImgUrl', ''),
            'LogoURL': store_header.get('coverSquareImgUrl', ''),
            'restaurantAddress': {
                '@type': mx_info.get('address', {}).get('__typename', ''),
                'streetAddress': mx_info.get('address', {}).get('street', ''),
                'addressLocality': mx_info.get('address', {}).get('city', ''),
                'addressRegion': mx_info.get('address', {}).get('state', ''),
                'postalCode': postal_code,
                'addressCountry': mx_info.get('address', {}).get('countryShortname', ''),
            },
            'storeOpeningHours': store_opening_hours,
            'priceRange': store_header.get('priceRangeDisplayString', ''),
            'telephone': mx_info.get('phoneno', ''),
            'ratingValue': '',
            'ratingCount': '',
            'latitude': float(store_header.get('address', {}).get('lat', 0.0)),
            'longitude': float(store_header.get('address', {}).get('lng', 0.0)),
            'cuisine': '',
            'menu_groups': menu_groups,
            'categories': transformed_categories
        }
    }


def extract_and_transform_json_data(json_data):
    if not json_data:
        logging.error("No JSON data provided for transformation.")
        return {}

    results = json_data.get('json', {}).get('results', [])
    if not results:
        logging.error("No results found in the provided JSON data.")
        return {}

    for result in results:
        storepage_feed = result.get('result', {}).get('storepageFeed', {})
        if storepage_feed:
            store_header = extract_store_header(storepage_feed)
            mx_info = storepage_feed.get('mxInfo', {})
            store_opening_hours = extract_store_hours(mx_info)
            menu_book = storepage_feed.get('menuBook', {})
            menu_groups = extract_menu_groups(menu_book)
            item_lists = storepage_feed.get('itemLists', {})
            transformed_categories = transform_item_lists(item_lists)

            restaurant = compile_restaurant_data(
                store_header,
                mx_info,
                store_opening_hours,
                menu_groups,
                transformed_categories
            )

            return restaurant


def parse_store_data(driver):
    try:
        script_tag = WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.XPATH, '(//script[contains(text(),"ApolloSSRDataTransport")])[2]'))
        )
        json_text = script_tag.get_attribute('textContent')
    except Exception as e:
        logging.error("Could not find the script tag: %s", e)
        return {}

    try:
        json_start = json_text.find('{')
        json_end = json_text.rfind('}') + 1
        json_str = json_text[json_start:json_end]
        json_data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logging.error("JSON decoding failed: %s", e)
        return {}

    restaurant_detail = extract_and_transform_json_data(json_data)
    return restaurant_detail


def save_json_to_file(data, filename='restaurant_detail.json'):
    with open(filename, 'w') as outfile:
        json.dump(data, outfile, indent=4)


def click_item(driver, item):
    """Click the item and handle the item modal."""
    global all_items_details, clicked_items  # Declare global variables before use
    try:
        WebDriverWait(driver, 60).until(EC.element_to_be_clickable(item))
        item_text = item.text
        if item_text not in clicked_items:
            item.click()
            clicked_items.add(item_text)
            logging.info(f"Item clicked: {item_text}")
            time.sleep(5)  # Wait for item modal to load

            # Wait for the item modal to become visible
            WebDriverWait(driver, 60).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-testid="ItemModal"]'))
            )
            logging.info("Item modal visible")

            # Extract item name
            item_name = driver.find_element(By.XPATH, '//h2[@class="Text-sc-1nm69d8-0 dtvoNG"]/span').text
            logging.info(f"Item name: {item_name}")

            details = []

            # Extract details similar to salad choices
            details_elements = driver.find_elements(By.CSS_SELECTOR, 'div[role="group"]')
            logging.info(f"details_elements: {details_elements}")
            for detail in details_elements:
                detail_name = detail.find_element(By.CSS_SELECTOR, 'h3.Text-sc-1nm69d8-0.hBnZXN').text
                logging.info(f"detail_name: {detail_name}")
                select_spans = detail.find_elements(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.gFJzBa')
                logging.info(f"select_spans: {select_spans}")
                if len(select_spans) > 1:
                    select_value_text = select_spans[1].text.strip()
                    select_value = re.sub(r'[^0-9]', '', select_value_text)
                    if not select_value:
                        select_value = 0
                    else:
                        select_value = int(select_value)  # Convert to integer
                else:
                    select_value = 0

                options = []

                # Check for element type 1 specific structure
                option_elements = detail.find_elements(By.CSS_SELECTOR, 'div.sc-724a33a-8')
                if not option_elements:
                    # Fallback to the original option_elements selector
                    option_elements = detail.find_elements(By.CSS_SELECTOR, 'label')

                logging.info(f"option_elements: {option_elements}")
                for option in option_elements:
                    # For element type 1
                    if 'sc-724a33a-8' in option.get_attribute('class'):
                        option_name = option.find_element(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.ZNLaC').text
                        # Filter out calorie-only elements and extract only price elements
                        price_elements = [elem for elem in
                                          option.find_elements(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.dCneXH')
                                          if '+' in elem.text]  # This will include only price elements
                    else:
                        # For element type 2 and 3
                        option_name = option.find_element(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0').text
                        price_elements = [elem for elem in
                                          option.find_elements(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.dCneXH')
                                          if '+' in elem.text]

                    logging.info(f"option_name: {option_name}")
                    logging.info(f"price_elements: {price_elements}")

                    if price_elements:
                        raw_price = price_elements[0].text
                        # Remove unwanted characters and any additional text
                        raw_price = raw_price.replace('US', '').replace('+', '').replace('$', '').strip()

                        try:
                            # Attempt to convert to float
                            cleaned_price = float(raw_price)
                        except ValueError:
                            # Handle cases where conversion to float fails
                            cleaned_price = 0
                    else:
                        # Handle cases where price_elements was not used or found
                        logging.info(f"No price found for {option_name}. Setting default price.")
                        cleaned_price = 0  # Or you can set a default value like 0 or 0.0

                    # Multiply cleaned price by 2
                    price = cleaned_price * 2

                    # Define possibleToAdd value based on element type
                    possible_to_add = 999999 if 'sc-724a33a-8' in option.get_attribute('class') else 1

                    options.append({
                        'name': option_name,
                        'possibleToAdd': possible_to_add,
                        'price': price,
                        'leftHalfPrice': cleaned_price,
                        'rightHalfPrice': cleaned_price,
                        'ingredientsGroup': []
                    })

                details.append({
                    'type': "general",
                    'name': detail_name,
                    'requiresSelectionMin': 0,
                    'requiresSelectionMax': select_value,
                    'ingredients': options
                })

            # Append the item details to the global list
            item_details = {
                'item_name': item_name,
                'item_details': details
            }
            all_items_details.append(item_details)

            # Close the modal and handle any issues with closing
            close_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label^="Close"]')
            logging.info(f"close_button: {close_button}")

            close_button.click()
            logging.info("Close button clicked")

            # Wait for the modal to close
            WebDriverWait(driver, 60).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, '[data-testid="ItemModal"]'))
            )
            logging.info("Item modal closed")
            time.sleep(5)

            # Update the global menu with the item details
            global restaurant_detail
            if restaurant_detail:
                restaurant_detail = append_item_details_to_menu(restaurant_detail, item_details)
        else:
            logging.info(f"Item already clicked: {item_text}")

    except Exception as e:
        logging.error(f"Error interacting with item: {e}")
        time.sleep(2)



def append_item_details_to_menu(menu, item_details):
    if not item_details:
        return menu

    item_name = item_details.get('item_name')

    if not item_name:
        return menu

    for section in menu['data']['categories']:
        for menu_item in section['menu']:
            if menu_item['name'] == item_name:
                # Only add details if the item does not already have them
                if not menu_item.get('ingredientsGroups'):
                    menu_item['ingredientsGroups'] = item_details['item_details']

    return menu

def is_scrolling(driver, previous_scroll_position):
    current_scroll_position = driver.execute_script("return window.scrollY;")
    return current_scroll_position > previous_scroll_position


def scrape_menu(url, menu_id):
    global restaurant_detail, all_items_details, clicked_items
    driver = Driver(uc=True, undetectable=True, headless=True)
    driver.set_window_size(1024, 1024)  # Example for an iPad in portrait mode

    driver.get(url)
    time.sleep(50)  # Adjust the sleep time based on how long the page takes to load

    # Parse and save restaurant data
    restaurant_detail = parse_store_data(driver)
    restaurant_detail['data']['menu_id'] = menu_id  # Set the menu_id received as input

    # Scroll and fetch items
    driver.execute_script("window.scrollBy(0, 2000);")
    time.sleep(10)

    # Fetch all items initially
    items_xpath = '//div[@data-testid="MenuItem"]'
    items = driver.find_elements(By.XPATH, items_xpath)

    previous_scroll_position = driver.execute_script("return window.scrollY;")
    no_new_items_count = 0
    max_no_new_items_count = 3  # Number of times to not find new items before quitting

    while items:
        for item in items:
            click_item(driver, item)

        # Scroll and check if new items are loaded
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)
        items = driver.find_elements(By.XPATH, items_xpath)

        if not items:
            logging.info("No more items found.")
            break

        # Check if scrolling is still occurring
        if is_scrolling(driver, previous_scroll_position):
            previous_scroll_position = driver.execute_script("return window.scrollY;")
            no_new_items_count = 0
        else:
            no_new_items_count += 1
            if no_new_items_count >= max_no_new_items_count:
                logging.info("No new items found after scrolling multiple times. Quitting.")
                break

    # After processing all items, update the restaurant data
    if restaurant_detail:
        for item_details in all_items_details:
            restaurant_detail = append_item_details_to_menu(restaurant_detail, item_details)

    # Close the browser when done
    driver.quit()

    return restaurant_detail

# Flask API route
@doorbash_bp.route('/doordash_getmenu', methods=['POST'])
def scrape_menu_api():
    try:
        # Get URL and menu_id from the request arguments
        url = request.args.get('url')
        menu_id = request.args.get('menu_id')

        if not url or not menu_id:
            return jsonify({"error": "Please provide both 'url' and 'menu_id'"}), 400

        # Call the scrape function
        restaurant_data = scrape_menu(url, menu_id)

        # Save the restaurant data to a file
        save_json_to_file(restaurant_data, 'restaurant_detail.json')

        return jsonify(restaurant_data), 200

    except Exception as e:
        logging.error(f"Error during scraping: {e}")
        return jsonify({"error": str(e)}), 500


# Register the Blueprint
app.register_blueprint(doorbash_bp)


if __name__ == '__main__':
    app.run(debug=True)