# todo:  I need a add a transaction (buy, sell, redeem, fund, dividend - etc..)

import csv
import logging
import os
import json

from datetime import datetime, date
from dateutil import relativedelta

import plotly.io as pio
import plotly.graph_objects as go

from pandas import DataFrame
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import QuerySet, Sum, Avg, Q
from django.core.mail import EmailMultiAlternatives, EmailMessage

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, DeleteView, UpdateView
from django.views.generic.dates import DateMixin
from django.http import JsonResponse


from .models import Equity, Portfolio, Transaction, EquityEvent, EquityValue
from .forms import *
from .importers import QuestTrade, Manulife, StockImporter, HEADERS
from base.utils import DIYImportException, normalize_today, normalize_date
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


class TransactionDeleteView(LoginRequiredMixin, DeleteView):
    model = Transaction
    template_name = 'stocks/delete_transaction_confirm_delete.html'

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse_lazy('portfolio_details', kwargs = {'pk': self.object.portfolio.id})

    def post(self, request, *args, **kwargs):
        if "cancel" in request.POST:
            this = self.get_object()
            url = reverse_lazy('portfolio_details', kwargs = {'pk': this.portfolio.id})
            return HttpResponseRedirect(url)
        else:
            return super(TransactionDeleteView, self).post(request, *args, **kwargs)


class PortfolioTableView(LoginRequiredMixin, DetailView):
    model = Portfolio
    template_name = 'stocks/portfolio_table.html'

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
        p: Portfolio = context['portfolio']
        data = list()
        elist = p.equities.order_by('symbol')

        # Build the table data as [date, (shares, value), (shares, value)... total_value
        for this_date in p.e_pd.Date.unique():
            total_value = 0
            this_record = [this_date, 0]
            for equity in elist:
                try:
                    df = p.e_pd[(p.e_pd['Date'] == this_date) & (p.e_pd['Equity'] == equity.symbol)][['Shares', 'Value']]
                    if df.empty:
                        this_record.append((None, None))
                    else:
                        shares = df['Shares'].tolist()[0]
                        value = df['Value'].tolist()[0]
                        this_record.append((shares, value))
                        total_value += value

                except KeyError:
                    this_record.append((None, None))
            this_record[1] = total_value
            data.append(this_record)
        data.sort(reverse=True)
        return {'portfolio': p,
                'data': data,
                'equities': elist,
                'equity_count': elist.count()
                }


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

        funded = p.transactions.filter(xa_action=Transaction.FUND)
        redeemed = p.transactions.filter(xa_action=Transaction.REDEEM)
        if funded.count() == 0:
            funded = 0
        else:
            funded = funded.aggregate(Sum('value'))['value__sum']
        if redeemed.count() == 0:
            redeemed = 0
        else:
            redeemed = redeemed.aggregate(Sum('value'))['value__sum'] * -1
        return {'portfolio': p,
                'xas': p.transactions.order_by('-real_date', 'xa_action'),
                'can_update': can_update,
                'funded': funded,
                'redeemed': redeemed,
                }


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


class TransactionEdit(LoginRequiredMixin, UpdateView):
    model = Transaction
    #fields = ['real_date', 'xa_action', 'price', 'quantity', 'value']
    template_name = 'stocks/add_transaction.html'
    form_class = TransactionForm

    def get_object(self, queryset=None):
        return super().get_object(queryset=Transaction.objects.filter(user=self.request.user))

    def get_success_url(self):
        return reverse('portfolio_details', kwargs={'pk': self.object.portfolio.id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['view_verb'] = 'Edit'
        return context


class PortfolioEdit(LoginRequiredMixin, UpdateView, DateMixin):
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
def edit_transaction(request, pk):
    xa: Transaction = get_object_or_404(Transaction, pk=pk, user=request.user)

    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user})
        if form.is_valid():
            action = form.cleaned_data['xa_action']
            if action == Transaction.FUND or Transaction.REDEEM:
                xa.date = form.cleaned_data['date']
                xa.price = 0
                xa.quantity = 0
                xa.value = form.cleaned_data['value']
                xa.xa_action = form.cleaned_data['xa_action']
                xa.portfolio = form.cleaned_data['portfolio']
            else:
                xa.date = form.cleaned_data['date']
                xa.price = form.cleaned_data['price']
                xa.quantity = form.cleaned_data['quantity']
                xa.value = 0
                xa.xa_action = form.cleaned_data['xa_action']
                xa.portfolio = form.cleaned_data['portfolio']
            xa.save()


