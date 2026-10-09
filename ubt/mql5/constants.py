"""MQL5 constants used by ported Expert Advisors.

Integer enum values are the real MetaTrader 5 values, so inputs stored in
MT5 ``.set`` files (which hold enums as integers) load without translation.
Property identifiers (SYMBOL_*, ACCOUNT_*, POSITION_*, ...) are strings: they
are only ever passed back into the emulated API, never stored.
"""

# --------------------------------------------------------------------------
# Generic
# --------------------------------------------------------------------------
DBL_MAX = 1.7976931348623157e308
DBL_MIN = 2.2250738585072014e-308
DBL_EPSILON = 2.220446049250313e-16
EMPTY_VALUE = DBL_MAX
INT_MAX = 2147483647
INT_MIN = -2147483648
LONG_MAX = 9223372036854775807
WRONG_VALUE = -1
INVALID_HANDLE = -1

INIT_SUCCEEDED = 0
INIT_FAILED = 1
INIT_PARAMETERS_INCORRECT = 2
INIT_AGENT_NOT_SUITABLE = 3

# --------------------------------------------------------------------------
# Timeframes (real MT5 values)
# --------------------------------------------------------------------------
PERIOD_CURRENT = 0
PERIOD_M1 = 1
PERIOD_M2 = 2
PERIOD_M3 = 3
PERIOD_M4 = 4
PERIOD_M5 = 5
PERIOD_M6 = 6
PERIOD_M10 = 10
PERIOD_M12 = 12
PERIOD_M15 = 15
PERIOD_M20 = 20
PERIOD_M30 = 30
PERIOD_H1 = 16385
PERIOD_H2 = 16386
PERIOD_H3 = 16387
PERIOD_H4 = 16388
PERIOD_H6 = 16390
PERIOD_H8 = 16392
PERIOD_H12 = 16396
PERIOD_D1 = 16408
PERIOD_W1 = 32769
PERIOD_MN1 = 49153

TIMEFRAME_SECONDS = {
    PERIOD_M1: 60, PERIOD_M2: 120, PERIOD_M3: 180, PERIOD_M4: 240,
    PERIOD_M5: 300, PERIOD_M6: 360, PERIOD_M10: 600, PERIOD_M12: 720,
    PERIOD_M15: 900, PERIOD_M20: 1200, PERIOD_M30: 1800,
    PERIOD_H1: 3600, PERIOD_H2: 7200, PERIOD_H3: 10800, PERIOD_H4: 14400,
    PERIOD_H6: 21600, PERIOD_H8: 28800, PERIOD_H12: 43200,
    PERIOD_D1: 86400, PERIOD_W1: 604800, PERIOD_MN1: 2592000,
}
TIMEFRAME_NAMES = {
    PERIOD_M1: "M1", PERIOD_M2: "M2", PERIOD_M3: "M3", PERIOD_M4: "M4",
    PERIOD_M5: "M5", PERIOD_M6: "M6", PERIOD_M10: "M10", PERIOD_M12: "M12",
    PERIOD_M15: "M15", PERIOD_M20: "M20", PERIOD_M30: "M30",
    PERIOD_H1: "H1", PERIOD_H2: "H2", PERIOD_H3: "H3", PERIOD_H4: "H4",
    PERIOD_H6: "H6", PERIOD_H8: "H8", PERIOD_H12: "H12",
    PERIOD_D1: "D1", PERIOD_W1: "W1", PERIOD_MN1: "MN1",
}
TIMEFRAME_BY_NAME = {v: k for k, v in TIMEFRAME_NAMES.items()}

# --------------------------------------------------------------------------
# Moving averages / applied price
# --------------------------------------------------------------------------
MODE_SMA = 0
MODE_EMA = 1
MODE_SMMA = 2
MODE_LWMA = 3

PRICE_CLOSE = 1
PRICE_OPEN = 2
PRICE_HIGH = 3
PRICE_LOW = 4
PRICE_MEDIAN = 5
PRICE_TYPICAL = 6
PRICE_WEIGHTED = 7

MAIN_LINE = 0
SIGNAL_LINE = 1
BASE_LINE = 0
UPPER_BAND = 1
LOWER_BAND = 2

# --------------------------------------------------------------------------
# Orders / positions / deals
# --------------------------------------------------------------------------
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_TYPE_BUY_LIMIT = 2
ORDER_TYPE_SELL_LIMIT = 3
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
ORDER_TYPE_BUY_STOP_LIMIT = 6
ORDER_TYPE_SELL_STOP_LIMIT = 7
ORDER_TYPE_CLOSE_BY = 8

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_FILLING_BOC = 3

