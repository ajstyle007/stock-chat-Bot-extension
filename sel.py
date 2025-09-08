from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import logging
import base64, os, datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CHROMEDRIVER_PATH = r"C:\Users\kumar\Downloads\chromedriver-win64\chromedriver-win64\chromedriver.exe"

def get_driver(headless: bool = True):
    try:
        opts = Options()
        
        if headless:
            # Run in headless mode (good for scraping)
            opts.add_argument("--headless=new")   # modern headless
        else:
            # Non-headless for chart display
            logger.info("Launching Chrome in visible mode")

        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        )

        driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=opts)

        driver.get("https://www.tradingview.com/")
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        logger.info("Navigated to TradingView home")
        return driver

    except Exception as e:
        logger.error(f"Failed to initialize driver: {str(e)}")
        raise


def scrape_stocks(
    driver,
    row_selector="table tbody tr",
    ticker_selector="a[href*='/symbols/']",
    price_selector="td:nth-child(3)",
    change_percent_selector="td:nth-child(2)",
    volume_selector="td:nth-child(4)",
    max_stocks: int = 100
):
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, row_selector))
        )
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ticker_selector))
        )

        rows = driver.find_elements(By.CSS_SELECTOR, row_selector)[:max_stocks]
        if not rows:
            logger.error(f"No rows found with selector {row_selector}")
            logger.error("Page source snippet:\n" + driver.page_source[:2000])
            return []

        stocks = []
        for i, row in enumerate(rows):
            try:
                ticker = row.find_element(By.CSS_SELECTOR, ticker_selector).text.strip()
                price = row.find_element(By.CSS_SELECTOR, price_selector).text.strip()
                change_percent = row.find_element(By.CSS_SELECTOR, change_percent_selector).text.strip()
                volume = row.find_element(By.CSS_SELECTOR, volume_selector).text.strip()

                logger.debug(
                    f"Row {i+1}: ticker={ticker}, price={price}, change_percent={change_percent}"
                )

                stocks.append({
                    "ticker": ticker,
                    "price": price,
                    "change_percent": change_percent,
                    "volume" : volume
                })

            except Exception as e:
                logger.warning(f"Error scraping row {i+1}: {str(e)}")
                continue

        if not stocks:
            logger.warning("No stock data parsed from rows")

        return stocks

    except TimeoutException as e:
        logger.error(f"Timeout waiting for stock elements: {str(e)}")
        logger.error("Page source snippet:\n" + driver.page_source[:2000])
        return []

    except Exception as e:
        logger.error(f"Scraping error: {str(e)}")
        return []
    

def scrape_single_stock(driver, symbol_selector, price_selector):
    try:
        wait = WebDriverWait(driver, 30)

        # --- Symbol ---
        symbol_elem = wait.until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, symbol_selector))
        )
        symbol = symbol_elem.text.strip()

        # --- Price (with fallbacks) ---
        possible_price_selectors = [
            price_selector,
            "span[data-test='instrument-price-last']",
            "div[data-test='instrument-price-last']",
            "span[class*='last']",
        ]



        price = None
        for sel in possible_price_selectors:
            try:
                elem = wait.until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
                )
                # wait until text is non-empty
                wait.until(lambda d: elem.text.strip() != "")
                price = elem.text.strip()
                price = f"{price} USD"
                if price:
                    break
            except Exception:
                continue

        if not price:
            raise TimeoutException("Price element not found with any selector")
        

        # --- Performance (timeframes) ---
        performance = {}
        try:
            perf_elems = driver.find_elements(By.CSS_SELECTOR, "span.content-o1CQs_Mg")
            for elem in perf_elems:
                try:
                    parts = elem.find_elements(By.TAG_NAME, "span")
                    if len(parts) == 2:
                        label = parts[0].text.strip()
                        value = parts[1].text.strip()
                        if label and value:
                            performance[label] = value
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Could not extract performance data: {str(e)}")


        
        # --- Key Stats (HTML block) ---
        stats = {}
        try:
            # saare labels aur values ek sath nikal lo
            labels = driver.find_elements(By.CSS_SELECTOR, "div.label-QCJM7wcY")
            values = driver.find_elements(By.CSS_SELECTOR, "div.value-QCJM7wcY")

            for label, value in zip(labels, values):
                key = label.text.strip()
                val = value.text.strip()
                stats[key] = val

        except Exception as e:
            logger.warning(f"Could not extract key stats properly: {str(e)}")


        chart_image_path = None
        chart_base64 = None

        try:
            # Wait for the chart canvas to be visible (adjust selector as needed)
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "canvas.chart-canvas"))  # Specific class
            )
            canvases = driver.find_elements(By.CSS_SELECTOR, "canvas.chart-canvas")
            
            if canvases:
                chart_elem = canvases[0]  # Use first matching canvas or adjust logic
                # Optionally resize browser window to ensure chart visibility
                driver.set_window_size(800, 600)  # Adjust size as needed
                
                # Save screenshot to temporary file
                chart_image_path = f"./{symbol}_chart.png"
                chart_elem.screenshot(chart_image_path)

                # Convert to base64
                with open(chart_image_path, "rb") as img_file:
                    chart_base64 = base64.b64encode(img_file.read()).decode("utf-8")
                
                # Basic validation of base64 (check if it starts with PNG header)
                if chart_base64.startswith("iVBORw0KGgo"):
                    logger.info(f"Chart screenshot saved at {chart_image_path} and converted to base64")
                else:
                    logger.warning("Invalid chart image captured")
                    chart_base64 = None

                # Clean up temporary file
                try:
                    os.remove(chart_image_path)
                    logger.info(f"Temporary file {chart_image_path} deleted")
                except OSError as e:
                    logger.warning(f"Could not delete temporary file {chart_image_path}: {str(e)}")

            else:
                logger.warning("No canvas elements found for chart")
        except TimeoutException:
            logger.warning("Timeout waiting for chart canvas to load")

        return {
            "symbol": symbol,
            "price": price,
            "performance": performance,
            "key_stats_html": stats,
            "chart_image": chart_image_path,
            "chart_image_base64": chart_base64  
        }


    except TimeoutException as e:
        logger.error(f"Timeout waiting for stock details: {str(e)}")
        # print snippet of DOM for debugging
        logger.debug(driver.page_source[:1000])
        return {}
    except Exception as e:
        logger.error(f"Error scraping single stock: {str(e)}")
        return {}


