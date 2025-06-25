# Save as poly_combined_holder_stats_v5_clean_json_corrected.py
import sys
import re
import playwright
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import requests
import time
import json
from typing import List, Dict, Any, Optional, Tuple

# --- Helper Function to get Market Data from Event Page ---
def get_market_data_from_page(page) -> Optional[List[Dict[str, Any]]]:
    """Extracts the market data array from the __NEXT_DATA__ script tag."""
    # print("Extracting __NEXT_DATA__...") # Suppressed print
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
                 data_container = event_query_state.get("data", {})
                 if isinstance(data_container, dict):
                     markets_data = data_container.get("markets")
                     if not markets_data and "conditionId" in data_container:
                         markets_data = [data_container]
                 elif isinstance(data_container, list):
                     markets_data = data_container
        if not markets_data or not isinstance(markets_data, list):
             print("WARN: Could not find 'markets' list/data in __NEXT_DATA__.", file=sys.stderr)
             return None
        # print(f"Successfully extracted data for {len(markets_data)} market(s).") # Suppressed print
        return markets_data
    except Exception as e:
        # --- CORRECTED ERROR PRINT ---
        print(f"ERROR extracting or parsing market data from __NEXT_DATA__: {e}", file=sys.stderr)
        # --- END CORRECTION ---
        return None

