# polymarket-top-holder-analysis
scripts to pull info of top holders of a market on polymarket. this info will be used to do an analysis of the holders on each side, including trading history success and portfolio size to access whether the Yes or No side of the trade has the "better" holders. NOT TO BE USED FOR FINANCIAL ADVICE.

get_market_ids_json.py - returns the options if a market has multiple options i.e. Who will be president? Trump (yes/no) Biden (yes/no) vs. single option market: Will Trump be president? Yes or No.
arg1 - url of the market.
output: json object of market ids and details for each.

get_top_holders_details_json.py - returns the top holders of a market.
arg1 - url of te market
arg2 - market id (default is 0)
arg3 - number of top holders you want.
output: json object of the top yes and no holders for the given market.

