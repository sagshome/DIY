import logging
import pandas as pd

from dateutil.relativedelta import relativedelta


from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .models import Account, Equity, EquityEvent, EquityValue, Portfolio, ACCOUNT_COL
from base.utils import normalize_today, DateUtil
from base.models import COLORS, PALETTE

logger = logging.getLogger(__name__)


@login_required
def compare_equity_chart(request):

    try:
        account = Account.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
        compare_to = Equity.objects.get(id=request.GET.get("compare_id"))
        equity = Equity.objects.get(id=request.GET.get("equity_id"))
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = account.transactions.filter(equity=equity) if equity else account.transactions
    xas = xas.order_by('date')  # just to be safe
    xa_list = list(xas.values_list('date', flat=True))

    first_date = xas.first().date
    last_date = normalize_today()

    ct_div_dict = dict(EquityEvent.objects.filter(equity=compare_to, event_type='Dividend', date__gte=first_date).values_list('date', 'value'))
    e_div_dict = dict(EquityEvent.objects.filter(equity=equity, event_type='Dividend', date__gte=first_date).values_list('date', 'value'))
    ct_value_dict = dict(EquityValue.objects.filter(equity=compare_to, date__gte=first_date).values_list('date', 'price'))
    e_value_dict = dict(EquityValue.objects.filter(equity=equity, date__gte=first_date).values_list('date', 'price'))

    months = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta(months=1)

    cost = ct_shares = e_shares = ct_div = e_div = 0
    cost_list = []
    ct_value_list = []
    ct_div_list = []
    e_value_list = []
    e_div_list = []

    for this_date in months:
        if this_date in xa_list:
            result = xas.filter(date=this_date).aggregate(Sum('quantity'), Avg('price'))
            amount = result['quantity__sum']
            price = result['price__avg']
            cost += amount * price
            e_shares += amount
            ct_shares += (amount * price) / ct_value_dict[this_date]
        cost_list.append(cost)
        ct_value_list.append(ct_shares * ct_value_dict[this_date])
        e_value_list.append(e_shares * e_value_dict[this_date])
        if this_date in ct_div_dict:
            ct_div += ct_shares * ct_div_dict[this_date]
        ct_div_list.append(ct_div)
        if this_date in e_div_dict:
            e_div += e_shares * e_div_dict[this_date]
        e_div_list.append(e_div)

    colors = COLORS.copy()
    ci = 0
    chart_data = {'labels': sorted(months), 'datasets': []}
    chart_data['datasets'].append({'label': 'Cost', 'type': 'line', 'fill': False, 'data': cost_list, 'borderColor': colors[0],
                                   'backgroundColor': colors[0]})
    chart_data['datasets'].append({'label': f'{{Equity}} Value', 'type': 'line', 'fill': False, 'data': e_value_list, 'borderColor': colors[1],
                                   'backgroundColor': colors[1]})
    chart_data['datasets'].append({'label': f'{{Equity}} Dividends', 'type': 'line', 'fill': False, 'data': e_div_list, 'borderColor': colors[2],
                                   'backgroundColor': colors[2]})
    chart_data['datasets'].append({'label': f'{{compare_to}} Value', 'type': 'line', 'fill': False, 'data': ct_value_list, 'borderColor': colors[3],
                                   'backgroundColor': colors[3]})
    chart_data['datasets'].append({'label': f'{{compare_to}} Dividends', 'type': 'line', 'fill': False, 'data': ct_div_list, 'borderColor': colors[4],
                                   'backgroundColor': colors[4]})

    return JsonResponse(chart_data)


