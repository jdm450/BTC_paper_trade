import requests
import sys
import json
import os
import uuid
from datetime import datetime
import signal
import threading
import time
import websocket
from tabulate import tabulate

# Global variable to store the latest BTC price
latest_btc_price = None
price_lock = threading.Lock()
ws_app = None  # WebSocketApp instance

def on_message(ws, message):
    global latest_btc_price
    try:
        data = json.loads(message)
        # Kraken sends data as a list where the second element contains the ticker info
        if isinstance(data, list) and len(data) >= 2:
            ticker_info = data[1]
            # 'c' is the last trade closed array: [price, lot volume]
            latest_price = float(ticker_info['c'][0])
            with price_lock:
                latest_btc_price = latest_price
            # Uncomment the following line to see live price updates
            # print(f"Updated BTC Price: ${latest_btc_price}")
    except (KeyError, ValueError, IndexError) as e:
        print(f"Error parsing message: {e}")

def on_error(ws, error):
    print(f"WebSocket error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WebSocket connection closed")

def on_open(ws):
    print("WebSocket connection established")
    # Subscribe to the BTC/USD ticker stream
    subscribe_message = {
        "event": "subscribe",
        "pair": ["BTC/USD"],
        "subscription": {
            "name": "ticker"
        }
    }
    ws.send(json.dumps(subscribe_message))

