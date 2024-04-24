import csv
import logging

import plotly.io as pio
import plotly.graph_objects as go

from pandas import DataFrame

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin


from .models import Equity, Portfolio, Transaction, EquityEvent, EquityValue
from .forms import AddEquityForm, TransactionForm, PortfolioForm, UploadFileForm
from .importers import QuestTrade, Manulife, StockImporter, HEADERS
from stocks.base.utils import DIYImportException
from .tasks import daily_update

logger = logging.getLogger(__name__)


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
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        p: Portfolio = context['portfolio']
        x = sorted(p.p_pd['Date'].unique())
        cost = p.p_pd['EffectiveCost']
        value = p.p_pd['Value'] + p.p_pd['Cash']
        inflation = p.p_pd['InflatedCost']
        dividends = p.p_pd['TotalDividends']

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=dividends, mode='lines', name='Total Dividends'))
        fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Effective Cost'))
        fig.add_trace(go.Scatter(x=x, y=value, mode='lines', name='Value'))
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

def diy_update(request):
    """
    :param request:
    :return:
    """
    daily_update()
    return HttpResponseRedirect(reverse('portfolio_list'))

class PortfolioAdd(CreateView):
    model = Portfolio
    template_name = 'stocks/add_portfolio.html'
    fields = ['name', 'currency', 'managed']
    # form_class = AddPortfolioForm

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Add'
        return context


class PortfolioEdit(UpdateView, DateMixin):
    model = Portfolio
    # fields = ['name', 'currency', 'managed', 'end']
    template_name = 'stocks/add_portfolio.html'
    date_filed = 'end'
    form_class = PortfolioForm

    def get_success_url(self):
        return reverse('portfolio_list')

    def get_initial(self):
        original = Portfolio.objects.get(pk=self.kwargs['pk'])
        return {'name': original.name,
                'currency': original.currency,
                'managed': original.managed}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


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
                                       price=t.price, value=t.value,
                                       quantity=t.quantity, xa_action=t.xa_action)


        return result

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.id})


def upload_file(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            bin_file = form.cleaned_data['csv_file'].read()
            text_file = bin_file.decode('utf-8')
            reader = csv.reader(text_file.splitlines())
            stub = form.cleaned_data['stub'] if form.cleaned_data['stub'] else None
            try:
                if form.cleaned_data["csv_type"] == 'QuestTrade':
                    importer = QuestTrade(reader, stub)
                elif form.cleaned_data["csv_type"] == 'Manulife':
                    importer = Manulife(reader, stub)
                else:
                    importer = StockImporter(reader, HEADERS, stub=stub, managed=False)
                importer.process()
                if len(importer.warnings) != 0:
                    return render(request, "stocks/uploadfile.html",
                                  {"form": form, 'custom_warnings': importer.warnings})
            except DIYImportException as e:
                return render(request, "stocks/uploadfile.html", {"form": form, 'custom_error': str(e)})
            return HttpResponseRedirect(reverse('portfolio_list'))

    else:
        form = UploadFileForm()
    return render(request, "stocks/uploadfile.html", {"form": form})


def add_transaction(request, pk):
    portfolio = get_object_or_404(Portfolio, pk=pk)

    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            new = Transaction.objects.create(equity=form.cleaned_data['equity'],
                                             date=form.cleaned_data['date'],
                                             price=form.cleaned_data['price'],
                                             quantity=form.cleaned_data['quantity'],
                                             xa_action=form.cleaned_data['action'],
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
    return render(request, 'stocks/add_transaction.html', context)


def portfolio_compare(request, pk, symbol):
    portfolio: Portfolio = get_object_or_404(Portfolio, pk=pk)
    compare_equity: Equity = get_object_or_404(Equity, symbol=symbol)
    compare_to: DataFrame = portfolio.switch(compare_equity)

    x = sorted(portfolio.e_pd['Date'].unique())
    new = portfolio.e_pd[['Date', 'EffectiveCost', 'InflatedCost', 'Value', 'TotalDividends']].groupby('Date').sum()
    comp = compare_to[['Date', 'Value',  'InflatedCost', 'TotalDividends']].groupby('Date').sum()
    total = new['Value']
    dividends = new['TotalDividends']
    inflation = new['InflatedCost']
    cost = new['EffectiveCost']
    compt = comp['Value']
    compd = comp['TotalDividends']

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=dividends, mode='lines', name='Total Dividends'))
    fig.add_trace(go.Scatter(x=x, y=total, mode='lines', name='Present Value'))
    fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Effective Cost'))
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


def portfolio_equity_details(request, pk, symbol):
    """

    :param request:
    :param pk:
    :param symbol:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    portfolio = get_object_or_404(Portfolio, pk=pk)
    equity = get_object_or_404(Equity, symbol=symbol)

    dividend_detail = dict(EquityEvent.objects.filter(event_type='Dividend', equity=equity).values_list('date', 'value'))
    value_detail = dict(EquityValue.objects.filter(equity=equity).values_list('date', 'price'))

    data = []
    chart_html = '<p>No chart data available</p>'
    #portfolio.pd['Date'] = pd.to_datetime(portfolio.pd['Date'])
    df_sorted = portfolio.e_pd.sort_values(by='Date')
    new_df = df_sorted.loc[df_sorted['Equity'] == equity.symbol]
    for element in new_df.to_records():
        extra_data = ''
        if element['Date'] in portfolio.trade_dates(equity):
            quantity, price = portfolio.trade_details(equity, element['Date'])
            if quantity < 0:
                extra_data = f'Sold {quantity} shares at ${price}'
            else:
                if price == 0:
                    extra_data = f'Received {quantity} shares (DRIP or Split)'
                else:
                    extra_data = f'Bought {quantity} shares at ${price}'

        if element['Shares'] == 0:
            total_dividends = equity_growth = 0
        else:
            total_dividends = element['TotalDividends']
            equity_growth = element['Value'] - element['EffectiveCost']

        share_price = value_detail[element['Date']] if element['Date'] in value_detail else 0
        dividend_price = dividend_detail[element['Date']] if element['Date'] in dividend_detail else 0

        data.append([element['Date'], element['Shares'], element['Value'], element['EffectiveCost'],
                     total_dividends, equity_growth, dividend_price,
                     share_price, extra_data])

        x = sorted(new_df['Date'].unique())
        #new = df_sorted.loc[df_sorted['Equity'] == equity.key][['Date', 'Cost', 'Value', 'TotalDividends']]
        cost = new_df['EffectiveCost']
        inflation = new_df['InflatedCost']
        total = new_df['Value']
        dividends = new_df['TotalDividends']
        e_value = new_df['TotalDividends'] + new_df['Value']

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=e_value, fill='tonexty', mode='lines', name='Effective Value'))
        fig.add_trace(go.Scatter(x=x, y=dividends, mode='lines', name='Total Dividends'))

        fig.add_trace(go.Scatter(x=x, y=total, mode='lines', name='Present Value'))
        fig.add_trace(go.Scatter(x=x, y=cost, mode='lines', name='Effective Cost'))
        fig.add_trace(go.Scatter(x=x, y=inflation, mode='lines', name='Inflation Cost'))
        fig.update_layout(title=f'{portfolio}/{equity}: Return vs Cost', xaxis_title='Month', yaxis_title='Dollars')
        chart_html = pio.to_html(fig, full_html=False)

    data.reverse()
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