def scrape_stock_news(driver, url, stock_ticker, max_news=5, days_limit=7):

    driver.get(url)
    
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[data-qa-id='news-headline-title']"))
        )
    except TimeoutException:
        return []

    news_items = []
    news_divs = driver.find_elements(By.CSS_SELECTOR, "div[data-qa-id='news-headline-title']")

    for div in news_divs[:max_news]:
        try:
            title = div.get_attribute("data-overflow-tooltip-text").strip()
        except:
            title = div.text.strip()

        # Get link
        try:
            link_elem = div.find_element(By.TAG_NAME, "a")
            link = link_elem.get_attribute("href").strip()
        except:
            link = None

        # Get date
        try:
            date_elem = div.find_element(By.XPATH, ".//following-sibling::span")
            date_text = date_elem.text.strip()
            news_time = None
            try:
                news_date = datetime.datetime.strptime(date_text, "%b %d, %Y")
                # Filter by last `days_limit` days
                if news_date < datetime.datetime.now() - datetime.timedelta(days=days_limit):
                    continue
                news_time = news_date.strftime("%Y-%m-%d %H:%M:%S")
            except:
                news_time = date_text
        except:
            news_time = None

        news_items.append({
            "title": title,
            "link": link,
            "time": news_time
        })

    return news_items

def scrape_sector(target_sector: str, driver, count: int | str | None = None):
    # Normalize sector name for URL (e.g., "Producer Manufacturing" -> "producer-manufacturing")
    sector_url_slug = target_sector.lower().replace(" ", "-")
    url = f"https://in.tradingview.com/markets/stocks-usa/sectorandindustry-sector/{sector_url_slug}/"
    logger.info(f"Navigating to URL: {url}")
    driver.get(url)

    # Verify the loaded URL
    current_url = driver.current_url
    logger.info(f"Current URL after navigation: {current_url}")
    if sector_url_slug not in current_url:
        logger.error(f"Failed to navigate to correct sector page. Expected: {url}, Got: {current_url}")
        return []

    wait = WebDriverWait(driver, 20)

    try:
        # Wait for potential Cloudflare anti-bot check
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
        logger.info("Waited for potential anti-bot checks")

        # Wait for the table and at least one row
        table_selector = "table.tv-data-table"
        try:
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f"{table_selector} tbody tr.listRow"))
            )
            logger.info(f"Found table with selector: {table_selector}")
        except TimeoutException:
            table_selector = "table"
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, f"{table_selector} tbody tr"))
            )
            logger.info(f"Fell back to generic table selector: {table_selector}")

        prev_count = 0
        for i in range(5):  # max 10 scrolls
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # small wait
            rows = driver.find_elements(By.CSS_SELECTOR, f"{table_selector} tbody tr")

            # ✅ Stop early if enough rows are loaded
            if count and str(count).lower() != "all":
                try:
                    limit = int(count)
                    if len(rows) >= limit:
                        logger.info(f"Reached requested {limit} rows, stopping scroll")
                        break
                except ValueError:
                    logger.warning(f"Invalid count '{count}', continuing full scrape")

            # Stop if no new rows are loaded
            if len(rows) == prev_count:
                break
            prev_count = len(rows)

        # Scroll back up
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # Collect rows
        rows = wait.until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, f"{table_selector} tbody tr.listRow"))
        )
        logger.info(f"Found {len(rows)} rows before limiting")

        # Apply count limit
        if count and str(count).lower() != "all":
            try:
                limit = int(count)
                rows = rows[:limit]
                logger.info(f"Limiting to {limit} rows")
            except ValueError:
                logger.warning(f"Invalid count '{count}', defaulting to all rows")

        # Scrape headers
        headers = [h.text.strip() for h in driver.find_elements(By.CSS_SELECTOR, f"{table_selector} thead tr th")]
        if not headers:
            logger.error("No table headers found")
            return []

        expected_columns = 11
        headers = headers[:expected_columns]
        logger.info(f"Table headers: {headers}")

        # Scrape row data
        all_data = []
        for row in rows:
            cols = row.find_elements(By.TAG_NAME, "td")
            if not cols:
                continue

            num_cols = min(len(cols), expected_columns)
            record = {headers[j]: cols[j].text.strip() for j in range(num_cols)}
            record["Sector"] = target_sector

            if not all_data:  # log only first row for debug
                logger.info(f"Sample row data: {record}")

            all_data.append(record)

        if not all_data:
            logger.warning(f"No data scraped for sector '{target_sector}'")

        return all_data

    except TimeoutException as e:
        logger.error(f"Timeout in scrape_sector: {e}")
        return []
    except Exception as e:
        logger.error(f"Error in scrape_sector: {e}")
        return []


