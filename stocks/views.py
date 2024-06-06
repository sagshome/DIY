# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)

import csv
import logging
import json

import plotly.io as pio
import plotly.graph_objects as go

from pandas import DataFrame
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin
from django.http import JsonResponse


from .models import Equity, Portfolio, Transaction, EquityEvent, EquityValue
from .forms import *
from .importers import QuestTrade, Manulife, StockImporter, HEADERS
from base.utils import DIYImportException
from .tasks import daily_update
from base.models import Profile, COLORS

logger = logging.getLogger(__name__)




class PortfolioView(LoginRequiredMixin, ListView):
    model = Portfolio
    template_name = 'stocks/portfolio_list.html'

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this portfolio
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """

        profile = Profile.objects.get(user=self.request.user)
        context = super().get_context_data(**kwargs)
        context['portfolio_list'] = Portfolio.objects.filter(user=self.request.user)
        context['can_update'] = True if profile.av_api_key else False
        return context


class PortfolioDeleteView(LoginRequiredMixin, DeleteView):
    model = Portfolio
    template_name = 'stocks/delete_portfolio_confirm_delete.html'
    success_url = '/stocks/portfolio/'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))


class PortfolioDetailView(LoginRequiredMixin, DetailView):
    model = Portfolio
    template_name = 'stocks/portfolio_detail.html'

    def get_object(self):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_context_data(self, **kwargs):
        """
        Add a list of all the equities in this portfolio
        :param kwargs:
        :return:
        ['Date', 'EffectiveCost', 'Value', 'TotalDividends', 'InflatedCost']
        """
        context = super().get_context_data(**kwargs)
        profile = Profile.objects.get(user=self.request.user)
        can_update = True if profile.av_api_key else False
        p: Portfolio = context['portfolio']
        return {'portfolio': p,  'can_update': can_update}


def portfolio_update(request, pk):
    """
    :param request:
    :param pk:
    :param key:
    :return:
    """
    profile = Profile.objects.get(user=request.user)
    if not profile.av_api_key:
        return HttpResponse(status=404)

    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
    portfolio.update()
    return HttpResponse(status=200)


def diy_update(request):
    """
    :param request:
    :return:
    """
    daily_update()
    return HttpResponseRedirect(reverse('portfolio_list'))


class PortfolioAdd(LoginRequiredMixin, CreateView):
    model = Portfolio
    template_name = 'stocks/add_portfolio.html'
    form_class = PortfolioAddForm

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.id})

    def get_initial(self):
        super().get_initial()
        self.initial['user'] = self.request.user.id
        return self.initial


class PortfolioEdit(UpdateView, DateMixin):
    model = Portfolio
    # fields = ['name', 'currency', 'managed', 'end']
    template_name = 'stocks/add_portfolio.html'
    date_filed = 'end'
    form_class = PortfolioForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse('portfolio_list')

    def get_initial(self):
        original = Portfolio.objects.get(pk=self.kwargs['pk'])
        return {'name': original.name,
                'currency': original.currency,
                'managed': original.managed,
                'user': original.user}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


class PortfolioCopy(CreateView):
    model = Portfolio
    template_name = 'stocks/add_portfolio.html'
    form_class = PortfolioCopyForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Portfolio.objects.filter(user=self.request.user))


    def get_initial(self):
        original = Portfolio.objects.get(pk=self.kwargs['pk'])
        return {'name': f'{original.name}_copy',
                'user': original.user,
                'managed': original.managed,
                'currency': original.currency,
                'end': original.end}

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


@login_required
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
                    importer = QuestTrade(reader, request.user, stub)
                elif form.cleaned_data["csv_type"] == 'Manulife':
                    importer = Manulife(reader, request.user, stub)
                else:
                    importer = StockImporter(reader, request.user, HEADERS, stub=stub, managed=False)
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


@login_required
def add_transaction(request):
    if request.method == 'POST':
        form = TransactionAddForm(request.POST, initial={'user': request.user})
        if form.is_valid():
            action = form.cleaned_data['xa_action']
            if action == Transaction.FUND or Transaction.SELL:
                new = Transaction.objects.create(user=request.user,
                                                 date=form.cleaned_data['date'],
                                                 price=0,
                                                 quantity=0,
                                                 value=form.cleaned_data['value'],
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 portfolio=form.cleaned_data['portfolio'])
            else:
                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 date=form.cleaned_data['date'],
                                                 price=form.cleaned_data['price'],
                                                 quantity=form.cleaned_data['quantity'],
                                                 xa_action=form.cleaned_data['xa_action'])

            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                form = TransactionAddForm(initial={'user': request.user,
                                                'portfolio': new.portfolio,
                                                'equity': new.equity,
                                                'date': new.date})
            else:
                return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': new.portfolio.id}))
    else:  # Initial get
        form = TransactionAddForm(initial={'user': request.user})

    context = {
        'form': form,
    }
    return render(request, 'stocks/add_transaction.html', context)


@login_required
def portfolio_compare(request, pk, symbol):
    portfolio: Portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
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


@login_required
def equity_update(request,  key):
    """

    :param request:
    :param pk:
    :param key:
    :return:
    """
    profile = Profile.objects.get(user=request.user)
    if not profile.av_api_key:
        return HttpResponse(status=404)

    equity = get_object_or_404(Equity, symbol=key)
    equity.update(key=profile.av_api_key)
    return HttpResponse(status=200)


@login_required
def portfolio_equity_details(request, pk, symbol):
    """

    :param request:
    :param pk:
    :param symbol:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')

    """
    portfolio = get_object_or_404(Portfolio, pk=pk, user=request.user)
    equity = get_object_or_404(Equity, symbol=symbol)

    dividend_detail = dict(EquityEvent.objects.filter(event_type='Dividend', equity=equity).values_list('date', 'value'))
    value_detail = dict(EquityValue.objects.filter(equity=equity).values_list('date', 'price'))

    data = []
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
            equity_growth = element['Value'] - element['EffectiveCost'] + total_dividends

        share_price = value_detail[element['Date']] if element['Date'] in value_detail else 0
        dividend_price = dividend_detail[element['Date']] if element['Date'] in dividend_detail else 0

        data.append([element['Date'], element['Shares'], element['Value'], element['EffectiveCost'],
                     total_dividends, equity_growth, dividend_price,
                     share_price, extra_data])

    data.reverse()
    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data, 'portfolio': portfolio, 'equity': equity})



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


def overlay_dates(dataframe: DataFrame, key: str, symbol: str, list_of_dates):
    result = []
    for this_date in list_of_dates:
        value = dataframe.loc[(dataframe['Equity'] == symbol) & (dataframe['Date'] == this_date)][key]
        if len(value) != 1:
            result.append(0)
        else:
            result.append(value.item())
    return result


@login_required
def growth_chart(request):


    portfolio_id = request.GET.get("portfolio_id")
    equity_id = request.GET.get("equity_id")
    compare_id = request.GET.get("compare_id")

    portfolio = equity = compare_to = None
    try:
        portfolio = Portfolio.objects.get(id=portfolio_id, user=request.user)
        if equity_id:
            equity = Equity.objects.get(id=equity_id)
        if compare_id:
            compare_to = Equity.objects.get(id=compare_id)
    except:  # Yes,  I know this is too broad but really,  what else could it be
        JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    colors = COLORS.copy()
    ci = 0
    chart_data = {'labels': sorted(portfolio.p_pd['Date'].unique()), 'datasets': []}

    for this_equity in portfolio.e_pd['Equity'].unique():
        if (equity and this_equity == equity.symbol) or not equity:
            values = overlay_dates(portfolio.e_pd, 'Value', this_equity, chart_data['labels'])
            chart_data['datasets'].append({'label': this_equity, 'fill': True, 'data': values, 'backgroundColor': colors[ci]})
            ci += 1

    if equity:
        cost = overlay_dates(portfolio.e_pd, 'InflatedCost', equity.symbol, chart_data['labels'])
    else:
        cost = portfolio.p_pd['InflatedCost'].tolist()
    next_color = colors.pop()
    chart_data['datasets'].append({'label': 'Inflated Cost', 'type': 'line', 'fill': False, 'data': cost, 'borderColor': colors[ci],
                                   'backgroundColor': colors[ci]})
    ci += 1
    if compare_to:
        if equity:
            new_df = portfolio.switch(compare_to, equity)
            compare = overlay_dates(new_df, 'Value', compare_to.symbol, chart_data['labels'])
        else:
            new_df = portfolio.switch(compare_to)
            compare = new_df['InflatedCost'].tolist()
        chart_data['datasets'].append({'label': compare_to.symbol, 'fill': True, 'data': compare, 'backgroundColor': colors[ci]})

    return JsonResponse(chart_data)


@login_required
def cost_value_chart(request):
    """
    Build the chart.js data for a bar chart based on the standard search_filter
    """

    colors = COLORS.copy()
    chart_data = {'labels': None,
                  'datasets': []}

    portfolio_id = request.GET.get("portfolio_id")
    equity_id = request.GET.get("symbol")

    try:
        p = Portfolio.objects.get(id=portfolio_id, user=request.user)
        if p.transactions:
            chart_data['labels'] = sorted(p.p_pd['Date'].unique())
            if not equity_id:
                chart_data['datasets'].append({'label': 'Inflation Cost', 'fill': False,
                                               'data': p.p_pd['InflatedCost'].tolist(),
                                               'borderColor': colors[0], 'backgroundColor': colors[0]})
                chart_data['datasets'].append({'label': 'Effective Cost', 'fill': False,
                                               'data': p.p_pd['EffectiveCost'].tolist(),
                                               'borderColor': colors[1], 'backgroundColor': colors[1]})
                value = p.p_pd['Value'] + p.p_pd['Cash']
                chart_data['datasets'].append({'label': 'Value', 'fill': False,
                                               'data': value.tolist(),
                                               'borderColor': colors[3], 'backgroundColor': colors[3]})

            else:
                try:
                    equity = Equity.objects.get(id=equity_id)
                except Equity.DoesNotExist:
                    JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

                new_df = p.e_pd.loc[p.e_pd['Equity'] == equity.symbol]
                new_df['ec'] = new_df['EffectiveCost'] - new_df['TotalDividends']

                ec = overlay_dates(new_df, 'ec', equity.symbol, chart_data['labels'])
                cost = overlay_dates(p.e_pd, 'InflatedCost', equity.symbol, chart_data['labels'])
                value = overlay_dates(p.e_pd, 'Value', equity.symbol, chart_data['labels'])

                chart_data['datasets'].append({'label': 'Inflation Cost', 'fill': False,
                                               'data': cost,
                                               'borderColor': colors[0], 'backgroundColor': colors[0]})
                chart_data['datasets'].append({'label': 'Effective Cost', 'fill': False,
                                               'data': ec,
                                               'borderColor': colors[1], 'backgroundColor': colors[1]})
                chart_data['datasets'].append({'label': 'Value', 'fill': False,
                                               'data': value,
                                               'borderColor': colors[3], 'backgroundColor': colors[3]})

    except Portfolio.DoesNotExist:
        JsonResponse({'status': 'false', 'message': 'Does Not Exist'}, status=404)

    return JsonResponse(chart_data)
