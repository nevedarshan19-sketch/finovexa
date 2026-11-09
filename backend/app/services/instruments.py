from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from ..config import settings
from ..models import MarketInstrument, ResearchSignal, utcnow
from .market import latest_quote, quote_to_dict, refresh_live_quotes

# NSE NIFTY 50 constituents and their public Upstox instrument keys, generated from
# the NSE constituent list and the Upstox NSE instruments master. Keys are public
# identifiers, not credentials.
NIFTY50_STOCKS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ADANIENT", "Adani Enterprises", "Metals & Mining", "NSE_EQ|INE423A01024", "25"),
    ("ADANIPORTS", "Adani Ports and Special Economic Zone", "Services", "NSE_EQ|INE742F01042", "15083"),
    ("APOLLOHOSP", "Apollo Hospitals Enterprise", "Healthcare", "NSE_EQ|INE437A01024", "157"),
    ("ASIANPAINT", "Asian Paints", "Consumer Durables", "NSE_EQ|INE021A01026", "236"),
    ("AXISBANK", "Axis Bank", "Financial Services", "NSE_EQ|INE238A01034", "5900"),
    ("BSE", "BSE", "Financial Services", "NSE_EQ|INE118H01025", "19585"),
    ("BAJAJ-AUTO", "Bajaj Auto", "Automobile and Auto Components", "NSE_EQ|INE917I01010", "16669"),
    ("BAJFINANCE", "Bajaj Finance", "Financial Services", "NSE_EQ|INE296A01032", "317"),
    ("BAJAJFINSV", "Bajaj Finserv", "Financial Services", "NSE_EQ|INE918I01026", "16675"),
    ("BEL", "Bharat Electronics", "Capital Goods", "NSE_EQ|INE263A01024", "383"),
    ("BHARTIARTL", "Bharti Airtel", "Telecommunication", "NSE_EQ|INE397D01024", "10604"),
    ("CIPLA", "Cipla", "Healthcare", "NSE_EQ|INE059A01026", "694"),
    ("COALINDIA", "Coal India", "Oil Gas & Consumable Fuels", "NSE_EQ|INE522F01014", "20374"),
    ("DRREDDY", "Dr. Reddy's Laboratories", "Healthcare", "NSE_EQ|INE089A01031", "881"),
    ("EICHERMOT", "Eicher Motors", "Automobile and Auto Components", "NSE_EQ|INE066A01021", "910"),
    ("ETERNAL", "Eternal", "Consumer Services", "NSE_EQ|INE758T01015", "5097"),
    ("GRASIM", "Grasim Industries", "Construction Materials", "NSE_EQ|INE047A01021", "1232"),
    ("HCLTECH", "HCL Technologies", "Information Technology", "NSE_EQ|INE860A01027", "7229"),
    ("HDFCBANK", "HDFC Bank", "Financial Services", "NSE_EQ|INE040A01034", "1333"),
    ("HDFCLIFE", "HDFC Life Insurance Company", "Financial Services", "NSE_EQ|INE795G01014", "467"),
    ("HINDALCO", "Hindalco Industries", "Metals & Mining", "NSE_EQ|INE038A01020", "1363"),
    ("HINDUNILVR", "Hindustan Unilever", "Fast Moving Consumer Goods", "NSE_EQ|INE030A01027", "1394"),
    ("ICICIBANK", "ICICI Bank", "Financial Services", "NSE_EQ|INE090A01021", "4963"),
    ("ITC", "ITC", "Fast Moving Consumer Goods", "NSE_EQ|INE154A01025", "1660"),
    ("INFY", "Infosys", "Information Technology", "NSE_EQ|INE009A01021", "1594"),
    ("INDIGO", "InterGlobe Aviation", "Services", "NSE_EQ|INE646L01027", "11195"),
    ("JSWSTEEL", "JSW Steel", "Metals & Mining", "NSE_EQ|INE019A01038", "11723"),
    ("JIOFIN", "Jio Financial Services", "Financial Services", "NSE_EQ|INE758E01017", "18143"),
    ("KOTAKBANK", "Kotak Mahindra Bank", "Financial Services", "NSE_EQ|INE237A01036", "1922"),
    ("LT", "Larsen & Toubro", "Construction", "NSE_EQ|INE018A01030", "11483"),
    ("M&M", "Mahindra & Mahindra", "Automobile and Auto Components", "NSE_EQ|INE101A01026", "2031"),
    ("MARUTI", "Maruti Suzuki India", "Automobile and Auto Components", "NSE_EQ|INE585B01010", "10999"),
    ("MAXHEALTH", "Max Healthcare Institute", "Healthcare", "NSE_EQ|INE027H01010", "22377"),
    ("NTPC", "NTPC", "Power", "NSE_EQ|INE733E01010", "11630"),
    ("NESTLEIND", "Nestle India", "Fast Moving Consumer Goods", "NSE_EQ|INE239A01024", "17963"),
    ("ONGC", "Oil & Natural Gas Corporation", "Oil Gas & Consumable Fuels", "NSE_EQ|INE213A01029", "2475"),
    ("POWERGRID", "Power Grid Corporation of India", "Power", "NSE_EQ|INE752E01010", "14977"),
    ("RELIANCE", "Reliance Industries", "Oil Gas & Consumable Fuels", "NSE_EQ|INE002A01018", "2885"),
    ("SBILIFE", "SBI Life Insurance Company", "Financial Services", "NSE_EQ|INE123W01016", "21808"),
    ("SHRIRAMFIN", "Shriram Finance", "Financial Services", "NSE_EQ|INE721A01047", "4306"),
    ("SBIN", "State Bank of India", "Financial Services", "NSE_EQ|INE062A01020", "3045"),
    ("SUNPHARMA", "Sun Pharmaceutical Industries", "Healthcare", "NSE_EQ|INE044A01036", "3351"),
    ("TCS", "Tata Consultancy Services", "Information Technology", "NSE_EQ|INE467B01029", "11536"),
    ("TATACONSUM", "Tata Consumer Products", "Fast Moving Consumer Goods", "NSE_EQ|INE192A01025", "3432"),
    ("TMPV", "Tata Motors Passenger Vehicles", "Automobile and Auto Components", "NSE_EQ|INE155A01022", "3456"),
    ("TATASTEEL", "Tata Steel", "Metals & Mining", "NSE_EQ|INE081A01020", "3499"),
    ("TECHM", "Tech Mahindra", "Information Technology", "NSE_EQ|INE669C01036", "13538"),
    ("TITAN", "Titan Company", "Consumer Durables", "NSE_EQ|INE280A01028", "3506"),
    ("TRENT", "Trent", "Consumer Services", "NSE_EQ|INE849A01020", "1964"),
    ("ULTRACEMCO", "UltraTech Cement", "Construction Materials", "NSE_EQ|INE481G01011", "11532"),
)


