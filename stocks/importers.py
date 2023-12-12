import csv

from datetime import datetime, date
from typing import List, Dict

from .models import Equity, EquityAlias, Portfolio, EquityValue, EquityEvent, Transaction
from .utils import next_date, normalize_date

equities: Dict[str, Equity] = {}
portfolios: Dict[str, Portfolio] = {}


def equity_lookup(symbol: str, name: str):
    if symbol in equities:
        return equities[symbol]
    value = EquityAlias.find_equity(name)
    if value:
        equities[symbol] = value
        return equities[symbol]
    raise Exception(f'Failed to lookup {symbol} - {name}')


def get_or_create_equity(symbol: str, name: str, currency: str, managed: bool):
    '''
    Given a symbol,  and a descriptive name - do your best to lookup and / or create a new equity
    :param symbol:  The basic for the search
    :param name:  The text description
    :param currency: Used to pick region and possible symbol decorations
    :param managed:  Used to determine MoneyMarket vs MutualFund for managed accounts
    :return:
    '''

    if symbol not in equities:  # Not yet cached
        try:
            equity = Equity.objects.get(symbol=symbol)
        except Equity.DoesNotExist:
            searchable = False
            region = 'TRT' if currency == 'CAD' else ""
            if name.find(' ETF') != -1:
                equity_type = 'ETF'
                searchable = True
            elif not managed:
                equity_type = 'Equity'
                searchable = True
            elif name.find('%') != -1 or name.find('SAVINGS') != -1:
                equity_type = 'MM'
            else:
                equity_type = 'MF'
            equity = Equity(symbol=symbol, name=name, searchable=searchable, equity_type=equity_type,
                            currency=currency, region=region)
            equity.save(update=False)

        if not EquityAlias.objects.filter(symbol=symbol, name=name).exists():
            EquityAlias.objects.create(symbol=symbol, name=name, equity=equity)
        equities[symbol] = equity
    return equities[symbol]


def get_or_create_portfolio(portfolio, managed):
    if portfolio not in portfolios:
        p, created = Portfolio.objects.get_or_create(name=portfolio, managed=managed)
        portfolios[portfolio] = p
    return portfolios[portfolio]


def fill_value_holes():
    """
    Inporting based on transactions leaves a lot of holes in price data.    This function will fill those holes
    with estimated data based on price changes between data points.

    :return:
    """
    for equity in Equity.objects.all():
        print(f'Checking {equity} for holes')
        equity.fill_equity_holes()


def manulife(file_name):
    """
    Downloaded my transactions from manulife and looking to import them
    :param file_name:
    :return:
    """
    with open(file_name) as csv_file:
        csv_reader = csv.reader(csv_file)
        header = next(csv_reader)
        column_indices = {
            'Portfolio': header.index('Account'),
            'Name': header.index('Investment Name'),
            'Symbol': header.index('Symbol'),
            'XAType': header.index('Transaction Type'),
            'Currency': header.index('Currency'),
            'Quantity': header.index('Unit Quantity'),
            'Price': header.index('Price'),
            'Cost': header.index('Net Amount'),
            'Date': header.index('Posted Date')
        }

        for row in csv_reader:
            portfolio = get_or_create_portfolio(row[column_indices['Portfolio']], managed=True)
            equity = get_or_create_equity(row[column_indices['Symbol']],
                                          row[column_indices['Name']],
                                          row[column_indices['Currency']],
                                          True)
            this_date = normalize_date(datetime.strptime(row[column_indices['Date']], '%Y-%m-%d'))
            price = float(row[column_indices['Price']])
            quantity = float(row[column_indices['Quantity']])
            xa_type = row[column_indices['XAType']]
            cost = row[column_indices['Cost']]

            if xa_type == 'Cash Dividend/Interest' or xa_type == 'Fee Rebate':
                pass  # This will be reinvested or redeemed later
            else:
                xa_price = price
                if xa_type == 'Transfer In - External' or xa_type == 'Purchase' or xa_type == 'Switch In':
                    buy_action = 'buy'
                    drip = False
                elif xa_type == 'Reinvested Dividend/Interest':
                    if equity.equity_type == 'MM':
                        drip = False
                        buy_action = 'int'
                    elif equity.equity_type == 'MF':
                        drip = True
                        buy_action = 'div'
                    xa_price = 0  # Since we did not really pay for this.
                elif xa_type == 'Redemption' or xa_type == 'Switch Out':
                    buy_action = 'sell'
                    drip = False
                    quantity = quantity * -1
                else:
                    raise Exception(f'Unknown XA Type:{xa_type}')

                if not Transaction.objects.filter(portfolio=portfolio, equity=equity, date=this_date, xa_action=buy_action,
                                                  drip=drip, price=xa_price, quantity=quantity).exists():

                    Transaction.objects.create(portfolio=portfolio, equity=equity, date=this_date, xa_action=buy_action,
                                               drip=drip, price=xa_price, quantity=quantity)
                else:
                    print(f'Warning - duplicate transaction: {portfolio}, {equity}, {date}')

                if not EquityValue.objects.filter(equity=equity, date=this_date).exists():
                    EquityValue.objects.create(equity=equity, date=this_date, price=price, )

        fill_value_holes()


