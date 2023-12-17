import pandas as pd
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go

from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, DetailView, CreateView, DeleteView


from .models import Equity, Portfolio, Transaction, normalize_today
from .forms import AddEquityForm, TransactionForm
from .importers import *

def test2(request):
    from .models import Inflation
    Inflation.update()
    return JsonResponse(status=200, data={})


def test(request):
    # manulife('/home/scott/shared/Finance/manulife_1_xas.csv')
    #questtrade('/home/scott/Downloads/GailQtrade.csv', 'Gail')
    # questtrade('/home/scott/Downloads/QTest1.csv', 'QTest1')
    p: Portfolio = Portfolio.objects.get(name='Scott-Individual RRSP')
    p.update_static_values()
    return JsonResponse(status=200, data={})

@require_http_methods(['GET'])
def search(request):
    """
    Ajax call to run a search and return list of possible values
    :param request:
    :return:
    """
    string = request.GET.get('string')
    if string:
        region = request.GET.get('region')

    if not region:
        region = 'United States'

    response = Equity.lookup(string)
    if response:
        for value in response:
            print(value, type(value))
            if '4. region' in value and value['4. region'] == region:
                result = {'key':  value['1. symbol'],
                          'name': value['2. name'],
                          'type': value['3. type'],
                          'region': value['4. region'],
                          'symbol': value['1. symbol'].split('.')[0],
                          'currency': value['8. currency'],
                          'value': value['6. marketClose'],
                          }
                return JsonResponse(status=200, data=result)
    return JsonResponse(status=407, data={'status': 'false', 'message': f'Lookup of "{string}" for "{region}" not found'})


class PortfolioView(ListView):
    model = Portfolio
    template_name = 'stocks/portfolio_list.html'


class PortfolioDeleteView(DeleteView):
    model = Portfolio
    template_name = 'stocks/delete_portfolio_confirm_delete.html'
    success_url = '/stocks/portfolio/'


