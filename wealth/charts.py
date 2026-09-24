import logging
import numpy as np
import pandas as pd

from dateutil.relativedelta import relativedelta


from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .models import Account, Investment, Dividend, Value, Portfolio
from .dataframes import WealthDF
from base.ioom_dates import IOOMDates
from base.models import COLORS, PALETTE, Inflation

logger = logging.getLogger(__name__)

@login_required
def generic_wealth_data(request):
    '''
    object_type + object_id produces a chart based on Portfolio or Account,
        blank = Portfolios and orphan Accounts
    date_range for the length of time to chart out
        default = year
    equity - An equity held in the account or portfolio,
        blank just show totals

    scope day for an item for each day,  month for each month
        blank is select vs date_range
    options:
        growth - Show the value change over the time
        dividend - Show the total dividends over time
        funding - Include a row for funding
        inflation - show the value of
        equities - show the values as stacked lines

    compare
        add an equity item to compare to.   This will change value to a

    '''

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')
    date_range = request.GET.get('range', 'year')
    object_id = int(object_id) if object_id else object_id
    options = request.GET.getlist('options[]')
    compare = request.GET.get('compare')
    scope = request.GET.get('scope')

    # scope only make sense when you want day data for a period longer then 1 year So picking a scope of month
    # and a range of 1 year will produce strange results.
    if scope:
        dfo = WealthDF(user, scope=scope)  # Get the DF based on scope - will force by_day or by_month
    else:
        dfo = WealthDF(user, date_range=date_range)  # Calculate the DF based on default scope for range

    df = dfo.by_range(date_range)                # Limit dataframe to start date of the selected range (regardless of scope

    # Step 1 - trim the data
    if object_type and object_type == 'Account':
        df = df.loc[df['AccountID'] == object_id]     # Limit dataframe only items matching this account
    elif object_type and object_type == 'Portfolio':  # Limit dataframe to only items matching this portfolio
        df = df.loc[df['PortfolioID'] == object_id]   # expand using AccountID
    # else we are working with all the data
    
    if df.empty:
        return JsonResponse({'labels': [], 'datasets': []})

    ldf = dfo.dated_summary_df(df)

    if 'dividends' in options and 'DivTotal' in df.columns:
        ldf = ldf.merge(df[['Date', 'DivTotal']], on='Date', how='left')

    if 'inflation' in options:
        ldf = ldf.merge(Inflation.as_dataframe(ldf, scope=dfo.scope), on='Date', how='left')
        # ------------------------------------------------------------
        # Funding
        # ------------------------------------------------------------

        # Change in cumulative funding from the previous month.
        # Positive = money added
        # Negative = money withdrawn
        ldf['NewFunding'] = ldf['Funding'].diff()

        # Inflation rate for each month
        ldf['Inflation'] = ldf['CPICost'].pct_change()

        # ------------------------------------------------------------
        # Inflation-adjusted funding
        # ------------------------------------------------------------

        # Convert each month's funding change into CPI units.
        #
        # Example:
        #   $10,000 deposited when CPI = 160
        #   10,000 / 160 = 62.5 CPI units
        #
        # Withdrawals are automatically negative.
        ldf['FundingCPIUnits'] = ldf['NewFunding'] / ldf['CPICost']

        # Accumulate the CPI units and convert them back into
        # dollars using the current month's CPI.
        #
        # This tells us what all of the deposits/withdrawals since
        # the beginning of the dataframe are worth after inflation.
        ldf['InflationAdjustedFunding'] = ldf['FundingCPIUnits'].cumsum() * ldf['CPICost']

        # ------------------------------------------------------------
        # Inflation-adjusted portfolio value
        # ------------------------------------------------------------

        # Convert the actual portfolio value into the purchasing
        # power of the first month.
        #
        # Example:
        #   $1,000,000 when CPI = 160
        #   is equivalent to less than $1,000,000 when expressed
        #   in the purchasing power of the earlier month.
        initial_cpi = ldf['CPICost'].iloc[0]

        ldf['RealTotalValue'] = ldf['TotalValue'] / ldf['CPICost'] * initial_cpi

        # ------------------------------------------------------------
        # Investment gain after inflation
        # ------------------------------------------------------------

        # The difference between the actual portfolio and the
        # inflation-adjusted funding.
        ldf['RealGain'] = ldf['TotalValue'] - ldf['InflationAdjustedFunding']

        #ldf["ValueChange"] = ldf["TotalValue"].diff()
        #ldf['Inflation'] = ldf['CPICost'].pct_change()
        #ldf["NewFunding"] = ldf["Funding"].diff()

        #ldf["FundingCPIUnits"] = ldf["NewFunding"] / ldf["CPICost"]
        #ldf["InflationAdjustedFunding"] = ldf["FundingCPIUnits"].cumsum() * ldf["CPICost"]

        #initial_value = ldf.loc[0, "TotalValue"]
        #initial_funding = ldf.loc[0, "Funding"]
        #initial_cpi = ldf.loc[0, "CPICost"]

        #ldf["RealGain"] = ldf["TotalValue"] - ldf["InflationAdjustedFunding"]
        #ldf["RealTotalValue"] = ldf["TotalValue"] / ldf["CPICost"] * ldf["CPICost"].iloc[0]
        
    starting = df.iloc[0].InvValue
    data = df["InvValue"].to_list()

    if dfo.scope == 'month' or scope == 'month':
        labels = [this_date.strftime('%Y-%b') for this_date in df["Date"].to_list()]
    else:
        labels = [this_date.strftime('%b-%d') for this_date in df["Date"].to_list()]

    return JsonResponse({"labels": labels, "data": data, "starting": starting})


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
    Data for a chart that shows growth by 1) Accounts, 2) Investments, 3) Containers
    '''
    colors = COLORS.copy()
    ci = 0

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')
    date_range = request.GET.get('range', 'year')
    object_id = int(object_id) if object_id else object_id

    dfo = WealthDF(user, date_range=date_range)
    df = dfo.by_range(date_range)                                                          # Limit dataframe to match requested range

    if object_type and object_type == 'Account':
        df = df.loc[df['AccountID'] == object_id]     # Limit dataframe only items matching this account
        groupon = 'Symbol'                            # expand using symbol
    elif object_type and object_type == 'Portfolio':  # Limit dataframe to only items matching this portfolio
        df = df.loc[df['PortfolioID'] == object_id]   # expand using AccountID
        groupon = 'AccountID'
    else:
        groupon = 'Mixed'                             # Show both Portfolio rollup and Accounts without portfolios

    if df.empty:
        return JsonResponse({'labels': [], 'datasets': []})

    these_dates = dfo.dates.loc[dfo.dates['Date'] >= IOOMDates(build=False).range_start(date_range)]  # Limit dates to just those in the range
    these_dates = these_dates.loc[these_dates['Date'] >= df['Date'].min()]

    if groupon == 'Mixed':
        portfolios = df.loc[((df['InvType'] == 'Trading') | (df['InvType'] == 'Value')) & (df['PortfolioID'] != 0)].groupby(['Date', 'PortfolioID']).agg({'InvValue': 'sum'}).reset_index()
        accounts = df.loc[((df['InvType'] == 'Funding') | (df['InvType'] == 'Value')) & (df['PortfolioID'] == 0)].groupby(['Date', 'AccountID']).agg({'InvValue': 'sum'}).reset_index()
        values = pd.concat([portfolios, accounts])
    else:
        values = df.loc[(df['InvType'] == 'Trading') | (df['InvType'] == 'Value')].groupby(['Date', groupon]).agg({'InvValue': 'sum'}).reset_index()

    values = dfo.set_names(values)

    if dfo.scope == 'month':
        labels = [this_date.strftime('%Y-%b') for this_date in these_dates['Date'].to_list()]
    else:
        labels = [this_date.strftime('%b-%d') for this_date in these_dates['Date'].to_list()]

    datasets = []
    for search_on in {'PortfolioName', 'AccountName', 'Symbol'} & set(values.columns):
        for x in values[search_on].unique():
            if isinstance(x, str):  # A valid column
                color = colors[ci]
                ci += 1
                data_df = these_dates.merge(values.loc[values[search_on] == x], on=['Date'], how='left')
                data_df['InvValue'] = data_df['InvValue'].astype('float64').fillna(0)
                data = data_df['InvValue'].to_list()
                logger.debug('%s: size%s' % (x, len(data)))
                if len(data) == len(labels):
                    datasets.append({
                        'label': x,
                        'fill': False,
                        'data': data,
                        'boarderColor': color, 'backgroundColor': color,
                        'stack': 1,
                        'order': 1,
                    })

    data = these_dates.merge(df.loc[df['InvType'] == 'Funding'].groupby('Date').agg({'InvValue': 'sum'}), on='Date', how='left')
    data['InvValue'] = data['InvValue'].ffill().fillna(0)
    data.loc[data['InvValue'] < 0, 'InvValue'] = 0
    datasets.append({
        'label': 'Funding',
        'fill': False,
        'data': data['InvValue'].to_list(),
        'boarderColor': '#000000', 'backgroundColor': '#000000',
        'type': 'line',
        'order': 0,
    })

    return JsonResponse({'labels': labels, 'datasets': datasets})

@login_required
def growth_and_dividends(request):
    """
    Chartjs,  X axis is dates,  Yleft is lines with values (change or raw ?),  Yright is Dividend Price or Value

    <canvas id="myChart"></canvas>

<script>
const ctx = document.getElementById('myChart');

new Chart(ctx, {
    data: {
        labels: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'],

        datasets: [
            {
                type: 'line',
                label: 'Portfolio Value',
                data: [100000, 103000, 101000, 108000, 112000, 115000],
                yAxisID: 'yValue',

                borderWidth: 2,
                tension: 0.2,
                pointRadius: 0
            },
            {
                type: 'bar',
                label: 'Contributions',
                data: [5000, 2000, 0, 7500, 3000, 0],
                yAxisID: 'yContributions',

                borderWidth: 0,
                barPercentage: 0.6
            }
        ]
    },

    options: {
        responsive: true,

        interaction: {
            mode: 'index',
            intersect: false
        },

        scales: {

            // LEFT Y AXIS
            yValue: {
                type: 'linear',
                position: 'left',

                title: {
                    display: true,
                    text: 'Portfolio Value'
                },

                ticks: {
                    callback: function(value) {
                        return '$' + value.toLocaleString();
                    }
                }
            },

            // RIGHT Y AXIS
            yContributions: {
                type: 'linear',
                position: 'right',

                title: {
                    display: true,
                    text: 'Contributions'
                },

                ticks: {
                    callback: function(value) {
                        return '$' + value.toLocaleString();
                    }
                },

                // Don't draw another grid over the chart
                grid: {
                    drawOnChartArea: false
                }
            }
        }
    }
});
</script>
    """
    user = request.user
    account = request.GET.get('account')
    symbol = request.GET.get('symbol')
    date_range = request.GET.get('range', 'year')
    detail = request.GET.get('detail', 'detail') # vs 'trend'

    dfo = WealthDF(user, date_range=date_range)  # Calculate the span (months vs days)
    df = dfo.by_range(date_range)                # Limit dataframe to match requested range


@login_required
def zero_acc_summary(request):
    '''
    Produce a simple chart
    Three modes,  1) Portfolio,  2) Account,  3) Everything
    '''

    user = request.user
    object_id = request.GET.get('object_id')
    object_type = request.GET.get('object_type')
    date_range = request.GET.get('range', 'year')
    object_id = int(object_id) if object_id else object_id
    options = request.GET.getlist('options[]')

    dfo = WealthDF(user, date_range=date_range)  # Calculate the span (months vs days)
    df = dfo.by_range(date_range)                # Limit dataframe to match requested range

    if object_type and object_type == 'Account':
        df = df.loc[df['AccountID'] == object_id]     # Limit dataframe only items matching this account
    elif object_type and object_type == 'Portfolio':  # Limit dataframe to only items matching this portfolio
        df = df.loc[df['PortfolioID'] == object_id]   # expand using AccountID
    # else do everything

    if df.empty:
        return JsonResponse({'labels': [], 'datasets': []})

    df = (df.loc[(df["InvType"] == "Trading") | (df["InvType"] == "Value")].groupby(["Date"]).
          agg({"InvValue": "sum"}).reset_index())

    starting = df.iloc[0].InvValue
    data = df["InvValue"].to_list()

    if dfo.scope == 'month':
        labels = [this_date.strftime('%Y-%b') for this_date in df["Date"].to_list()]
    else:
        labels = [this_date.strftime('%b-%d') for this_date in df["Date"].to_list()]

    return JsonResponse({"labels": labels, "data": data, "starting": starting})

    values = df.loc[(df['InvType'] == 'Trading') | (df['InvType'] == 'Value')].groupby(['Date']).agg({'InvValue': 'sum'}).reset_index()
    these_dates = values["Date"]
    values['InvValue'] = values['InvValue'].fillna(0)
    starting = values.iloc[0].InvValue
    data = values['InvValue'].to_list()

    labels = [
        this_date.strftime("%Y-%b-%d") for this_date in these_dates.to_list()
    ]

    return JsonResponse({'labels': labels, 'data': data, 'starting': starting})


@login_required
def equity_summary(request):
    #colors = COLORS.copy()
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
    #end = this.end if this.end else IOOMDates().
    if not (start and end):
        return JsonResponse({'status': 'false', 'message': 'Invalid Data'}, status=500)

    start = start.strftime('%Y-%m-%d')
    end = end.strftime('%Y-%m-%d')

    date_range = pd.date_range(start=start, end=end, freq='MS')
    month_df = pd.DataFrame({'Date': date_range, 'Value': 0})

    labels = [this_date.strftime('%Y-%b') for this_date in month_df['Date'].to_list()]
    datasets = []
    if object_type == 'Account' and this.account_type == 'Cash':
        datasets.append({
            'label': 'Cash',
            'fill': False,
            'data': this_pd['Cash'].to_list(),
            'boarderColor': PALETTE['green'], 'backgroundColor': PALETTE['green'],
            'stack': 1,
            'order': 1,
        })
    else:
        ci = 0
        for equity in this.equities:
            color = colors[ci]
            ci += 1
            label = equity.symbol if equity.equity_type == 'Equity' else equity.equity_type
            if equity.equity_type == 'Value':
                datasets.append({
                    'label': label,
                    'fill': False,
                    'data': this_pd['Value'].to_list(),
                    'boarderColor': color, 'backgroundColor': color,
                    'stack': 1,
                    'order': 1,
                })
            else:
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
    # df = cost_df.applymap(lambda x: 0 if x < 0 else x)
    cost_df[cost_df < 0] = 0

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
