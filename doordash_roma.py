import json
import time
import re
import logging
from selenium.webdriver.common.by import By
from seleniumbase import Driver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
from flask import Flask, request, jsonify



# Set up logging to console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

restaurant_detail = {}
all_items_details = []
clicked_items = set()

def extract_store_header(storepage_feed):
    return storepage_feed.get('storeHeader', {})


def convert_to_24hr(time_str):
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
            try:
                start_time, end_time = time_slot.split(' - ')
                start_time = convert_to_24hr(start_time)
                end_time = convert_to_24hr(end_time)
                store_opening_hours.append(f"{day} {start_time}-{end_time}")
            except ValueError:
                store_opening_hours.append(f"{day} {time_slot}")
    return store_opening_hours


def extract_menu_groups(menu_book):
    menu_categories = menu_book.get('menuCategories', [])
    return [category.get('name') for category in menu_categories]


def transform_item_lists(item_lists, item_name):  # Add item_name as an argument
    global all_items_details  # Declare the global list

    transformed_categories = []
    for item_list in item_lists:
        category = {
            "title": item_list.get('name', 'Unknown Category'),
            "menu": []
        }
        for item in item_list.get('items', []):
            # Check if the current item's name matches the provided item_name
            if item.get('name', '').lower() == item_name.lower():
                try:
                    price_str = item.get('displayPrice', '$0.00').replace('$', '').replace(',', '')
                    price = float(price_str)
                except ValueError:
                    print(f"Warning: Unable to convert price '{price_str}' to float.")
                    price = 0.0

                menu_item = {
                    "name": item.get('name', 'Unnamed Item'),
                    "description": item.get('description', 'No Description'),
                    "imageUrl": item.get('imageUrl', 'No Image URL'),
                    "price": price,
                    "ingredientsGroups": all_items_details  # Append global list here
                }
                category["menu"].append(menu_item)

        # Append the category only if it has menu items
        if category["menu"]:
            transformed_categories.append(category)

    return transformed_categories