@login_required
def cost_value_chart(request):
    """
    The cost value chart is displayed with accounts,  portfolio and equities
    """

    colors = COLORS.copy()
    chart_data = {'labels': None,
                  'datasets': []}

    object_id = request.GET.get('object_id')
    object_type = request.GET.get("object_type")
    equity_id = request.GET.get("symbol")

    df = my_object = None
    if object_type == 'Portfolio':
        try:
            my_object = Portfolio.objects.get(id=object_id, user=request.user)
        except Portfolio.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)
    else:
        try:
            my_object = Account.objects.get(id=object_id, user=request.user)
        except Account.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if equity_id:
        try:
            equity = Equity.objects.get(id=equity_id)
        except Equity.DoesNotExist:
            return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

        df = my_object.equity_dataframe(equity)
        label1 = 'Cost'
    else:  # Portfolio or Account
        df = my_object.p_pd
        de = my_object.e_pd.groupby('Date', as_index=False).sum('Value')
        if len(de) == 0:
            df['Value'] = df['Funds']
        else:
            try:
                df = df.merge(de, on='Date', how='outer')
            except ValueError:   # No data it would appear
                return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

        df['Cost'] = df['Funds'] - df['Redeemed']
        if my_object.end:
            df = df.loc[df['Date'] <= pd.to_datetime(my_object.end)]
        df.fillna(0, inplace=True)
        label1 = 'Funding'

    if df.empty:
        chart_data = {}
    else:
        df.sort_values(by='Date', ascending=True, inplace=True)
        df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%b')

        chart_data['labels'] = df['Date'].to_list()
        chart_data['datasets'].append({'label': label1, 'fill': False, 'data': df['Cost'].tolist(), 'borderColor': PALETTE['cost'], 'backgroundColor': PALETTE['cost'], 'tension': 0.1})
        chart_data['datasets'].append({'label': 'Value', 'fill': False,'data': df['Value'].tolist(),'borderColor': PALETTE['value'], 'backgroundColor': PALETTE['value']})
        if equity_id:
            chart_data['datasets'].append(
                {'label': 'Value w/ Dividends', 'fill': False, 'data': df['AdjValue'].tolist(), 'borderColor': PALETTE['dividends'], 'backgroundColor': PALETTE['dividends']})

    return JsonResponse(chart_data)