# Illustrative price levels for deterministic demo candles. These are not live
# quotes and are only used when no Upstox access token is configured.
NIFTY50_DEMO_BASES: dict[str, Decimal] = {
    "ADANIENT": Decimal("2450.00"),
    "ADANIPORTS": Decimal("1450.00"),
    "APOLLOHOSP": Decimal("7200.00"),
    "ASIANPAINT": Decimal("2450.00"),
    "AXISBANK": Decimal("1180.00"),
    "BSE": Decimal("2350.00"),
    "BAJAJ-AUTO": Decimal("8900.00"),
    "BAJFINANCE": Decimal("950.00"),
    "BAJAJFINSV": Decimal("2050.00"),
    "BEL": Decimal("380.00"),
    "BHARTIARTL": Decimal("1900.00"),
    "CIPLA": Decimal("1550.00"),
    "COALINDIA": Decimal("400.00"),
    "DRREDDY": Decimal("1300.00"),
    "EICHERMOT": Decimal("5400.00"),
    "ETERNAL": Decimal("300.00"),
    "GRASIM": Decimal("2750.00"),
    "HCLTECH": Decimal("1750.00"),
    "HDFCBANK": Decimal("1760.00"),
    "HDFCLIFE": Decimal("780.00"),
    "HINDALCO": Decimal("720.00"),
    "HINDUNILVR": Decimal("2500.00"),
    "ICICIBANK": Decimal("1420.00"),
    "ITC": Decimal("430.00"),
    "INFY": Decimal("1890.00"),
    "INDIGO": Decimal("5200.00"),
    "JSWSTEEL": Decimal("1050.00"),
    "JIOFIN": Decimal("320.00"),
    "KOTAKBANK": Decimal("2100.00"),
    "LT": Decimal("3800.00"),
    "M&M": Decimal("3200.00"),
    "MARUTI": Decimal("12800.00"),
    "MAXHEALTH": Decimal("1150.00"),
    "NTPC": Decimal("380.00"),
    "NESTLEIND": Decimal("2300.00"),
    "ONGC": Decimal("260.00"),
    "POWERGRID": Decimal("300.00"),
    "RELIANCE": Decimal("1485.00"),
    "SBILIFE": Decimal("1650.00"),
    "SHRIRAMFIN": Decimal("750.00"),
    "SBIN": Decimal("850.00"),
    "SUNPHARMA": Decimal("1750.00"),
    "TCS": Decimal("4120.00"),
    "TATACONSUM": Decimal("1150.00"),
    "TMPV": Decimal("380.00"),
    "TATASTEEL": Decimal("165.00"),
    "TECHM": Decimal("1650.00"),
    "TITAN": Decimal("3800.00"),
    "TRENT": Decimal("6200.00"),
    "ULTRACEMCO": Decimal("11800.00"),
}