# def display_stock_chart(driver, ticker: str, timeframe: str):
#     try:
#         driver = get_driver()
#         wait = WebDriverWait(driver, 20)

#         # Step 1: Open TradingView
#         driver.get("https://www.tradingview.com/")
#         logger.info("Navigated to TradingView home")

#         # Step 2: Click search button
#         search_btn = wait.until(
#             EC.element_to_be_clickable((By.CSS_SELECTOR, "button.js-header-search-button"))
#         )
#         search_btn.click()
#         logger.info("Opened search box")

#         # Step 3: Type ticker
#         search_box = wait.until(
#             EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='query']"))
#         )
#         search_box.click()
#         search_box.clear()
#         search_box.send_keys(ticker)
#         time.sleep(2)
#         logger.info(f"Typed {ticker}")

#         # Step 4: Click first result
#         first_result = wait.until(
#             EC.element_to_be_clickable((By.CSS_SELECTOR, "div[data-name='list-item-title']"))
#         )
#         first_result.click()
#         logger.info(f"Selected first result for {ticker}")

#         # Step 5: Switch tab if chart opens in new one
#         time.sleep(3)
#         if len(driver.window_handles) > 1:
#             driver.switch_to.window(driver.window_handles[-1])
#             logger.info("Switched to new tab for chart")

#         # Step 6: Wait for chart to load
#         wait.until(
#             EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-name='chart-content']"))
#         )
#         logger.info(f"{ticker} chart loaded")

#         # Step 7: Map timeframes
#         time_map = {
#             "1D": "date-range-tab-1D",
#             "1W": "date-range-tab-1W",
#             "1M": "date-range-tab-1M",
#             "6M": "date-range-tab-6M",
#             "1Y": "date-range-tab-12M",
#             "5Y": "date-range-tab-60M",
#         }
#         if timeframe not in time_map:
#             timeframe = "1Y"

#         # Step 8: Click timeframe button
#         button_xpath = f"//button[@data-name='{time_map[timeframe]}']"
#         time_button = wait.until(
#             EC.element_to_be_clickable((By.XPATH, button_xpath))
#         )

#         chart_canvas = wait.until(
#             EC.presence_of_element_located((By.TAG_NAME, "canvas"))
#         )
#         before_size = chart_canvas.size

#         driver.execute_script("arguments[0].click();", time_button)
#         logger.info(f"Clicked {timeframe} button")

#         # Step 9: Verify chart update
#         for i in range(20):
#             time.sleep(0.5)
#             after_size = chart_canvas.size
#             if after_size != before_size:
#                 logger.info(f"✅ Chart updated to {timeframe} view")
#                 break
#         else:
#             logger.warning(f"⚠️ {timeframe} button clicked, but chart did not visibly update")
        
#         return {
#             "status": "success",
#             "message": f"Displaying {ticker} chart for {timeframe}. Close the browser manually."
#         }

#     except Exception as e:
#         logger.error(f"Error displaying chart for {ticker} ({timeframe}): {e}")
#         return {
#             "status": "error",
#             "message": f"Error displaying chart for {ticker} ({timeframe}): {e}"
#         }


