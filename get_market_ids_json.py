# Save as poly_get_condition_ids_v2.py (Corrected Syntax Error)
import sys
import re
import playwright
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import json
from typing import List, Dict, Any, Optional

# --- Helper Function to get Market Data from Event Page ---
def get_market_data_from_page(page) -> Optional[List[Dict[str, Any]]]:
    """Extracts the market data array from the __NEXT_DATA__ script tag."""
    # print("Extracting __NEXT_DATA__...", file=sys.stderr) # Status to stderr
    try:
        next_data_script = page.locator("script#__NEXT_DATA__").first
        json_text = next_data_script.inner_text(timeout=15000)
        json_data = json.loads(json_text)
        markets_data = None
        query_state = json_data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}).get("queries", [])
        if query_state and isinstance(query_state, list) and len(query_state) > 0:
            event_query_state = None
            for query in query_state:
                query_key = query.get("queryKey", [""])[0]
                if query_key in ["/api/event/slug", "/api/market"]:
                    event_query_state = query.get("state", {})
                    break
            if event_query_state:
                 # --- CORRECTED LINE ---
                 data_container = event_query_state.get("data", {}) # Added closing parenthesis and bracket
                 # --- END CORRECTION ---
                 if isinstance(data_container, dict):
                     markets_data = data_container.get("markets")
                     if not markets_data and "conditionId" in data_container:
                         markets_data = [data_container]
                 elif isinstance(data_container, list):
                     markets_data = data_container
        if not markets_data or not isinstance(markets_data, list):
             print("WARN: Could not find 'markets' list/data in __NEXT_DATA__.", file=sys.stderr)
             return None
        # print(f"Successfully extracted data for {len(markets_data)} market(s).", file=sys.stderr) # Status to stderr
        return markets_data
    except Exception as e:
        print(f"ERROR extracting or parsing market data from __NEXT_DATA__: {e}", file=sys.stderr)
        return None

# --- Main Extraction Function ---
def extract_market_info_with_odds(url: str) -> Optional[List[Dict[str, Any]]]:
    """
    Navigates to a Polymarket page and extracts the index, title,
    conditionId, and current Yes/No odds for each market found.

    Args:
        url: The full URL of the Polymarket EVENT or MARKET page.

    Returns:
        A list of dictionaries or None on failure.
    """
    market_info_list = []
    p_context = None
    browser = None

    # print(f"--- Attempting to extract market info from: {url} ---", file=sys.stderr)
    launch_options = {"headless": True}

    try:
        p_context = sync_playwright().start()
        browser = p_context.chromium.launch(**launch_options)
        page = browser.new_page()
        page.set_default_navigation_timeout(60000)
        page.set_default_timeout(30000)

        # print(f"Navigating to {url} to extract initial data...", file=sys.stderr)
        page.goto(url, wait_until='domcontentloaded')
        markets_list = get_market_data_from_page(page)
        browser.close()
        p_context.stop()

        if not markets_list:
            print("ERROR: Failed to extract market list from page.", file=sys.stderr)
            return None

        # Extract title, ID, and prices from each market
        for index, market in enumerate(markets_list):
            condition_id = market.get("conditionId")
            title = market.get("groupItemTitle") or market.get("question", f"Market {index}")
            outcome_prices = market.get("outcomePrices") # Get the prices array
            yes_price_str = "N/A"
            no_price_str = "N/A"

            # Format prices if available
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                try:
                    yes_price_str = f"{float(outcome_prices[0])*100:.1f}%"
                except (ValueError, TypeError, IndexError):
                    yes_price_str = f"Error({outcome_prices[0]})" # Handle non-numeric or missing price
                try:
                    no_price_str = f"{float(outcome_prices[1])*100:.1f}%"
                except (ValueError, TypeError, IndexError):
                    no_price_str = f"Error({outcome_prices[1]})"

            if condition_id and title:
                market_info_list.append({
                    "index": index,
                    "title": title.strip(),
                    "conditionId": condition_id,
                    "yes_odds_%": yes_price_str, # Add yes odds
                    "no_odds_%": no_price_str    # Add no odds
                })
            else:
                print(f"WARN: Missing conditionId or title for market data at index {index}.", file=sys.stderr)

        if not market_info_list:
            print("ERROR: No valid market info could be extracted.", file=sys.stderr)
            return None

        return market_info_list

    except Exception as e:
        print(f"ERROR during Playwright operation or data extraction: {e}", file=sys.stderr)
        if p_context and 'browser' in locals() and browser and browser.is_connected():
             browser.close()
        if p_context:
             p_context.stop()
        return None

# --- Main Execution ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python poly_get_condition_ids_v2.py <polymarket_event_or_market_url>", file=sys.stderr)
        sys.exit(1)

    target_url = sys.argv[1]

    if not target_url.startswith(("http://", "https://")):
        print(f"Error: Invalid URL format: {target_url}", file=sys.stderr)
        sys.exit(1)

    # print(f"\nExtracting Market IDs, Titles, and Odds from: {target_url}", file=sys.stderr) # Status to stderr

    market_data = extract_market_info_with_odds(target_url) # Call updated function

    # --- Final Output ---
    if market_data is not None:
        # Print ONLY the JSON list to standard output
        print(json.dumps(market_data, indent=2))
    else:
        # Print an empty JSON list to standard output on failure
        print("[]")
        # sys.exit(1) # Optional: exit with error code