def questtrade(file_name: str, portfolio_stub: str):
    """
    Downloaded my transactions from Questtrade to import them
    Notes,
        1. questrade does not report dividend amount just net value.  Must track quantities and divided by net.
        2. wanky things will happen,  make sure you sort your CSV file by date.
        3. Dividend may include stock split - CM


    :param file_name:   The file to import
    :param portfolio_stub:  A stub for the portfolio name
    :return:
    """
    with open(file_name) as csv_file:
        csv_reader = csv.reader(csv_file)
        header = next(csv_reader)
        column_indices = {
            'AccType': header.index('Account Type'),
            'Name': header.index('Description'),
            'Symbol': header.index('Symbol'),
            'XAType': header.index('Activity Type'),
            'Currency': header.index('Currency'),
            'Quantity': header.index('Quantity'),
            'Price': header.index('Price'),
            'Net': header.index('Net Amount'),
            'Cost': header.index('Commission'),
            'Date': header.index('Settlement Date')
        }
        equity_totals = {}
        cash_totals = {}
        for row in csv_reader:
            portfolio = get_or_create_portfolio(f'{portfolio_stub}-{row[column_indices["AccType"]]}', False)
            if not portfolio.name in equity_totals:
                equity_totals[portfolio.name] = {}
                cash_totals[portfolio.name] = {'CAD': 0, 'USD': 0}

            name = row[column_indices['Name']]
            symbol = row[column_indices['Symbol']]
            xa_date = normalize_date(datetime.strptime(row[column_indices['Date']], '%Y-%m-%d %H:%M:%S %p'))
            price = float(row[column_indices['Price']])
            quantity = float(row[column_indices['Quantity']])
            net = float(row[column_indices['Net']])
            cost = float(row[column_indices['Cost']])
            xa_type = row[column_indices['XAType']]
            currency = row[column_indices['Currency']]

            equity: Equity
            if xa_type in ('Deposits', 'Transfers', 'Fees and rebates', 'Withdrawals', 'Other', 'FX conversion'):
                cash_totals[portfolio.name][currency] += net
            else:
                if xa_type == 'Trades':
                    if symbol.endswith('.TO'):
                        symbol = symbol[0:len(symbol) - 3] + '.TRT'
                    equity = get_or_create_equity(symbol, name, currency, False)
                else:
                    equity = equity_lookup(symbol, name)

                if not equity:
                    raise Exception(f'Could not create/lookup equity {symbol} - {name}')

                if xa_type == 'Trades':
                    if equity.key not in equity_totals[portfolio.name]:
                        equity_totals[portfolio.name][equity.key] = 0  # First purchase
                    cash_totals[portfolio.name][currency] += net
                    cash_totals[portfolio.name][currency] += cost
                    equity_totals[portfolio.name][equity.key] += quantity
                    if quantity > 0:
                        trans_type = 'buy'
                    if quantity < 0:
                        trans_type = 'sell'
                        quantity *= -1
                    xa_price = (price * quantity + cost * -1) / quantity
                    if not EquityValue.objects.filter(equity=equity, date=xa_date).exists():
                        EquityValue.objects.create(equity=equity, date=xa_date, price=price)

                    if not Transaction.objects.filter(portfolio=portfolio, equity=equity, date=xa_date,
                                                      xa_action=trans_type,
                                                      price=xa_price, quantity=quantity).exists():
                        Transaction.objects.create(portfolio=portfolio, equity=equity, date=xa_date,
                                                   xa_action=trans_type,
                                                   price=xa_price, quantity=quantity)

                elif xa_type == 'Dividends':
                    value = net / equity_totals[portfolio.name][equity.key]
                    if not EquityEvent.objects.filter(equity=equity, date=xa_date, event_type='Dividend').exists():
                        EquityEvent.objects.create(equity=equity, date=xa_date, value=value,
                                                   event_type='Dividend', event_source='upload')
                    cash_totals[portfolio.name][currency] += net

                    '''if not Transaction.objects.filter(portfolio=portfolio, equity=equity, date=xa_date,
                                                      xa_action=trans_type,
                                                      price=xa_price, quantity=quantity).exists():
                        Transaction.objects.create(portfolio=portfolio, equity=equity, date=xa_date,
                                                   xa_action=trans_type,
                                                   price=xa_price, quantity=quantity)
                                                                   else:
                    print(f'Warning - duplicate transaction: {portfolio}, {equity}, {xa_date}')
'''

                else:
                    raise Exception(f'Unexpected Activity type {xa_type}')
            print(cash_totals, equity_totals)
        fill_value_holes()