def compile_restaurant_data(store_header, mx_info, store_opening_hours, menu_groups, transformed_categories):
    display_address = mx_info.get('address', {}).get('displayAddress', '')
    postal_code_match = re.search(r'\b\d{5}\b', display_address)
    postal_code = postal_code_match.group(0) if postal_code_match else ''
    return {
        'data': {
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


# Update the call to extract_and_transform_json_data in parse_store_data to include item_name
def parse_store_data(driver, item_name):
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

    restaurant_detail = extract_and_transform_json_data(json_data, item_name)  # Pass item_name
    return restaurant_detail


def save_json_to_file(data, filename='restaurant_detail.json'):
    with open(filename, 'w') as outfile:
        json.dump(data, outfile, indent=4)


def select_items_from_modal(driver, selected_items):
    global all_items_details  # Initialize the list to hold all item details

    try:
        details = []
        ingredients_group = {}  # Use a dict to group ingredients under each detail_name

        protein_additions_selector = '[role="group"][aria-labelledby="optionList_Protein Additions"]'
        recommended_desserts_selector = '[role="group"][aria-labelledby="optionList_Recommended Desserts"]'

        # Wait for the protein additions section
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, protein_additions_selector))
        )
        time.sleep(5)

        # Process Protein Additions
        detail_name = driver.find_element(By.CSS_SELECTOR, f'{protein_additions_selector} h3').text
        select_spans = driver.find_elements(By.CSS_SELECTOR,
                                            f'{protein_additions_selector} span.Text-sc-1nm69d8-0.gFJzBa')
        select_value = 0 if len(select_spans) < 2 else int(re.sub(r'[^0-9]', '', select_spans[1].text.strip()))

        if detail_name not in ingredients_group:
            ingredients_group[detail_name] = {
                'type': "general",
                'name': detail_name,
                'requiresSelectionMin': 0,
                'requiresSelectionMax': select_value,
                'ingredients': []
            }

        protein_options = driver.find_elements(By.CSS_SELECTOR,
                                               f'{protein_additions_selector} .styles__ToggleContainer-sc-t8krd2-0')
        for option in protein_options:
            checkbox = option.find_element(By.CSS_SELECTOR, 'input[type="checkbox"]')
            option_label = option.find_element(By.CSS_SELECTOR, '.Text-sc-1nm69d8-0.ZNLaC').text
            price_elements = [elem for elem in option.find_elements(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.dCneXH') if
                              '+' in elem.text]

            cleaned_price = 0 if not price_elements else float(
                price_elements[0].text.replace('US', '').replace('+', '').replace('$', '').strip())
            price = cleaned_price * 2

            if option_label in selected_items:
                item_details = {
                    'name': option_label,
                    'possibleToAdd': 1,
                    'price': price,
                    'leftHalfPrice': cleaned_price,
                    'rightHalfPrice': cleaned_price
                }
                ingredients_group[detail_name]['ingredients'].append(item_details)

                if option.is_enabled() and not checkbox.is_selected():
                    checkbox.click()
                    time.sleep(5)

        # Process Recommended Desserts
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, recommended_desserts_selector))
        )
        time.sleep(5)

        detail_name = driver.find_element(By.CSS_SELECTOR, f'{recommended_desserts_selector} h3').text
        select_spans = driver.find_elements(By.CSS_SELECTOR,
                                            f'{recommended_desserts_selector} span.Text-sc-1nm69d8-0.gFJzBa')
        select_value = 0 if len(select_spans) < 2 else int(re.sub(r'[^0-9]', '', select_spans[1].text.strip()))

        if detail_name not in ingredients_group:
            ingredients_group[detail_name] = {
                'type': "general",
                'name': detail_name,
                'requiresSelectionMin': 0,
                'requiresSelectionMax': select_value,
                'ingredients': []
            }

        dessert_options = driver.find_elements(By.CSS_SELECTOR,
                                               f'{recommended_desserts_selector} .styles__ToggleContainer-sc-t8krd2-0')
        for option in dessert_options:
            checkbox = option.find_element(By.CSS_SELECTOR, 'input[type="checkbox"]')
            option_label = option.find_element(By.CSS_SELECTOR, '.Text-sc-1nm69d8-0.ZNLaC').text
            price_elements = [elem for elem in option.find_elements(By.CSS_SELECTOR, 'span.Text-sc-1nm69d8-0.dCneXH') if
                              '+' in elem.text]

            cleaned_price = 0 if not price_elements else float(
                price_elements[0].text.replace('US', '').replace('+', '').replace('$', '').strip())
            price = cleaned_price * 2

            if option_label in selected_items:
                item_details = {
                    'name': option_label,
                    'possibleToAdd': 1,
                    'price': price,
                    'leftHalfPrice': cleaned_price,
                    'rightHalfPrice': cleaned_price
                }
                ingredients_group[detail_name]['ingredients'].append(item_details)

                if option.is_enabled() and not checkbox.is_selected():
                    checkbox.click()
                    time.sleep(5)

        # Append all grouped ingredients to details
        details.append(list(ingredients_group.values()))
        all_items_details.append(details)

    except Exception as e:
        logging.error(f"Error selecting items from modal: {e}")

    return all_items_details



def click_item(driver, item, selected_items):
    try:
        # Scroll down by a static amount of 400 pixels
        driver.execute_script("window.scrollBy(0, 400);")
        time.sleep(0.5)  # Optional wait for scrolling

        # Wait for the item to be clickable and click it
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable(item))
        item.click()
        logging.info(f"Clicked on item: {item.text}")

        # Wait for the modal to appear
        WebDriverWait(driver, 30).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, '[data-testid="ItemModal"]'))
        )
        logging.info("Item modal is visible.")

        # Wait for modal contents to load
        time.sleep(5)

        # Select items in the modal (element 1 and element 2)
        select_items_from_modal(driver, selected_items)

        # Click the "Add to Cart" button
        add_to_cart_button = driver.find_element(By.CSS_SELECTOR, '[data-testid="AddToCartButton"]')
        add_to_cart_button.click()
        time.sleep(5)
        logging.info("Item added to cart.")

        # Wait for the modal's close button to become clickable
        close_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Close Enter your delivery address"]')
        WebDriverWait(driver, 30).until(EC.element_to_be_clickable(close_button))

        # Click the close button to close the modal
        close_button.click()
        logging.info("Modal closed successfully.")

        # Wait for a short period to allow modal closure to complete
        time.sleep(5)

    except Exception as e:
        logging.error(f"Error interacting with the item: {e}")