@login_required
def acc_summary(request):
    '''
    Three modes,  1) Portfolio,  2) Account,  3) Everything
    '''
    colors = COLORS.copy()
    ci = 0

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')
    this = None
    if object_type:
        if object_type == 'Account':
            accounts = Account.objects.filter(user=user, id=object_id)
            this = Account.objects.get(id=object_id)
        else:
            this = Portfolio.objects.get(id=object_id)
            accounts = Account.objects.filter(user=user, portfolio_id=object_id)
    else:
        accounts = Account.objects.filter(user=user)

    if accounts.exists():
        try:
            start = accounts.filter(_start__isnull=False).earliest('_start')._start.strftime('%Y-%m-%d')
            if accounts.filter(_end__isnull=True).exists():
                end = normalize_today().strftime('%Y-%m-%d')
            else:
                end = accounts.latest('_end')._end.strftime('%Y-%m-%d')
        except Account.DoesNotExist:
            return JsonResponse({'labels': [], 'datasets': []})
    else:
        return JsonResponse({'labels': [], 'datasets': []})

    if not object_type:  # This is a 'Everything' - so remove accounts with a portfolio
        accounts = accounts.exclude(portfolio__isnull=False)

    date_range = pd.date_range(start=start, end=end, freq='MS')
    month_df = pd.DataFrame({'Date': date_range, 'Value': 0})

    labels = [this_date.strftime('%Y-%b') for this_date in month_df['Date'].to_list()]
    df = pd.DataFrame(columns=ACCOUNT_COL)
    datasets = []
    for account in accounts:
        color = colors[ci]
        ci += 1
        datasets.append({
            'label': account.name,
            'fill': False,
            'data': pd.concat([month_df, account.e_pd.loc[:, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
            'boarderColor': color, 'backgroundColor': color,
            'stack': 1,
            'order': 1,
        })
        df = pd.concat([df, account.p_pd]).groupby('Date', as_index=False).sum()

    if not object_type:  # This is a 'Everything' - process portfolios a portfolio
        for portfolio in Portfolio.objects.filter(user=user):
            color = colors[ci]
            ci += 1

            datasets.append({
                'label': portfolio.name,
                'fill': False,
                'data': pd.concat([month_df,  portfolio.e_pd.loc[:, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
                'boarderColor': color,  'backgroundColor': color,
                'stack': 1,
                'order': 1,
            })
            df = pd.concat([df, portfolio.p_pd]).groupby('Date', as_index=False).sum()
    else:
        datasets.append({
            'label': 'Cash',
            'fill': False,
            'data': pd.concat([month_df, this.p_pd.loc[:, ['Date', 'Cash']]]).groupby('Date')['Cash'].sum().to_list(),
            'boarderColor': PALETTE['green'], 'backgroundColor': PALETTE['green'],
            'stack': 1,
            'order': 1,
        })

    if object_type == 'Account':
        df['Cost'] = df['Funds'] + df['TransIn'] + df['Redeemed'] + df['TransOut']
    else:
        df['Cost'] = df['Funds'] + df['Redeemed']

    datasets.append({
        'label': 'Cost',
        'fill': False,
        'data': df['Cost'].to_list(),
        'boarderColor': '#000000', 'backgroundColor': '#000000',
        'type': 'line',
        'order': 0,
    })

    return JsonResponse({'labels': labels, 'datasets': datasets})


@login_required
def equity_summary(request):
    colors = COLORS.copy()
    ci = 0

    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')

    if not (object_id and object_type):
        return JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    if object_type == 'Account':
        this = get_object_or_404(Account, id=object_id, user=request.user)
    else:
        this = get_object_or_404(Portfolio, id=object_id, user=request.user)

    this_pd = this.p_pd
    this_ed = this.e_pd

    start = this.start
    end = this.end if this.end else normalize_today()
    if not (start and end):
        return JsonResponse({'status': 'false', 'message': 'Invalid Data'}, status=500)

    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')

    date_range = pd.date_range(start=start, end=end, freq='MS')
    month_df = pd.DataFrame({'Date': date_range, 'Value': 0})

    labels = [this_date.strftime('%Y-%b') for this_date in month_df['Date'].to_list()]
    datasets = []
    datasets.append({
        'label': 'Cash',
        'fill': False,
        'data': this_pd['Cash'].to_list(),
        'boarderColor': PALETTE['green'], 'backgroundColor': PALETTE['green'],
        'stack': 1,
        'order': 1,
    })
    ci = 0
    for equity in this.equities:
        color = colors[ci]
        ci += 1
        label = equity.symbol if equity.equity_type == 'Equity' else equity.equity_type
        datasets.append({
            'label': label,
            'fill': False,
            'data': pd.concat([month_df, this_ed.loc[this_ed['Object_ID'] == equity.id, ['Date', 'Value']]]).groupby('Date')['Value'].sum().to_list(),
            'boarderColor': color, 'backgroundColor': color,
            'stack': 1,
            'order': 1,
        })

    # Redeemed and TransOut are negative numbers so add them to subtract them.
    if object_type == 'Account':
        cost_df = this_pd['Funds'] + this_pd['TransIn'] + this_pd['Redeemed'] + this_pd['TransOut']
    else:
        cost_df = this_pd['Funds'] + this_pd['Redeemed']

    datasets.append({
        'label': 'Cost',
        'fill': False,
        'data': cost_df.to_list(),
        'boarderColor': '#000000', 'backgroundColor': '#000000',
        'type': 'line',
        'order': 0,
    })

    return JsonResponse({'labels': labels, 'datasets': datasets})


@login_required
def wealth_summary_chart(request):
    """
    Build the chart data required for the timespan with the following data
    1.  Cost
    2.  CPI Cost
    3.  Value
    4.  Dividends
    5.  Comparison Value
    """

    user = request.user
    date_util = DateUtil(period=request.GET.get('period'), span=request.GET.get('span'))
    dates = date_util.dates({'cost': 0, 'cpi_cost': 0, 'value': 0, 'dividends': 0, 'comp_value': 0})

    accounts = Account.objects.filter(user=user)
    for account in accounts:
        logger.debug('Processing %s:%s' % (account.id, account))
        for key in dates.keys():
            logger.debug('Processing date %s' % key)
            this_cost = account.get_pattr('Funds', key) - account.get_pattr('Redeemed', key)
            this_value = account.get_eattr('Value', key)
            dates[key]['cost'] += this_cost
            dates[key]['value'] += this_value

    # Lets get the data back to lists
    labels = []
    cost = []
    value = []
    for key in dates.keys():
        labels.append(date_util.date_to_label(key))
        cost.append(dates[key]['cost'])
        value.append(dates[key]['value'])

    chart_data = {'labels': labels,
                  'datasets': [
                      {'label': 'Cost', 'fill': False, 'data': cost, 'boarderColor': PALETTE['coral'],  'backgroundColor': PALETTE['coral'], 'tension': 0.1},
                      {'label': 'Value', 'fill': False, 'data': value, 'boarderColor': PALETTE['olive'],  'backgroundColor': PALETTE['olive']}
                  ]
                  }

    return JsonResponse(chart_data)


@login_required
def wealth_summary_pie(request):
    '''
    A quick pie chart - launched at login time
    '''
    data = []
    labels = []
    option_links = []
    for account in Account.objects.filter(user=request.user, portfolio__isnull=True, _end__isnull=True):
        value = account.value if account.value and account.value > 0 else 0
        data.append(value)
        option_links.append(reverse('account_details', kwargs={'pk': account.id}))
        labels.append(account.name)
    for portfolio in Portfolio.objects.filter(user=request.user):
        value = portfolio.value if portfolio.value and portfolio.value > 0 else 0
        data.append(value)
        option_links.append(reverse('portfolio_details', kwargs={'pk': portfolio.id}))
        labels.append(portfolio.name)
    return JsonResponse({'data': data, 'labels': labels, 'options_links': option_links, 'colors': COLORS})


@login_required
def account_equity_compare(request, pk, orig_id, compare_id):
    try:
        account = Account.objects.get(id=pk, user=request.user)
        compare_to = Equity.objects.get(id=compare_id)
        equity = Equity.objects.get(id=orig_id)
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = account.transactions.filter(equity=equity) if equity else account.transactions
    xas = xas.order_by('date')  # just to be safe
    xa_list = list(xas.values_list('date', flat=True))

    first_date = xas.first().date
    last_date = normalize_today()

    ct_div_dict = compare_to.event_dict()
    e_div_dict = equity.event_dict()

    ct_value_dict = compare_to.value_dict()
    e_value_dict = equity.value_dict()

    months = []
    month_dict = {}
    next_date = first_date
    while next_date <= last_date:
        months.append(next_date)
        month_dict[next_date] = len(months) - 1
        next_date = next_date + relativedelta(months=1)

    cost = ct_shares = e_shares = ct_div = e_div = 0
    cost_list = []
    ct_value_list = []
    ct_div_list = []
    e_value_list = []
    e_div_list = []

    for this_date in months:
        if this_date in xa_list:
            result = xas.filter(date=this_date).aggregate(Sum('quantity'), Avg('price'))
            amount = result['quantity__sum']
            price = result['price__avg']
            cost += amount * price
            e_shares += amount
            ct_shares += (amount * price) / ct_value_dict[this_date]
        cost_list.append(cost)
        if e_shares:
            if this_date in ct_value_dict:
                ct_value_list.append(ct_shares * ct_value_dict[this_date])
            if this_date in e_value_dict:
                e_value_list.append(e_shares * e_value_dict[this_date])
            if this_date in ct_div_dict:
                ct_div += ct_shares * ct_div_dict[this_date]
            ct_div_list.append(ct_div)
            if this_date in e_div_dict:
                e_div += e_shares * e_div_dict[this_date]
            e_div_list.append(e_div)

    colors = COLORS.copy()
    ci = 0
    chart_data = {'labels': sorted(months), 'datasets': []}
    chart_data['datasets'].append({'label': 'Cost', 'type': 'line', 'fill': False, 'data': cost_list, 'borderColor': colors[0],
                                   'backgroundColor': colors[0]})
    chart_data['datasets'].append({'label': f'{equity.symbol} Value', 'type': 'line', 'fill': False, 'data': e_value_list, 'borderColor': colors[1],
                                   'backgroundColor': colors[1]})
    chart_data['datasets'].append({'label': f'{equity.symbol} Dividends', 'type': 'line', 'fill': False, 'data': e_div_list, 'borderColor': colors[2],
                                   'backgroundColor': colors[2]})
    chart_data['datasets'].append({'label': f'{compare_to.symbol} Value', 'type': 'line', 'fill': False, 'data': ct_value_list, 'borderColor': colors[3],
                                   'backgroundColor': colors[3]})
    chart_data['datasets'].append({'label': f'{compare_to.symbol} Dividends', 'type': 'line', 'fill': False, 'data': ct_div_list, 'borderColor': colors[4],
                                   'backgroundColor': colors[4]})

    return JsonResponse(chart_data)