def display_stock_chart(ticker: str, timeframe: str = "12M", headless: bool = False):
    try:
        # Set up Chrome options
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")

        # Initialize WebDriver (replace with your ChromeDriver path)
          # Update this
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER_PATH), options=chrome_options)
        wait = WebDriverWait(driver, 20)

        # Step 1: Open TradingView
        driver.get("https://www.tradingview.com/")
        logger.info("Opened TradingView")

        # Step 2: Open search
        try:
            search_btn = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button.js-header-search-button"))
            )
            search_btn.click()
            logger.info("Opened search box")
        except Exception as e:
            logger.error(f"Could not click search button: {e}")
            driver.quit()
            return {"status": "error", "message": f"Could not click search button: {e}"}

        # Step 3: Type ticker
        try:
            search_box = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='query']"))
            )
            search_box.click()
            search_box.clear()
            search_box.send_keys(ticker)
            time.sleep(2)  # Allow dropdown to load
            logger.info(f"Typed {ticker}")
        except Exception as e:
            logger.error(f"Could not type ticker {ticker}: {e}")
            driver.quit()
            return {"status": "error", "message": f"Could not type ticker: {e}"}

        # Step 4: Select first result
        try:
            first_result = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "div[data-name='list-item-title']"))
            )
            first_result.click()
            logger.info(f"Selected first result for {ticker}")
        except Exception as e:
            logger.error(f"Could not select first result for {ticker}: {e}")
            driver.quit()
            return {"status": "error", "message": f"Could not select ticker: {e}"}

        # Step 5: Switch to new tab if opened
        time.sleep(1)
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            logger.info("Switched to new tab for chart")

        # Step 6: Check for iframe and switch if present
        try:
            iframe = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[src*='chart']"))
            )
            driver.switch_to.frame(iframe)
            logger.info("Switched into chart iframe")
        except:
            logger.info("No iframe found, proceeding with direct chart view")

        # Step 7: Wait for chart to load
        try:
            wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-name='chart-content']"))
            )
            logger.info(f"{ticker} chart loaded")
        except Exception as e:
            logger.warning(f"Chart did not load, but proceeding anyway: {e}")

        # Step 8: Ensure toolbar is ready
        try:
            wait.until(
                EC.presence_of_element_located((By.XPATH, "//div[@data-name='date-ranges-tabs']"))
            )
            logger.info("Chart toolbar loaded")
        except Exception as e:
            logger.warning(f"Chart toolbar not found, but proceeding: {e}")

        # Step 9: Click timeframe button
        try:
            # Map timeframe to correct button attribute
            timeframe_button_map = {
                "12M": "date-range-tab-12M",
                "1D": "date-range-tab-1D",
                "5D": "date-range-tab-5D",
                "1M": "date-range-tab-1M",
                "3M": "date-range-tab-3M",
                "6M": "date-range-tab-6M",
                "YTD": "date-range-tab-YTD",
                "5Y": "date-range-tab-60M",
                "ALL": "date-range-tab-ALL"
            }
            tf = timeframe_button_map.get(timeframe.upper(), "date-range-tab-12M")  # Default to 12M
            button_xpath = f"//button[@data-name='{tf}']"
            time_button = wait.until(
                EC.element_to_be_clickable((By.XPATH, button_xpath))
            )
            chart_canvas = wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "canvas"))
            )
            before_size = chart_canvas.size

            driver.execute_script("arguments[0].click();", time_button)
            logger.info(f"Clicked {timeframe} button")

            # Verify chart update
            for i in range(20):
                time.sleep(0.5)
                after_size = chart_canvas.size
                if after_size != before_size:
                    logger.info(f"✅ Chart updated to {timeframe} view")
                    break
            else:
                logger.warning(f"⚠️ {timeframe} button clicked, but chart did not visibly update")

        except Exception as e:
            logger.error(f"Could not set chart to {timeframe} view: {e}")
            driver.quit()
            return {"status": "error", "message": f"Could not set timeframe: {e}"}

        return {
            "status": "success",
            "message": f"Displaying {ticker} chart for {timeframe}. Close the browser manually."
        }

    except Exception as e:
        logger.error(f"Unexpected error displaying chart for {ticker} ({timeframe}): {e}")
        return {
            "status": "error",
            "message": f"Unexpected error: {e}"
        }
    finally:
        # Keep browser open for manual inspection
        pass
        
def click_element(driver, selector: str):
    try:
        elem = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
        )
        driver.execute_script("arguments[0].click();", elem)
        return {"status": "success", "action": "click", "selector": selector}
    except Exception as e:
        logger.error(f"Click error: {str(e)}")
        return {"status": "error", "message": f"Failed to click element: {str(e)}"}