def extract_and_transform_json_data(json_data, item_name):  # Pass item_name to this function
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

            # Update the call to transform_item_lists to include item_name
            transformed_categories = transform_item_lists(item_lists, item_name)

            restaurant = compile_restaurant_data(
                store_header,
                mx_info,
                store_opening_hours,
                menu_groups,
                transformed_categories
            )

            return restaurant

def open_browser_and_scrape_menu(url, item_name, selected_items, menu_id):
    driver = Driver(uc=True, undetectable=True, headless=True)

#    driver.set_window_size(1024, 1024)  # Set the window size for an iPad in portrait mode
    logging.info(f"Opening URL: {url}")
    driver.get(url)
    # Save screenshot after loading the page
    screenshot_path = 'screenshot.png'  # Define the file name for the screenshot
    driver.save_screenshot(screenshot_path)
    logging.info(f"Screenshot saved at: {screenshot_path}")

    previous_scroll_position = 0
    no_new_items_count = 0
    max_no_new_items_count = 5

    try:
        # Give time for page to load
        time.sleep(50)

        # Parse and save restaurant data
        restaurant_detail = parse_store_data(driver, item_name)  # Pass item_name here
        restaurant_detail['data']['menu_id'] = menu_id

        # Searching for the desired items by scrolling
        while True:
            time.sleep(5)  # Longer wait time for content to load

            # Update the XPath to look for div with aria-label containing the item name
            items = driver.find_elements(By.XPATH, f'//div[contains(@aria-label, "{item_name}")]')
            logging.info(f"Found {len(items)} items on the page.")

            for item in items:
                item_text = item.get_attribute("aria-label")
                logging.info(f"Checking item: {item_text}")

                if item_name.lower() in item_text.lower():
                    logging.info(f"Item found: {item_text}")
                    click_item(driver, item, selected_items)
                    return restaurant_detail  # Exit after clicking the item and return data

            # Scroll down if no item was found
            logging.info("No desired item found, scrolling down.")
            current_scroll_position = driver.execute_script("return window.scrollY;")
            logging.info(f"Current scroll position before scrolling: {current_scroll_position}")

            # Scroll to a calculated position closer to the item
            target_scroll_position = current_scroll_position + 100  # Adjust as necessary
            driver.execute_script("window.scrollTo(0, arguments[0]);", target_scroll_position)

            # Optional: Wait for new items to load
            time.sleep(2)

            new_scroll_position = driver.execute_script("return window.scrollY;")
            logging.info(f"Scrolled down. New scroll position: {new_scroll_position}")

            # Check for stopping condition
            if new_scroll_position == previous_scroll_position:
                no_new_items_count += 1  # Increment if no items found
                if no_new_items_count >= max_no_new_items_count:
                    logging.info("Reached max scroll attempts without finding the item. Exiting.")
                    break
            else:
                no_new_items_count = 0  # Reset count if new items are loaded

            previous_scroll_position = new_scroll_position  # Update the previous position

    except Exception as e:
        logging.error(f"Error during scraping: {e}")
    finally:
        driver.quit()

    return restaurant_detail  # Return restaurant data after scraping

# Flask API route
@app.route('/scrape-menu', methods=['POST'])
def scrape_menu_api():
    try:
        # Get URL, menu_id, item_name, and selected_items from the request
        data = request.json
        url = data.get('url')
        menu_id = data.get('menu_id')
        item_name = data.get('item_name', '')  # Extract 'item_name' or use a default value
        selected_items = data.get('selected_items', [])

        if not url or not menu_id:
            return jsonify({"error": "Please provide 'url', 'menu_id', and 'item_name'"}), 400

        # Call the scrape function with the correct arguments
        restaurant_data = open_browser_and_scrape_menu(url, item_name, selected_items, menu_id)

        # Save the restaurant data to a file
        save_json_to_file(restaurant_data, 'restaurant_detail.json')

        return jsonify(restaurant_data), 200

    except Exception as e:
        logging.error(f"Error during scraping: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