@login_required
def add_transaction(request):
    if request.method == 'POST':
        form = TransactionForm(request.POST, initial={'user': request.user})
        if form.is_valid():
            action = form.cleaned_data['xa_action']
            if action == Transaction.FUND or action == Transaction.REDEEM:
                value = form.cleaned_data['value']
                if (action == Transaction.FUND and value < 0) or (action == Transaction.REDEEM and value > 0):
                    value = value * -1
                new = Transaction.objects.create(user=request.user,
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=0,
                                                 value=value,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 portfolio=form.cleaned_data['portfolio'])

            elif (action == Transaction.BUY) or (action == Transaction.SELL):
                quantity = form.cleaned_data['quantity']
                if (action == Transaction.BUY and quantity < 0) or (action == Transaction.SELL and quantity > 0):
                    quantity = quantity * -1

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=form.cleaned_data['price'],
                                                 quantity=quantity,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 portfolio=form.cleaned_data['portfolio'])
            elif (action == Transaction.REDIV):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=form.cleaned_data['xa_action'],
                                                 portfolio=form.cleaned_data['portfolio'])
            elif (action == Transaction.FEES):
                quantity = form.cleaned_data['quantity']

                new = Transaction.objects.create(user=request.user,
                                                 equity=form.cleaned_data['equity'],
                                                 real_date=form.cleaned_data['real_date'],
                                                 price=0,
                                                 quantity=quantity,
                                                 xa_action=Transaction.SELL,
                                                 portfolio=form.cleaned_data['portfolio'])

            if 'submit-type' in form.data and form.data['submit-type'] == 'Add Another':
                form = TransactionForm(initial={'user': request.user,
                                                'portfolio': new.portfolio,
                                                'equity': new.equity.id,
                                                'real_date': new.real_date,
                                                'xa_action': new.xa_action})
            else:
                return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': new.portfolio.id}))
    else:  # Initial get
        form = TransactionForm(initial={'user': request.user})

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
def portfolio_equity_compare(request, pk, orig_id, compare_id):
    try:
        portfolio = Portfolio.objects.get(id=pk, user=request.user)
        compare_to = Equity.objects.get(id=compare_id)
        equity = Equity.objects.get(id=orig_id)
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = portfolio.transactions.filter(equity=equity) if equity else portfolio.transactions
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
        next_date = next_date + relativedelta.relativedelta(months=1)

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
    compare_to = None
    if request.method == 'POST':
        form = EquityForm(request.POST)
        if form.is_valid():
            compare_to = form.cleaned_data['equity']

    dividend_detail = dict(EquityEvent.objects.filter(event_type='Dividend', equity=equity).values_list('date', 'value'))
    value_detail = dict(EquityValue.objects.filter(equity=equity).values_list('date', 'price'))
    form = EquityForm()
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
    funded = portfolio.transactions.filter(equity=equity, xa_action__in=(Transaction.BUY, Transaction.SELL)).aggregate(Sum('value'))['value__sum']
    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data,
                   'portfolio': portfolio,
                   'equity': equity,
                   'funded': funded,
                   'dividends': total_dividends,
                   'form': form,
                   'compare_to': compare_to
                   })


def add_equity(request):

    if request.method == 'POST':
        form = AddEquityForm(request.POST)
        if form.is_valid():
            subject = f"New Equity Request {form.cleaned_data['symbol']}"
            body = 'Requestor:%s\nSymbol:%s\nDescription:%s\nRegion:%s\nType:%s' % (
                request.user,
                form.cleaned_data['symbol'], form.cleaned_data['description'],
                form.cleaned_data['region'], form.cleaned_data['equity_type'])

            email_message = EmailMessage(subject, body, request.user.email, [os.environ['DIY_EMAIL_USER']])
            email_message.send()

            Equity.objects.create(symbol=form.cleaned_data['symbol'], region=form.cleaned_data['region'],
                                  name=form.cleaned_data['description'], equity_type=form.cleaned_data['equity_type'],
                                  searchable=False, validated=True)

            return HttpResponseRedirect(reverse('portfolio_list'))

    else:  # Initial get
        form = AddEquityForm()

    context = {
        'form': form,
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
def get_equity_list(request):
    """
    API to get the proper set of equities base on the action, profile and date.
    For instance,  A Sell/Reinvest action can only affect the equities you hold on a specific date
    """
    this_date = datetime.now()
    action = None

    if request.GET.get("date"):
        try:
            this_date = datetime.strptime(request.GET.get("date"), '%Y-%m-%d')
        except ValueError:
            logger.error("Received a ill formed date %s" % request.GET.get("date"))

    if request.GET.get("action"):
        try:
            action = int(request.GET.get('action'))
        except ValueError:
            logger.error("Received a non-numeric action %s" % request.GET.get("action"))

    values = Equity.objects.exclude(deactived_date__gt=this_date)

    if action in [Transaction.SELL, Transaction.REDIV, Transaction.FEES]:
        try:
            portfolio = Portfolio.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
            this_date = normalize_date(this_date)
            subset = portfolio.e_pd.loc[portfolio.e_pd['Date'] == this_date]['Equity']
            values = values.filter(symbol__in=subset.values)
        except Portfolio.DoesNotExist:
            logger.error('Someone %s is poking around, looking for %s' * (request.user, request.GET.get("portfolio_id")))
            pass
        except ValueError:
            pass  # No value supplied

    value_dictionary = dict()
    for e in values.order_by('symbol'):
        value_dictionary[e.id] = e

    return render(request, "generic_selection.html", {"values": value_dictionary})


@login_required
def compare_equity_chart(request):

    try:
        portfolio = Portfolio.objects.get(id=request.GET.get("portfolio_id"), user=request.user)
        compare_to = Equity.objects.get(id=request.GET.get("compare_id"))
        equity = Equity.objects.get(id=request.GET.get("equity_id"))
    except:
        JsonResponse({'status': 'false', 'message': 'Server Error - Does Not Exist'}, status=404)

    xas = portfolio.transactions.filter(equity=equity) if equity else portfolio.transactions
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
        next_date = next_date + relativedelta.relativedelta(months=1)

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
                                               'borderColor': colors[0], 'backgroundColor': colors[0], 'tension': 0.1})
                chart_data['datasets'].append({'label': 'Effective Cost', 'fill': False,
                                               'data': p.p_pd['EffectiveCost'].tolist(),
                                               'borderColor': colors[1], 'backgroundColor': colors[1]})
                value = p.p_pd['Value'] + p.p_pd['Cash']
                chart_data['datasets'].append({'label': 'Value', 'fill': False,
                                               'data': value.tolist(),
                                               'borderColor': colors[3], 'backgroundColor': colors[3], 'tension': 0.1})

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
