import json
import logging
import numpy as np
import pandas as pd
import yfinance as yf

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.http import JsonResponse, HttpResponse
from django.utils import timezone

# from base.utils import normalize_date
from .models import Account, Investment, Value, Transaction, Funding, CashFlow, ValueBalance
from .models import clear_caches
from .dataframes import WealthDF

logger = logging.getLogger(__name__)


@login_required
def delete_action(request):

    action_id = request.GET.get("action_id", None)
    action_type = request.GET.get("action_type", None)
    if action_id and action_type:
        action = Transaction.objects.none
        if action_type == 'XA':
            action = Transaction.objects.filter(id=action_id, account__user=request.user)
        elif action_type == 'FUND':
            action = Funding.objects.filter(id=action_id, account__user=request.user)
        elif action_type == 'CASH':
            action = CashFlow.objects.filter(id=action_id, account__user=request.user)
        elif action_type == 'VALUE':
            action = ValueBalance.objects.filter(id=action_id, account__user=request.user)
        if action.count() == 1:
            action.delete()
            if request.POST.get("refresh", True):
                clear_caches(user=request.user)
            return HttpResponse(status=200)
    return HttpResponse(status=404)

@login_required
def get_xa_action_list(request):
    """
    return a generic choice list of actions available to an account.  The choices will be in the format 'action': 'action'
    parameters:
        account_id
    """
    account_id = request.GET.get("account_id")
    if account_id:
        try:
            account = Account.objects.get(id=account_id, user=request.user)
        except Account.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    else:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    result = {}
    if account.acct_type == 'Trading' and not account.managed:
        my_set = ('Deposit', 'Withdraw', 'Buy',  'Sell', 'Reinvested Dividend', 'Dividends/Interest',)
    elif account.acct_type == 'Trading':
        my_set = ('Deposit', 'Withdraw', 'Buy',  'Sell', 'Reinvested Dividend', 'Dividends/Interest')
    elif account.acct_type == 'Cash':
        my_set = ('Balance',)
    elif account.acct_type == 'Value':
        my_set = ('Deposit', 'Withdraw', 'Balance')

    for item in my_set:
        result[item] = item
    # return json
    return render(request, "generic_selection.html", {"values": result})