# --- Helper Function to call Polymarket APIs ---
def call_polymarket_api(url: str, headers: Dict[str, str]) -> Optional[Any]:
    """Calls a Polymarket API endpoint and returns parsed JSON or None."""
    try:
        # print(f"    Calling API: {url}") # Suppressed print
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"    WARN: Failed API call {url}: {e}", file=sys.stderr)
        return None
    except json.JSONDecodeError:
        print(f"    WARN: Failed decoding API response JSON from {url}.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"    ERROR processing API response from {url}: {e}", file=sys.stderr)
        return None

# --- Helper Function to calculate Positions Value ---
def calculate_positions_value(positions_data: Optional[List[Dict[str, Any]]]) -> float:
    """Calculates total position value from the /positions API response."""
    total_value = 0.0
    if isinstance(positions_data, list):
        for position in positions_data:
            current_val = position.get("currentValue", 0.0)
            if isinstance(current_val, (int, float)):
                total_value += current_val
    return total_value

# --- Helper Function to Get Profile Stats & Find Specific Position ---
def get_profile_and_specific_position_data(
    holder_address: str,
    target_condition_id: str,
    target_outcome_index: int,
    api_headers: Dict[str, str]
) -> Dict[str, Any]:
    """
    Fetches overall Volume, P&L, calculates total Portfolio Value, AND extracts
    details for the SINGLE position matching the target_condition_id and outcome_index.
    """
    results = {
        "Overall Volume": "Error", "Overall Profit/Loss": "Error",
        "Total Portfolio Value": "Error", "Target Market Position": "Not Found"
    }
    positions_url = f"https://data-api.polymarket.com/positions?user={holder_address}&limit=1000"
    volume_url = f"https://lb-api.polymarket.com/volume?window=all&limit=1&address={holder_address}"
    profit_url = f"https://lb-api.polymarket.com/profit?window=all&limit=1&address={holder_address}"

    volume_data = call_polymarket_api(volume_url, api_headers)
    if volume_data and isinstance(volume_data, list) and len(volume_data) > 0:
        vol_amount = volume_data[0].get("amount", 0.0)
        try: results["Overall Volume"] = f"${float(vol_amount):,.2f}"
        except: results["Overall Volume"] = f"Error ({vol_amount})"

    profit_data = call_polymarket_api(profit_url, api_headers)
    if profit_data and isinstance(profit_data, list) and len(profit_data) > 0:
        pnl_amount = profit_data[0].get("amount", 0.0)
        try: results["Overall Profit/Loss"] = f"${float(pnl_amount):,.2f}"
        except: results["Overall Profit/Loss"] = f"Error ({pnl_amount})"

    positions_data = call_polymarket_api(positions_url, api_headers)
    if positions_data is not None and isinstance(positions_data, list):
        total_portfolio_value = calculate_positions_value(positions_data)
        results["Total Portfolio Value"] = f"${total_portfolio_value:,.2f}"
        target_position_details = None
        for pos in positions_data:
            if pos.get("conditionId") == target_condition_id and pos.get("outcomeIndex") == target_outcome_index:
                try: pos_size_fmt = f"{float(pos.get('size', 0)):,.0f}"
                except: pos_size_fmt = str(pos.get('size', 0))
                try: pos_avg_price_fmt = f"{float(pos.get('avgPrice', 0)*100):.1f}c"
                except: pos_avg_price_fmt = str(pos.get('avgPrice', 'N/A'))
                try: pos_cur_price_fmt = f"{float(pos.get('curPrice', 0)*100):.1f}c"
                except: pos_cur_price_fmt = str(pos.get('curPrice', 'N/A'))
                try: pos_pnl_fmt = f"${float(pos.get('cashPnl', 0)):,.2f}"
                except: pos_pnl_fmt = str(pos.get('cashPnl', 'N/A'))
                target_position_details = {
                    "shares_in_position": pos_size_fmt, "avg_price": pos_avg_price_fmt,
                    "current_price": pos_cur_price_fmt, "position_pnl": pos_pnl_fmt
                }
                break
        if target_position_details: results["Target Market Position"] = target_position_details
    # else: print(f"    WARN: Failed to get positions data for {holder_address}") # Less verbose

    return results

# --- Main Function ---
def process_market_holders_with_focused_stats(event_url: str, market_index: int = 0, max_holders_per_side: int = 10) -> Optional[Dict[str, Any]]:
    """
    Main function: gets market ID/prices, fetches holders, fetches stats.
    Returns a single dictionary containing market info and holder lists.
    """
    final_output = {}
    p_context = None
    browser = None
    market_found = False

    api_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.0.0 Safari/537.36',
        'Accept': 'application/json', 'Origin': 'https://polymarket.com', 'Referer': 'https://polymarket.com/',
    }
    try:
        print(f"Step 1: Getting Market info for index {market_index}...")
        p_context = sync_playwright().start()
        browser = p_context.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(event_url, wait_until='domcontentloaded')
        markets_list = get_market_data_from_page(page)
        browser.close()
        p_context.stop()

        if not markets_list: raise Exception("Failed to extract market list.")

        target_condition_id = None
        market_title = "Unknown Market"
        yes_price_str = "N/A"; no_price_str = "N/A"

        if 0 <= market_index < len(markets_list):
            target_market = markets_list[market_index]
            target_condition_id = target_market.get("conditionId")
            market_title = target_market.get("groupItemTitle") or target_market.get("question", f"Market {market_index}")
            outcome_prices = target_market.get("outcomePrices")
            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                try: yes_price_str = f"{float(outcome_prices[0])*100:.1f}%"
                except: yes_price_str = str(outcome_prices[0])
                try: no_price_str = f"{float(outcome_prices[1])*100:.1f}%"
                except: no_price_str = str(outcome_prices[1])
            market_found = True
        else: raise ValueError(f"Invalid market index {market_index}. Max index: {len(markets_list) - 1}")
        if not target_condition_id: raise Exception("Could not determine target conditionId.")

        final_output["market_info"] = {
            "title": market_title, "index": market_index, "conditionId": target_condition_id,
            "current_yes_odds": yes_price_str, "current_no_odds": no_price_str
        }
        print(f"Found target market: '{market_title}' ({target_condition_id})")
        print(f"Current Odds: Yes {yes_price_str}, No {no_price_str}")

        holders_api_url = f"https://data-api.polymarket.com/holders?market={target_condition_id}&limit={max_holders_per_side * 2 + 10}"
        print(f"Step 2: Fetching holders from API...")
        raw_api_holder_data = call_polymarket_api(holders_api_url, api_headers)
        if raw_api_holder_data is None: raise Exception("Failed to get holder list from API.")
        if not isinstance(raw_api_holder_data, list): raise TypeError("API holder response not a list.")

        final_output["holders"] = {"Yes": [], "No": []}

        print(f"Step 3: Fetching stats for top {max_holders_per_side} holders per side...")
        for outcome_index in [0, 1]:
             outcome_name = "Yes" if outcome_index == 0 else "No"
             # print(f"  Processing '{outcome_name}' Holders...") # Less verbose
             processed_count = 0
             found_outcome_data = False
             outcome_specific_holders = []
             for outcome_data in raw_api_holder_data:
                 current_holders_list = outcome_data.get("holders")
                 if current_holders_list and len(current_holders_list) > 0 and current_holders_list[0].get("outcomeIndex") == outcome_index:
                     outcome_specific_holders = current_holders_list
                     found_outcome_data = True
                     break
             if not found_outcome_data: continue # Silently skip if no holders for this side

             for i, holder in enumerate(outcome_specific_holders):
                 if processed_count >= max_holders_per_side: break
                 holder_address = holder.get("proxyWallet")
                 holder_name = holder.get("name", holder_address[:10]+"...") if holder_address else "N/A"
                 holder_shares_in_market = holder.get("amount", 0)
                 if not holder_address: continue

                 # print(f"    Processing {outcome_name} holder {i+1}: {holder_name}") # Verbose
                 profile_and_pos_data = get_profile_and_specific_position_data(
                     holder_address, target_condition_id, outcome_index, api_headers
                 )
                 try: shares_formatted = f"{float(holder_shares_in_market):,.0f}"
                 except: shares_formatted = str(holder_shares_in_market)

                 final_output["holders"][outcome_name].append({
                     "rank": i + 1, "name": holder_name, "address": holder_address,
                     "overall_volume": profile_and_pos_data.get("Overall Volume"),
                     "overall_pnl": profile_and_pos_data.get("Overall Profit/Loss"),
                     "total_portfolio_value": profile_and_pos_data.get("Total Portfolio Value"),
                     "target_market_position": profile_and_pos_data.get("Target Market Position")
                 })
                 processed_count += 1
                 # print("    Pausing 1s before next holder...") # Keep commented unless needed
                 time.sleep(1) # Keep rate limit

        print("--- Finished processing all outcomes ---")
        return final_output

    except Exception as e:
        print(f"\n--- SCRIPT ERROR ---")
        print(f"An error occurred: {e}", file=sys.stderr)
        if p_context and 'browser' in locals() and browser and browser.is_connected(): browser.close()
        if p_context: p_context.stop()
        return None # Indicate failure