ORDER_TIME_GTC = 0
ORDER_TIME_DAY = 1
ORDER_TIME_SPECIFIED = 2
ORDER_TIME_SPECIFIED_DAY = 3

ORDER_STATE_STARTED = 0
ORDER_STATE_PLACED = 1
ORDER_STATE_CANCELED = 2
ORDER_STATE_PARTIAL = 3
ORDER_STATE_FILLED = 4
ORDER_STATE_REJECTED = 5
ORDER_STATE_EXPIRED = 6

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1
DEAL_TYPE_BALANCE = 2

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_INOUT = 2
DEAL_ENTRY_OUT_BY = 3

DEAL_REASON_CLIENT = 0
DEAL_REASON_MOBILE = 1
DEAL_REASON_WEB = 2
DEAL_REASON_EXPERT = 3
DEAL_REASON_SL = 4
DEAL_REASON_TP = 5
DEAL_REASON_SO = 6

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8
TRADE_ACTION_CLOSE_BY = 10

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2
SYMBOL_FILLING_BOC = 4

ACCOUNT_MARGIN_MODE_RETAIL_NETTING = 0
ACCOUNT_MARGIN_MODE_EXCHANGE = 1
ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2

SYMBOL_CALC_MODE_FOREX = 0
SYMBOL_CALC_MODE_FUTURES = 1
SYMBOL_CALC_MODE_CFD = 2
SYMBOL_CALC_MODE_CFDINDEX = 3
SYMBOL_CALC_MODE_CFDLEVERAGE = 4
SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE = 5

SYMBOL_SWAP_MODE_DISABLED = 0
SYMBOL_SWAP_MODE_POINTS = 1
SYMBOL_SWAP_MODE_CURRENCY_SYMBOL = 2
SYMBOL_SWAP_MODE_CURRENCY_MARGIN = 3
SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT = 4
SYMBOL_SWAP_MODE_INTEREST_CURRENT = 5
SYMBOL_SWAP_MODE_INTEREST_OPEN = 6

# --------------------------------------------------------------------------
# Trade server return codes
# --------------------------------------------------------------------------
TRADE_RETCODE_REQUOTE = 10004
TRADE_RETCODE_REJECT = 10006
TRADE_RETCODE_CANCEL = 10007
TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
TRADE_RETCODE_ERROR = 10011
TRADE_RETCODE_TIMEOUT = 10012
TRADE_RETCODE_INVALID = 10013
TRADE_RETCODE_INVALID_VOLUME = 10014
TRADE_RETCODE_INVALID_PRICE = 10015
TRADE_RETCODE_INVALID_STOPS = 10016
TRADE_RETCODE_TRADE_DISABLED = 10017
TRADE_RETCODE_MARKET_CLOSED = 10018
TRADE_RETCODE_NO_MONEY = 10019
TRADE_RETCODE_PRICE_CHANGED = 10020
TRADE_RETCODE_PRICE_OFF = 10021
TRADE_RETCODE_INVALID_EXPIRATION = 10022
TRADE_RETCODE_ORDER_CHANGED = 10023
TRADE_RETCODE_TOO_MANY_REQUESTS = 10024
TRADE_RETCODE_NO_CHANGES = 10025
TRADE_RETCODE_FROZEN = 10029
TRADE_RETCODE_INVALID_FILL = 10030
TRADE_RETCODE_INVALID_ORDER = 10035
TRADE_RETCODE_POSITION_CLOSED = 10036
TRADE_RETCODE_INVALID_CLOSE_VOLUME = 10038
TRADE_RETCODE_LIMIT_POSITIONS = 10040

RETCODE_TEXT = {
    10004: "Requote", 10006: "Request rejected", 10007: "Request canceled",
    10008: "Order placed", 10009: "Request completed", 10010: "Partial fill",
    10011: "Request processing error", 10013: "Invalid request",
    10014: "Invalid volume", 10015: "Invalid price", 10016: "Invalid stops",
    10017: "Trade disabled", 10018: "Market closed", 10019: "No money",
    10025: "No changes", 10029: "Frozen", 10030: "Invalid fill",
    10035: "Invalid order", 10036: "Position closed",
    10038: "Invalid close volume", 10040: "Positions limit",
}

# Runtime error codes (GetLastError)
ERR_SUCCESS = 0
ERR_TRADE_POSITION_NOT_FOUND = 4753
ERR_TRADE_ORDER_NOT_FOUND = 4754
ERR_TRADE_DEAL_NOT_FOUND = 4755
ERR_TRADE_SEND_FAILED = 4756
ERR_MARKET_UNKNOWN_SYMBOL = 4301