def start_websocket():
    global ws_app
    websocket_url = "wss://ws.kraken.com/"
    ws_app = websocket.WebSocketApp(
        websocket_url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws_app.run_forever()

def get_current_btc_price():
    """
    Retrieves the latest Bitcoin price from the Kraken WebSocket stream.
    Returns:
        float: Current price of Bitcoin in USD, or None if not available.
    """
    with price_lock:
        return latest_btc_price

class BitcoinPaperTrader:
    def __init__(self, starting_cash=20000.0, data_file='trader_data.json', history_file='transaction_history.json'):
        """
        Initializes the BitcoinPaperTrader instance.

        Args:
            starting_cash (float): Initial cash balance in USD.
            data_file (str): Path to the JSON file for data persistence.
            history_file (str): Path to the JSON file for transaction history.
        """
        self.data_file = data_file
        self.history_file = history_file
        self.starting_cash = starting_cash
        self.starting_total = starting_cash  # Initial total is only cash

        # Load existing data or initialize with starting balances
        if os.path.exists(self.data_file):
            self.load_data()
            print(f"Loaded data: Cash: ${self.cash_balance:,.2f}, BTC: {self.btc_balance:.6f} BTC\n")
        else:
            self.cash_balance = starting_cash
            self.btc_balance = 0.0
            self.save_data()
            print(f"Initialized with Cash: ${self.cash_balance:,.2f} and BTC: {self.btc_balance:.6f} BTC\n")

        # Load existing transaction history or initialize empty
        if os.path.exists(self.history_file):
            self.load_history()
        else:
            self.transaction_history = []
            self.save_history()

    def load_data(self):
        """
        Loads trader data from the JSON file.
        """
        try:
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.cash_balance = data.get('cash_balance', self.starting_cash)
                self.btc_balance = data.get('btc_balance', 0.0)
                self.starting_total = data.get('starting_total', self.starting_cash)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Error loading data: {e}. Initializing with default values.")
            self.cash_balance = self.starting_cash
            self.btc_balance = 0.0
            self.starting_total = self.starting_cash
            self.save_data()

    def save_data(self):
        """
        Saves trader data to the JSON file.
        """
        data = {
            'cash_balance': self.cash_balance,
            'btc_balance': self.btc_balance,
            'starting_total': self.starting_total
        }
        try:
            with open(self.data_file, 'w') as f:
                json.dump(data, f, indent=4)
        except IOError as e:
            print(f"Error saving data: {e}")

    def load_history(self):
        """
        Loads transaction history from the JSON file.
        """
        try:
            with open(self.history_file, 'r') as f:
                self.transaction_history = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"Error loading transaction history: {e}. Initializing empty history.")
            self.transaction_history = []
            self.save_history()

    def save_history(self):
        """
        Saves transaction history to the JSON file.
        """
        try:
            with open(self.history_file, 'w') as f:
                json.dump(self.transaction_history, f, indent=4)
        except IOError as e:
            print(f"Error saving transaction history: {e}")

    def view_cash_balance(self):
        """
        Displays the current cash balance.
        """
        print(f"Cash Balance: ${self.cash_balance:,.2f}\n")

    def view_btc_balance(self):
        """
        Displays the current Bitcoin balance in USD.
        """
        price = get_current_btc_price()
        if price is None:
            print("Cannot fetch Bitcoin price at the moment.\n")
            return
        btc_usd_value = self.btc_balance * price
        print(f"Bitcoin Balance: ${btc_usd_value:,.2f} USD (Equivalent to {self.btc_balance:.6f} BTC at ${price:,.2f}/BTC)\n")

    def buy_btc(self):
        """
        Handles the buying of Bitcoin based on user input.
        """
        try:
            amount_usd = float(input("Enter USD amount to spend on buying Bitcoin: $"))
            if amount_usd <= 0:
                print("Amount must be greater than 0.\n")
                return
            if amount_usd > self.cash_balance:
                print("Insufficient cash balance.\n")
                return
            price = get_current_btc_price()
            if price is None:
                print("Cannot fetch Bitcoin price at the moment.\n")
                return
            btc_bought = amount_usd / price
            self.cash_balance -= amount_usd
            self.btc_balance += btc_bought
            print(f"Bought {btc_bought:.6f} BTC at ${price:,.2f} per BTC for ${amount_usd:,.2f}.\n")
            self.record_transaction('buy', amount_usd, btc_bought, price)
            self.save_data()
        except ValueError:
            print("Invalid input. Please enter a numerical value.\n")

    def sell_btc(self):
        """
        Handles the selling of Bitcoin based on user input, with sub-options.
        """
        if self.btc_balance == 0:
            print("No Bitcoin to sell.\n")
            return

        print("1. Sell All")
        print("2. Input Amount")
        sub_choice = input("Select an option (1-2): ").strip()
        print()  # For better readability

        if sub_choice == '1':
            # Sell All BTC
            price = get_current_btc_price()
            if price is None:
                print("Cannot fetch Bitcoin price at the moment.\n")
                return
            btc_to_sell = self.btc_balance
            amount_usd = btc_to_sell * price
            self.btc_balance = 0.0
            self.cash_balance += amount_usd
            print(f"Sold all {btc_to_sell:.6f} BTC at ${price:,.2f} per BTC for ${amount_usd:,.2f}.\n")
            self.record_transaction('sell', amount_usd, btc_to_sell, price)
            self.save_data()

        elif sub_choice == '2':
            # Input specific USD amount to sell
            try:
                amount_usd = float(input("Enter USD value of Bitcoin to sell: $"))
                if amount_usd <= 0:
                    print("Amount must be greater than 0.\n")
                    return
                price = get_current_btc_price()
                if price is None:
                    print("Cannot fetch Bitcoin price at the moment.\n")
                    return
                btc_to_sell = amount_usd / price
                if btc_to_sell > self.btc_balance:
                    print("Insufficient Bitcoin balance.\n")
                    return
                self.btc_balance -= btc_to_sell
                self.cash_balance += amount_usd
                print(f"Sold {btc_to_sell:.6f} BTC at ${price:,.2f} per BTC for ${amount_usd:,.2f}.\n")
                self.record_transaction('sell', amount_usd, btc_to_sell, price)
                self.save_data()
            except ValueError:
                print("Invalid input. Please enter a numerical value.\n")
        else:
            print("Invalid selection. Please choose 1 or 2.\n")

    def record_transaction(self, txn_type, amount_usd, btc_amount, price_per_btc):
        """
        Records a transaction in the transaction history.

        Args:
            txn_type (str): Type of transaction ('buy' or 'sell').
            amount_usd (float): Amount in USD.
            btc_amount (float): Amount in BTC.
            price_per_btc (float): Price per BTC at the time of transaction.
        """
        transaction = {
            'id': str(uuid.uuid4()),
            'type': txn_type,
            'amount_usd': amount_usd,
            'btc': btc_amount,
            'price_per_btc': price_per_btc,
            'timestamp': datetime.utcnow().isoformat() + 'Z'  # UTC time in ISO format
        }
        self.transaction_history.append(transaction)
        self.save_history()

    def view_total_pl(self):
        """
        Calculates and displays the total profit or loss.
        """
        current_price = get_current_btc_price()
        if current_price is None:
            print("Cannot fetch Bitcoin price at the moment.\n")
            return
        current_total = self.cash_balance + self.btc_balance * current_price
        pl = current_total - self.starting_total
        pl_percent = ((current_total - self.starting_total) / self.starting_total) * 100
        print(f"Current Bitcoin Price: ${current_price:,.2f}")
        print(f"Cash Balance: ${self.cash_balance:,.2f}")
        print(f"Bitcoin Balance: {self.btc_balance:.6f} BTC")
        print(f"Total Portfolio Value: ${current_total:,.2f}")
        print(f"Total P/L: ${pl:,.2f}")
        print(f"P/L Percent: {pl_percent:.2f}%\n")

    def view_transaction_history(self):
        """
        Displays the transaction history.
        """
        if not self.transaction_history:
            print("No transactions have been made yet.\n")
            return
        headers = ["Timestamp", "Type", "Amount (USD)", "Amount (BTC)", "Price per BTC (USD)"]
        table = []
        for txn in self.transaction_history:
            row = [
                txn['timestamp'],
                txn['type'].capitalize(),
                f"${txn['amount_usd']:,.2f}",
                f"{txn['btc']:.6f}",
                f"${txn['price_per_btc']:,.2f}"
            ]
            table.append(row)
        print("===== Transaction History =====")
        print(tabulate(table, headers=headers, tablefmt="pretty"))
        print("================================\n")

    def reset_trader(self):
        """
        Resets the trader's balances and transaction history after user confirmation.
        """
        confirm = input("Are you sure you want to reset all balances and transaction history? (y/n): ").strip().lower()
        if confirm == 'y':
            self.cash_balance = self.starting_cash
            self.btc_balance = 0.0
            self.transaction_history = []
            self.save_data()
            self.save_history()
            print("All balances and transaction history have been reset.\n")
        else:
            print("Reset cancelled.\n")