@login_required
def get_equity_list(request):
    """
    API to get the proper set of equities, held or available by the account on a specific date base on action='Buy' or 'Sell'.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    parameters:

        scope: str default = month - Values month or day
        account_id: int - pk of the account record
        investment: str - symbol of the investment
    """
    try:
        this_date = pd.to_datetime(request.GET.get("date"), utc=True) if 'date' in request else pd.to_datetime("now", utc=True).normalize()
    except:  # DateParseError: should be excplicit
        logger.error("Received a ill formed date %s" % request.GET.get("date"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if 'action' in request.GET and request.GET.get('action') == 'SELL':  # limit list to what was owned on this date
        scope = request.GET.get('scope') if 'scope' in request else 'month'
        if scope == 'month':
            this_date = this_date.replace(day=1)  # Set to month start for month scope
        try:
            account = Account.objects.get(id=request.GET.get('account_id'), user=request.user)
        except Account.DoesNotExist:
            logger.error("No account provided with ID %s is not found." % request.GET.get("account_id"))
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
        df = WealthDF(user=request.user, scope=scope).df
        df = WealthDF.on_datetime(df, this_date)
        values = Investment.objects.filter(symbol__in=df.loc[(df['InvType'] == 'Trading') & (df['AccountID'] == account.pk) ]['Symbol'].tolist())
    else:
        values = Investment.objects.filter(inv_type='Trading').exclude(deactivated_date__lt=this_date)

    if request.GET.get("q"):
        query_filter = str(request.GET.get('q'))
        values = values.filter(Q(symbol__icontains=query_filter) | Q(name__icontains=query_filter))

    results = [{'id': e.symbol, 'text': f'{e.symbol} - {e.name}'} for e in values.order_by('symbol')[:10]]
    return JsonResponse({"results": results})
    # return render(request, "generic_selection.html", {"values": value_dictionary})


@login_required
def get_transaction_list(request):
    """
    return a table of transactions for an account.
    parameters:
        account_id: int
    """
    title = 'Does Not Exist'
    xas = None
    if request.GET.get("account_id"):
        try:
            account = Account.objects.get(id=request.GET.get("account_id"), user=request.user)
            title = f'{account.name} (First 5)'
            xas = account.transaction_set.order_by('date')[:5]
        except Account.DoesNotExist:
            pass
    return render(request, 'stocks/includes/wealth_transaction_list.html',{'hide_new_xa': True, 'table_title': title, 'xas': xas})


@login_required
def get_equity_values(request):
    """
    API to get the proper set of equities base on the action, account, investment and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    API parameters
    scope: str default = month - Values month or day
    account_id: int -   pk of the account record
    investment: str - symbol of the investment
    action:
    """

    investment = request.GET.get('equity_id', None)
    this_date = request.GET.get('date', None)
    price = shares = None

    if this_date:
        try:
            this_date = pd.to_datetime(this_date).normalize()
        except:
            logger.error('Malformed date %s', this_date)
            this_date = None

        try:
            price = Value.objects.filter(investment=investment, date__lte=this_date).latest('date').close_value
        except Value.DoesNotExist:
            price = None

    if investment and this_date:
        action = request.GET.get('action', None)
        if action == 'SELL':
            try:
                investment = Investment.objects.get(pk=investment)
                df = WealthDF(user=request.user, scope='month').df
                this_date = this_date.replace(day=1)
                shares = df.loc[(df['Date'] == this_date) & (df['Symbol'] == investment.symbol)]['Quantity'].item()
            except Investment.DoesNotExist:
                shares = None
        else:
            shares = None
    return JsonResponse({'shares': shares, 'price': price})


@login_required
def get_cash_value(request):
    """
    API to get the proper set of equities base on the action, profile and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    """

    try:
        this_date = datetime.strptime(request.GET.get("date"), '%Y-%m-%d')
    except ValueError:
        logger.error("Received a ill formed date %s" % request.GET.get("date"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    except TypeError:
        logger.error("Received a ill formed date %s" % request.GET.get("date"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    this_date = this_date

    try:
        account = Account.objects.get(id=request.GET.get('account_id'), user=request.user)
    except Account.DoesNotExist:
        logger.error("No account provided with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    return JsonResponse({'cash': account.get_pattr('Cash', query_date=this_date)})


@login_required
def search_equity(request):
    query = request.GET.get('q', '')
    if query:
        items = []
        data = yf.Ticker(query).info  # Try the direct hit first
        if 'symbol' in data and 'shortName' in data:
            items.append({'symbol': data['symbol'], 'shortName': data['shortName']})
        else:  # try the common exchanges,  it will always after it finds something in NYSE,  then NASDAQ,   Toronto is an afterthought thus,  the hit if...
            for item in yf.search.Search(query, max_results=10, news_count=0, timeout=1, raise_errors=False).quotes:
                if item['exchDisp'] in ['NASDAQ', 'NYSE', 'Toronto']:
                    items.append({'symbol': item['symbol'], 'shortname': item['shortname']})
        return JsonResponse({'results': items}, safe=False)
    return JsonResponse([], safe=False)


@login_required
def search_equity_add(request):
    symbol = request.GET.get('symbol', None)
    if symbol:
        items = yf.search.Search(symbol, max_results=1, news_count=0, timeout=1, raise_errors=False).quotes
        if items:  # Will be empty or 1
            symbol = items[0]['symbol']
            if not Investment.objects.filter(symbol=symbol).exists():
                region = 'Canada' if items[0]['exchDisp'] == 'Toronto' else 'US'
                currency = 'CAD' if items[0]['exchDisp'] == 'Toronto' else 'USD'
                equity = Investment(symbol=symbol, country=region, currency=currency, validated=False, inv_type='Trading', searchable=True)
                equity.save()
                equity.daily_update()
            else:
                logger.info('Trying to readd symbol %s' % symbol)
    return JsonResponse([], safe=False)

