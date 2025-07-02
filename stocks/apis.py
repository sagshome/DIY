import json
import logging
import numpy as np
import yfinance as yf

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.http import JsonResponse

from base.utils import normalize_date
from .models import Account, Equity, EquityValue, Transaction

logger = logging.getLogger(__name__)


@login_required
def get_action_list(request):
    account_id = request.GET.get("account_id")
    if account_id:
        account = Account.objects.get(id=account_id, user=request.user)

    value_map = {value:key for key, value in Transaction.TRANSACTION_TYPE}
    result = {}
    if account.account_type == 'Investment':
        my_set = ('Deposit', 'Withdraw', 'Buy',  'Sell', 'Reinvested Dividend', 'Dividends/Interest', 'Transferred Out')
    if account.account_type == 'Cash':
        my_set = ('Value',)
    if account.account_type == 'Value':
        my_set = ('Deposit', 'Withdraw', 'Buy', 'Sell', 'Value', 'Transfer Out')
    for item in my_set:
        result[value_map[item]] = item
    # return json
    return render(request, "generic_selection.html", {"values": result})


@login_required
def get_equity_list(request):
    """
    API to get the proper set of equities, the number of shares and the number base on the action, profile and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    """
    this_date = datetime.now()
    action = None
    values = Equity.objects.filter(equity_type='Equity')

    if request.GET.get("date"):
        try:
            this_date = datetime.strptime(request.GET.get("date"), '%Y-%m-%d')
        except ValueError:
            logger.error("Received a ill formed date %s" % request.GET.get("date"))
    values = values.exclude(deactivated_date__lt=this_date)

    if request.GET.get("action"):
        try:
            action = int(request.GET.get('action'))
        except ValueError:
            logger.error("Received a non-numeric action %s" % request.GET.get("action"))

    if request.GET.get("q"):
        query_filter = str(request.GET.get('q'))
        values = values.filter(Q(symbol__icontains=query_filter) | Q(name__icontains=query_filter))

    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES, Transaction.TRANS_OUT]:
        try:
            account = Account.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
            this_date = np.datetime64(normalize_date(this_date))
            subset = account.e_pd.loc[(account.e_pd['Date'] == this_date) & (account.e_pd['Shares'] > 0)]['Object_ID']
            values = values.filter(id__in=subset.values)
        except Account.DoesNotExist:
            logger.error('Someone %s is poking around, looking for %s' * (request.user, request.GET.get("portfolio_id")))
        except ValueError:
            pass  # No value supplied

    results = [{'id': e.id, 'text': e.key} for e in values.order_by('symbol')[:10]]
    value_dictionary = dict()
    for e in values.order_by('symbol'):
        value_dictionary[e.id] = e.key

    return JsonResponse({"results": results})
    # return render(request, "generic_selection.html", {"values": value_dictionary})


@login_required
def get_transaction_list(request):
    title = 'Account not found'
    xas = None
    if request.GET.get("account_id"):
        try:
            account = Account.objects.get(id=request.GET.get("account_id"), user=request.user)
            title = f'{account.name} (First 5)'
            xas = account.transactions.filter(xa_action__in=Transaction.MAJOR_TRANSACTIONS).order_by('real_date')[:5]
        except Account.DoesNotExist:
            pass
    return render(request, 'stocks/includes/transaction_list.html',{'hide_new_xa': True, 'table_title': title, 'xas': xas})


@login_required
def get_equity_values(request):
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

    try:
        account = Account.objects.get(id=request.GET.get('account_id'), user=request.user)
    except Account.DoesNotExist:
        logger.error("No account provided with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    try:
        action = int(request.GET.get('action'))
    except ValueError:
        logger.error("No action provided with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    try:
        equity = Equity.objects.get(id=request.GET.get('equity_id'))
    except Equity.DoesNotExist:
        logger.error("No equity provided with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    price = 0
    if equity.equity_type == 'Equity':
        try:
            price = EquityValue.objects.get(equity=equity, date=normalize_date(this_date)).price
        except:
            pass

    shares = 0
    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES, Transaction.TRANS_OUT]:
        this_date = np.datetime64(normalize_date(this_date))
        shares = account.e_pd.loc[(account.e_pd['Date'] == this_date) & (account.e_pd['Equity'] == equity.key)]['Shares'].item()

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
    this_date = normalize_date(this_date)

    try:
        account = Account.objects.get(id=request.GET.get('account_id'), user=request.user)
    except Account.DoesNotExist:
        logger.error("No account provided with ID %s is not found." % request.GET.get("account_id"))
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    return JsonResponse({'cash': account.get_pattr('Cash', query_date=this_date)})

@login_required
def search_equity(request):
    query = request.GET.get('q', '')
    source = request.GET.get('t', '')
    items = []
    if not source:
        source = 'Equity'
    if query and source == 'Equity':
        for item in yf.search.Search(query, max_results=10, news_count=0, timeout=1, raise_errors=False).quotes:
            if item['exchDisp'] in ['NASDAQ', 'NYSE', 'Toronto']:
                items.append({'symbol': item['symbol'], 'shortname': item['shortname']})
        return JsonResponse({'results': items}, safe=False)
    if source == 'Fund' or not items:
        pass


    return JsonResponse([], safe=False)


@login_required
def search_equity_add(request):
    symbol = request.GET.get('symbol', None)
    if symbol:
        items = yf.search.Search(symbol, max_results=1, news_count=0, timeout=1, raise_errors=False).quotes
        if items:  # Will be empty or 1
            symbol = items[0]['symbol']
            if not Equity.objects.filter(symbol=symbol).exists():
                region = 'Canada' if items[0]['exchDisp'] == 'Toronto' else 'US'
                currency = 'CAD' if items[0]['exchDisp'] == 'Toronto' else 'USD'
                equity = Equity(symbol=symbol, region=region, currency=currency, validated=False, equity_type='Equity', searchable=True)
                equity.save()
                equity.update()
    return JsonResponse([], safe=False)