def display_menu():
    """
    Displays the main menu options.
    """
    print("===== Bitcoin Paper Trading Platform =====")
    print("1. View Cash Balance")
    print("2. View Bitcoin Balance")
    print("3. Buy Bitcoin")
    print("4. Sell Bitcoin")
    print("5. View Total P/L")
    print("6. View Transaction History")
    print("7. Reset Account")
    print("8. Exit")
    print("==========================================")

def clear_console():
    os.system('cls' if os.name == 'nt' else 'clear')

def signal_handler(sig, frame):
    """
    Handles keyboard interrupt signals to exit gracefully.
    """
    print("\nExiting the Paper Trading Platform. Goodbye!")
    if ws_app:
        ws_app.close()
    sys.exit(0)

def main():
    """
    Main function to run the paper trading platform.
    """
    global ws_app

    # Register the signal handler for graceful exit on Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    # Start the WebSocket in a separate thread
    ws_thread = threading.Thread(target=start_websocket, daemon=True)
    ws_thread.start()

    # Wait until the first price is received
    print("Connecting to Kraken WebSocket to receive live BTC prices...")
    while True:
        with price_lock:
            if latest_btc_price is not None:
                break
        time.sleep(0.1)
    print(f"Initial BTC Price: ${latest_btc_price:,.2f}\n")

    trader = BitcoinPaperTrader()

    while True:
        clear_console()
        display_menu()
        choice = input("Select an option (1-8): ").strip()
        print()  # For better readability

        if choice == '1':
            trader.view_cash_balance()
        elif choice == '2':
            trader.view_btc_balance()
        elif choice == '3':
            trader.buy_btc()
        elif choice == '4':
            trader.sell_btc()
        elif choice == '5':
            trader.view_total_pl()
        elif choice == '6':
            trader.view_transaction_history()
        elif choice == '7':
            trader.reset_trader()
        elif choice == '8':
            print("are ya winnin son!?")
            if ws_app:
                ws_app.close()
            sys.exit(0)
        else:
            print("Invalid selection. Please choose a number between 1 and 8.\n")
        
        input("Press Enter to continue...")  # Pause before clearing the console

if __name__ == "__main__":
    # Ensure that the websocket-client library is installed
    try:
        import websocket
    except ImportError:
        print("The 'websocket-client' library is required to run this script.")
        print("Install it using 'pip install websocket-client' and try again.")
        sys.exit(1)

    main()