class PortfolioDetailView(DetailView):
    model = Portfolio
    template_name = 'stocks/portfolio_detail.html'

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this portfolio
        :param kwargs:
        :return:

        """
        context = super().get_context_data(**kwargs)
        p = context['portfolio']
        x = sorted(p.pd['Date'].unique())
        new = p.pd[['Date', 'EffectiveCost', 'InflatedCost', 'Value', 'TotalDividends']].groupby('Date').sum()
        cost = new['EffectiveCost']
        inflation = new['InflatedCost']
        total = new['Value'] + new['TotalDividends']
        dividends = new['TotalDividends']

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=dividends, fill='tonexty', mode='lines', name='Total Dividends'))

        fig.add_trace(go.Scatter(x=x, y=total, fill='tonexty', mode='lines', name='Present Value (Stacked)'))
        fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Cost'))
        fig.add_trace(go.Scatter(x=x, y=inflation, mode='lines', name='Inflation Cost'))

        fig.update_layout(title='Return vs Cost', xaxis_title='Month', yaxis_title='Dollars')
        chart_html = pio.to_html(fig, full_html=False)
        context = {'portfolio': p, 'chart': chart_html}
        return context


def portfolio_update(request, pk):
    """
    :param request:
    :param pk:
    :param key:
    :return:
    """
    portfolio = get_object_or_404(Portfolio, pk=pk)
    portfolio.update()
    return HttpResponse(status=200)


class PortfolioAdd(CreateView):
    model = Portfolio
    template_name = 'stocks/add_portfolio.html'
    fields = ['name', 'managed']
    # form_class = AddPortfolioForm

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.id})


class PortfolioCopy(CreateView):
    model = Portfolio
    template_name = 'stocks/add_portfolio.html'
    fields = ['name']

    def get_initial(self):
        original = Portfolio.objects.get(pk=self.kwargs['pk'])
        return {'name': f'{original.name}_copy'}

    def form_valid(self, form):
        """

        :param form:
        :return:
        """
        result = super().form_valid(form)
        original = Portfolio.objects.get(pk=self.kwargs['pk'])
        for t in Transaction.objects.filter(portfolio=original):
            Transaction.objects.create(portfolio=self.object, equity=t.equity, date=t.date,
                                       price=t.price,
                                       quantity=t.quantity, buy_action=t.xa_action)

        return result

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.id})


def portfolio_buy(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    print(request.__dict__, pk)

    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            equity = Equity.objects.get(key=form.cleaned_data['equity'])
            new = Transaction.objects.create(equity=equity,
                                             date=form.cleaned_data['date'],
                                             price=form.cleaned_data['price'],
                                             quantity=form.cleaned_data['quantity'],
                                             portfolio=portfolio)
            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                form = TransactionForm(initial={'portfolio': portfolio,
                                                'equity': new.equity,
                                                'date': new.date})
            else:
                return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': portfolio.id}))
    else:  # Initial get
        form = TransactionForm(initial={'portfolio': portfolio.name})

    context = {
        'form': form,
        'portfolio': portfolio,
    }
    return render(request, 'stocks/add_bulk_equity.html', context)


def portfolio_compare(request, pk, symbol):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    compare_equity = Equity.objects.get(symbol=symbol)
    compare_to = portfolio.summary.switch(compare_equity.name, compare_equity, portfolio)

    x = sorted(portfolio.pd['Date'].unique())
    new = portfolio.pd[['Date', 'Cost', 'InflatedCost', 'Value', 'TotalDividends']].groupby('Date').sum()
    comp = compare_to.pd[['Date', 'Value',  'InflatedCost', 'TotalDividends']].groupby('Date').sum()
    total = new['Value']
    dividends = new['TotalDividends']
    inflation = new['InflatedCost']
    cost = new['Cost']
    compt = comp['Value']
    compd = comp['TotalDividends']

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=dividends, mode='lines', name='Total Dividends'))
    fig.add_trace(go.Scatter(x=x, y=total, mode='lines', name='Present Value'))
    fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Cost'))
    fig.add_trace(go.Scatter(x=x, y=inflation, mode='lines', name='Inflation'))
    fig.add_trace(go.Scatter(x=x, y=compd, mode='lines', name=f'Dividends if...{compare_equity}'))
    fig.add_trace(go.Scatter(x=x, y=compt, mode='lines', name=f'Present Value if...{compare_equity}'))
    fig.update_layout(title='Return vs Cost', xaxis_title='Month', yaxis_title='Dollars')
    chart_html = pio.to_html(fig, full_html=False)
    return render(request, 'stocks/portfolio_compare.html',
                  {'portfolio': portfolio, 'compare_to': compare_equity, 'chart': chart_html})


def equity_update(request,  key):
    """

    :param request:
    :param pk:
    :param key:
    :return:
    """
    equity = get_object_or_404(Equity, symbol=key)
    equity.update()
    return HttpResponse(status=200)


def portfolio_equity_details(request, pk, key):
    """

    :param request:
    :param pk:
    :param key:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    portfolio = get_object_or_404(Portfolio, pk=pk)
    equity = get_object_or_404(Equity, symbol=key)


    dividend_detail = dict(EquityEvent.objects.filter(event_type='Dividend', equity=equity).values_list('date', 'value'))
    value_detail = dict(EquityValue.objects.filter(equity=equity).values_list('date', 'price'))

    data = []
    chart_html = '<p>No chart data available</p>'
    #portfolio.pd['Date'] = pd.to_datetime(portfolio.pd['Date'])
    df_sorted = portfolio.pd.sort_values(by='Date')
    new_df = df_sorted.loc[df_sorted['Equity'] == equity.key]
    for element in new_df.to_records():
        extra_data = ''
        if element['Date'] in portfolio.transactions[equity.key]:
            xa = portfolio.transactions[equity.key][element['Date']]
            if xa.quantity < 0:
                extra_data = f'Sold {xa.quantity} shares at ${xa.price}'
            else:
                if xa.price == 0:
                    extra_data = f'Received {xa.quantity} shares (DRIP or Split)'
                else:
                    extra_data = f'Bought {xa.quantity} shares at ${xa.price}'

        if element['Shares'] == 0:
            total_dividends = equity_growth = 0
        else:
            total_dividends = element['TotalDividends']
            equity_growth = element['Value'] - element['EffectiveCost']

        #total_dividends = element['TotalDividends']
        #eyield = element['Yield']

        share_price = value_detail[element['Date']] if element['Date'] in value_detail else 0
        dividend_price = dividend_detail[element['Date']] if element['Date'] in dividend_detail else 0

        data.append([element['Date'], element['Shares'], element['Value'], element['EffectiveCost'],
                     total_dividends, equity_growth, dividend_price,
                     share_price, extra_data])
        #data.reverse()

        x = sorted(new_df['Date'].unique())
        #new = df_sorted.loc[df_sorted['Equity'] == equity.key][['Date', 'Cost', 'Value', 'TotalDividends']]
        cost = new_df['EffectiveCost']
        inflation = new_df['InflatedCost']
        total = new_df['Value'] + new_df['TotalDividends']
        dividends = new_df['TotalDividends']

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=dividends, fill='tonexty', mode='lines', name='Total Dividends'))

        fig.add_trace(go.Scatter(x=x, y=total, fill='tonexty', mode='lines', name='Present Value (Stacked)'))
        fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Cost'))
        fig.add_trace(go.Scatter(x=x, y=inflation, mode='lines', name='Inflation Cost'))
        fig.update_layout(title=f'{portfolio}/{equity}: Return vs Cost', xaxis_title='Month', yaxis_title='Dollars')
        chart_html = pio.to_html(fig, full_html=False)

    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data, 'portfolio': portfolio, 'equity': equity, 'chart': chart_html})


def add_equity(request):
    symbol_list = {}
    if request.method == 'POST':
        form = AddEquityForm(request.POST)
        if form.is_valid():
            equity = Equity.objects.create(name=form.cleaned_data['key'])
            return HttpResponseRedirect(reverse('portfolio_list'))
    else:  # Initial get
        form = AddEquityForm()

    context = {
        'form': form,
        'symbol_list': symbol_list
    }
    return render(request, 'stocks/add_equity.html', context)