_SECTOR_VOLATILITY = {
    "Financial Services": 0.010,
    "Information Technology": 0.009,
    "Metals & Mining": 0.014,
    "Automobile and Auto Components": 0.011,
    "Fast Moving Consumer Goods": 0.008,
    "Healthcare": 0.010,
    "Oil Gas & Consumable Fuels": 0.012,
    "Power": 0.010,
    "Consumer Durables": 0.010,
}


def nifty50_demo_specs() -> list[dict]:
    return [
        {
            "symbol": symbol,
            "name": name,
            "asset_class": "equity",
            "exchange": "NSE",
            "currency": "INR",
            "unit": "share",
            "external_key": instrument_key,
            "sector": sector,
            "base": NIFTY50_DEMO_BASES[symbol],
            "drift": Decimal("0.0007"),
            "volatility": _SECTOR_VOLATILITY.get(sector, 0.010),
        }
        for symbol, name, sector, instrument_key, _ in NIFTY50_STOCKS
    ]


def stock_token_catalogue(db: Session) -> dict:
    covered = {
        row[0]
        for row in db.query(MarketInstrument.symbol)
        .filter(MarketInstrument.asset_class == "equity")
        .all()
    }
    signal_symbols = {
        row[0]
        for row in db.query(MarketInstrument.symbol)
        .join(ResearchSignal, ResearchSignal.instrument_id == MarketInstrument.id)
        .distinct()
        .all()
    }
    items = [
        {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "exchange": "NSE",
            "instrument_key": instrument_key,
            "exchange_token": exchange_token,
            "seeded": symbol in covered,
            "research_coverage": symbol in signal_symbols,
            "signal_available": symbol in signal_symbols,
        }
        for symbol, name, sector, instrument_key, exchange_token in NIFTY50_STOCKS
    ]
    covered_count = sum(1 for item in items if item["seeded"])
    signal_count = sum(1 for item in items if item["research_coverage"])
    return {
        "index": "NIFTY 50",
        "total": len(items),
        "covered": covered_count,
        "signals": signal_count,
        "items": items,
        "note": (
            "Public Upstox instrument identifiers for every NIFTY 50 constituent. "
            "They are not credentials and are safe to display."
        ),
        "coverage_note": (
            f"Quotes and simulated buy/sell are seeded for {covered_count} of {len(items)} constituents. "
            f"{signal_count} stocks also carry a model research signal. Live Upstox quotes replace demo prices "
            "when the backend access token is configured."
        ),
        "provider_note": "Instrument keys are static metadata; quotes still follow the Upstox credential and data-mode rules.",
    }


def nifty50_trade_desk(db: Session) -> dict:
    provider_errors, _ = refresh_live_quotes(db)
    instruments = {
        instrument.symbol: instrument
        for instrument in db.query(MarketInstrument)
        .filter(MarketInstrument.asset_class == "equity")
        .all()
    }
    signal_symbols = {
        row[0]
        for row in db.query(MarketInstrument.symbol)
        .join(ResearchSignal, ResearchSignal.instrument_id == MarketInstrument.id)
        .distinct()
        .all()
    }
    items = []
    modes = {"live": 0, "demo": 0, "stale": 0, "unavailable": 0}
    for symbol, name, sector, instrument_key, exchange_token in NIFTY50_STOCKS:
        instrument = instruments.get(symbol)
        quote = latest_quote(db, instrument.id) if instrument else None
        quote_payload = quote_to_dict(instrument, quote) if instrument else None
        tradable = bool(quote_payload and quote_payload.get("price"))
        if quote_payload:
            if quote_payload.get("is_stale"):
                modes["stale"] += 1
            elif quote_payload.get("data_mode") == "demo":
                modes["demo"] += 1
            elif quote_payload.get("price") is not None:
                modes["live"] += 1
            else:
                modes["unavailable"] += 1
        else:
            modes["unavailable"] += 1
        items.append(
            {
                "symbol": symbol,
                "name": name,
                "sector": sector,
                "exchange": "NSE",
                "currency": "INR",
                "instrument_key": instrument_key,
                "exchange_token": exchange_token,
                "instrument_id": instrument.id if instrument else None,
                "quote": quote_payload,
                "signal_available": symbol in signal_symbols,
                "tradable": tradable,
            }
        )
    return {
        "index": "NIFTY 50",
        "total": len(items),
        "tradable": sum(1 for item in items if item["tradable"]),
        "items": items,
        "modes": modes,
        "provider": {
            "upstox_configured": settings.upstox_configured,
            "provider_errors": provider_errors,
            "note": (
                "Live NIFTY 50 quotes are fetched from Upstox in a single batch call and cached briefly."
                if settings.upstox_configured
                else "No Upstox access token is configured on the backend, so quotes are clearly labelled demo."
            ),
        },
        "orders_note": (
            "Every buy or sell creates a simulated order request that requires owner approval. "
            "No live broker order is placed and no holdings, cash or positions move."
        ),
        "as_of": utcnow(),
    }