# --------------------------------------------------------------------------
# Property identifiers (strings: only used as keys inside the emulator)
# --------------------------------------------------------------------------
SYMBOL_BID = "bid"
SYMBOL_ASK = "ask"
SYMBOL_LAST = "last"
SYMBOL_POINT = "point"
SYMBOL_DIGITS = "digits"
SYMBOL_SPREAD = "spread"
SYMBOL_SPREAD_FLOAT = "spread_float"
SYMBOL_TRADE_TICK_VALUE = "trade_tick_value"
SYMBOL_TRADE_TICK_VALUE_PROFIT = "trade_tick_value_profit"
SYMBOL_TRADE_TICK_VALUE_LOSS = "trade_tick_value_loss"
SYMBOL_TRADE_TICK_SIZE = "trade_tick_size"
SYMBOL_TRADE_CONTRACT_SIZE = "trade_contract_size"
SYMBOL_VOLUME_MIN = "volume_min"
SYMBOL_VOLUME_MAX = "volume_max"
SYMBOL_VOLUME_STEP = "volume_step"
SYMBOL_VOLUME_LIMIT = "volume_limit"
SYMBOL_TRADE_STOPS_LEVEL = "trade_stops_level"
SYMBOL_TRADE_FREEZE_LEVEL = "trade_freeze_level"
SYMBOL_FILLING_MODE = "filling_mode"
SYMBOL_TRADE_MODE = "trade_mode"
SYMBOL_TRADE_EXEMODE = "trade_exemode"
SYMBOL_TRADE_CALC_MODE = "trade_calc_mode"
SYMBOL_SWAP_MODE = "swap_mode"
SYMBOL_SWAP_LONG = "swap_long"
SYMBOL_SWAP_SHORT = "swap_short"
SYMBOL_SWAP_ROLLOVER3DAYS = "swap_rollover3days"
SYMBOL_MARGIN_INITIAL = "margin_initial"
SYMBOL_MARGIN_MAINTENANCE = "margin_maintenance"
SYMBOL_MARGIN_HEDGED = "margin_hedged"
SYMBOL_CURRENCY_BASE = "currency_base"
SYMBOL_CURRENCY_PROFIT = "currency_profit"
SYMBOL_CURRENCY_MARGIN = "currency_margin"
SYMBOL_DESCRIPTION = "description"
SYMBOL_PATH = "path"
SYMBOL_TIME = "time"
SYMBOL_VOLUME = "volume"
SYMBOL_SELECT = "select"
SYMBOL_VISIBLE = "visible"

ACCOUNT_BALANCE = "balance"
ACCOUNT_EQUITY = "equity"
ACCOUNT_PROFIT = "profit"
ACCOUNT_CREDIT = "credit"
ACCOUNT_MARGIN = "margin"
ACCOUNT_MARGIN_FREE = "margin_free"
ACCOUNT_MARGIN_LEVEL = "margin_level"
ACCOUNT_MARGIN_SO_CALL = "margin_so_call"
ACCOUNT_MARGIN_SO_SO = "margin_so_so"
ACCOUNT_LEVERAGE = "leverage"
ACCOUNT_LOGIN = "login"
ACCOUNT_MARGIN_MODE = "margin_mode"
ACCOUNT_TRADE_ALLOWED = "trade_allowed"
ACCOUNT_TRADE_EXPERT = "trade_expert"
ACCOUNT_LIMIT_ORDERS = "limit_orders"
ACCOUNT_CURRENCY = "currency"
ACCOUNT_COMPANY = "company"
ACCOUNT_SERVER = "server"
ACCOUNT_NAME = "name"

POSITION_TICKET = "ticket"
POSITION_IDENTIFIER = "identifier"
POSITION_SYMBOL = "symbol"
POSITION_TYPE = "type"
POSITION_MAGIC = "magic"
POSITION_VOLUME = "volume"
POSITION_PRICE_OPEN = "price_open"
POSITION_PRICE_CURRENT = "price_current"
POSITION_SL = "sl"
POSITION_TP = "tp"
POSITION_PROFIT = "profit"
POSITION_SWAP = "swap"
POSITION_COMMISSION = "commission"
POSITION_TIME = "time"
POSITION_TIME_MSC = "time_msc"
POSITION_TIME_UPDATE = "time_update"
POSITION_COMMENT = "comment"
POSITION_REASON = "reason"