# --- Main Execution ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python poly_holder_stats_clean_json_corrected.py <url> [market_index] [max_holders]")
        print("  Defaults: Market Index=0, Max Holders=5")
        sys.exit(1)

    target_url = sys.argv[1]
    market_idx_arg = 0
    max_h_arg = 5

    # Argument Parsing (same as v2)
    if len(sys.argv) == 3:
        try:
            max_h_arg = int(sys.argv[2])
            if max_h_arg <= 0: raise ValueError("Max holders must be positive")
            print(f"Using default market index 0 and max_holders={max_h_arg}")
        except ValueError as e:
            print(f"Warn: Invalid max_holders '{sys.argv[2]}'. Using defaults. Error: {e}")
            market_idx_arg = 0; max_h_arg = 5
    elif len(sys.argv) >= 4:
        try:
            market_idx_arg = int(sys.argv[2])
            if market_idx_arg < 0: raise ValueError("Market index cannot be negative")
            print(f"Market index provided: {market_idx_arg}")
        except ValueError as e:
            print(f"Warn: Invalid market index '{sys.argv[2]}'. Using default index 0. Error: {e}")
            market_idx_arg = 0
        try:
            max_h_arg = int(sys.argv[3])
            if max_h_arg <= 0: raise ValueError("Max holders must be positive")
            print(f"Max holders per side provided: {max_h_arg}")
        except (ValueError, IndexError) as e:
            print(f"Warn: Invalid or missing max_holders arg. Using default {max_h_arg}. Error: {e}")
            max_h_arg = 5
    else:
        print("Using defaults (index=0, max_holders=5).")


    if not target_url.startswith(("http://", "https://")): print("Error: Invalid URL"); sys.exit(1)

    print(f"\nAttempting fetch for Yes/No holders' focused stats from: {target_url} using API...")

    # Call the main processing function
    results_data = process_market_holders_with_focused_stats(target_url, market_idx_arg, max_h_arg) # Call correct function name

    # --- Clean JSON Output ---
    if results_data is not None:
        print("\n" + "="*10 + " FINAL JSON OUTPUT " + "="*10)
        # Print the entire results dictionary as a single JSON object
        print(json.dumps(results_data, indent=2))
        print("="*10 + " END JSON OUTPUT " + "="*10 + "\n")
    else:
        print(f"\nScript finished: Failed to extract holder data.")
        # Optionally print an empty JSON or error structure
        # print(json.dumps({"error": "Failed to extract data"}, indent=2))
