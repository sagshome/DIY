
# Get ETFS - should also work with simple Equities
import pandas as pd
import requests

BASE_URL = "https://stockanalysis.com/list/canadian-etfs/"

def discover_canadian_etfs(max_pages=20):
    """
    Discover ETF tickers from a published Canadian ETF directory.

    Returns a DataFrame containing ticker symbols and fund names.
    """
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    all_tables = []

    for page in range(1, max_pages + 1):
        url = BASE_URL if page == 1 else f"{BASE_URL}?p={page}"

        response = requests.get(
            url,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        tables = pd.read_html(response.text)

        if not tables:
            break

        table = tables[0]

        if "Symbol" not in table.columns:
            break

        table = table[["Symbol", "Company Name"]].copy()

        if table.empty:
            break

        all_tables.append(table)

    if not all_tables:
        raise RuntimeError("Could not retrieve the ETF listing.")

    etfs = pd.concat(all_tables, ignore_index=True)

    etfs = (
        etfs
        .dropna(subset=["Symbol"])
        .drop_duplicates(subset=["Symbol"])
        .reset_index(drop=True)
    )

    return etfs


etfs = discover_canadian_etfs()

print(f"Discovered {len(etfs)} ETF listings")
print(etfs.head(20))

etfs.to_csv("canadian_etfs_discovered.csv", index=False)


# Convert them for yahoo
def to_yahoo_ticker(symbol):
    symbol = str(symbol).strip().upper()

    # Yahoo commonly uses a hyphen for share-class separators.
    symbol = symbol.replace(".", "-")

    return f"{symbol}.TO"
    # Note,  sometime other suffix values are needed

etfs["YahooTicker"] = etfs["Symbol"].apply(to_yahoo_ticker)

print(etfs[["Symbol", "YahooTicker", "Company Name"]].head(20))

# Get info,   this is NOT how I would do it.
import yfinance as yf

sample_tickers = etfs["YahooTicker"].head(20).tolist()

prices = yf.download(
    tickers=sample_tickers,
    period="5d",
    interval="1d",
    auto_adjust=True,
    progress=False,
    group_by="ticker",
    threads=True,
)

print(prices.tail())