ORDER_TICKET = "ticket"
ORDER_SYMBOL = "symbol"
ORDER_TYPE = "type"
ORDER_MAGIC = "magic"
ORDER_VOLUME_INITIAL = "volume_initial"
ORDER_VOLUME_CURRENT = "volume_current"
ORDER_PRICE_OPEN = "price_open"
ORDER_PRICE_CURRENT = "price_current"
ORDER_SL = "sl"
ORDER_TP = "tp"
ORDER_TIME_SETUP = "time_setup"
ORDER_TIME_EXPIRATION = "time_expiration"
ORDER_TYPE_FILLING = "type_filling"
ORDER_TYPE_TIME = "type_time"
ORDER_STATE = "state"
ORDER_COMMENT = "comment"
ORDER_POSITION_ID = "position_id"

DEAL_TICKET = "ticket"
DEAL_ORDER = "order"
DEAL_POSITION_ID = "position_id"
DEAL_SYMBOL = "symbol"
DEAL_TYPE = "type"
DEAL_ENTRY = "entry"
DEAL_VOLUME = "volume"
DEAL_PRICE = "price"
DEAL_PROFIT = "profit"
DEAL_COMMISSION = "commission"
DEAL_SWAP = "swap"
DEAL_TIME = "time"
DEAL_TIME_MSC = "time_msc"
DEAL_MAGIC = "magic"
DEAL_COMMENT = "comment"
DEAL_REASON = "reason"

# --------------------------------------------------------------------------
# TesterStatistics identifiers
# --------------------------------------------------------------------------
STAT_INITIAL_DEPOSIT = "initial_deposit"
STAT_PROFIT = "net_profit"
STAT_GROSS_PROFIT = "gross_profit"
STAT_GROSS_LOSS = "gross_loss"
STAT_MAX_PROFITTRADE = "largest_profit_trade"
STAT_MAX_LOSSTRADE = "largest_loss_trade"
STAT_MAX_CONWINS = "max_consecutive_wins"
STAT_MAX_CONLOSSES = "max_consecutive_losses"
STAT_BALANCEMIN = "balance_min"
STAT_BALANCE_DD = "balance_dd_max"
STAT_BALANCEDD_PERCENT = "balance_dd_max_pct"
STAT_BALANCE_DDREL_PERCENT = "balance_dd_rel_pct"
STAT_EQUITYMIN = "equity_min"
STAT_EQUITY_DD = "equity_dd_max"
STAT_EQUITYDD_PERCENT = "equity_dd_max_pct"
STAT_EQUITY_DDREL_PERCENT = "equity_dd_rel_pct"
STAT_EXPECTED_PAYOFF = "expected_payoff"
STAT_PROFIT_FACTOR = "profit_factor"
STAT_RECOVERY_FACTOR = "recovery_factor"
STAT_SHARPE_RATIO = "sharpe_ratio"
STAT_MIN_MARGINLEVEL = "min_margin_level"
STAT_DEALS = "deals"
STAT_TRADES = "trades"
STAT_PROFIT_TRADES = "profit_trades"
STAT_LOSS_TRADES = "loss_trades"
STAT_SHORT_TRADES = "short_trades"
STAT_LONG_TRADES = "long_trades"
STAT_PROFIT_SHORTTRADES = "profit_short_trades"
STAT_PROFIT_LONGTRADES = "profit_long_trades"

# Chart objects (dashboard drawing is a no-op in the backtester)
OBJ_LABEL = 23
OBJPROP_CORNER = "corner"
OBJPROP_ANCHOR = "anchor"
OBJPROP_FONT = "font"
OBJPROP_SELECTABLE = "selectable"
OBJPROP_HIDDEN = "hidden"
OBJPROP_XDISTANCE = "xdistance"
OBJPROP_YDISTANCE = "ydistance"
OBJPROP_TEXT = "text"
OBJPROP_COLOR = "color"
OBJPROP_FONTSIZE = "fontsize"
CORNER_LEFT_UPPER = 0
CORNER_LEFT_LOWER = 1
ANCHOR_LEFT_LOWER = 2
clrAqua = 0x00FFFF
clrLightGray = 0xD3D3D3
clrOrange = 0x00A5FF
clrGold = 0x00D7FF
clrWhite = 0xFFFFFF
clrLightSkyBlue = 0xFACE87

# File flags (virtual file system)
FILE_READ = 1
FILE_WRITE = 2
FILE_BIN = 4
FILE_CSV = 8
FILE_TXT = 16
FILE_ANSI = 32
FILE_UNICODE = 64
FILE_SHARE_READ = 128
FILE_SHARE_WRITE = 256
FILE_REWRITE = 512
FILE_COMMON = 4096
