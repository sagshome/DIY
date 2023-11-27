import plotly.express as px
import plotly.io as pio

from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, DetailView, CreateView, DeleteView


from .models import Equity, Portfolio, Transaction
from .forms import AddEquityForm, TransactionForm


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
        equity_data = dict()
        for equity in p.equities:
            equity_data[equity.key] = p.data[equity.key].current_data
        context['equities'] = equity_data
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
    fields = ['name']
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
            Transaction.objects.create(portfolio=self.object, equity_fk=t.equity_fk, equity=t.equity, date=t.date,
                                       price=t.price,
                                       quantity=t.quantity, buy_action=t.buy_action)

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
                                             portfolio=portfolio,
                                             equity_fk=equity)
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


def portfolio_compare(request, pk, green_grass, drip):
    portfolio = get_object_or_404(Portfolio, pk=pk)
    # for equity in portfolio.equities:
    #
    #
    # if value == 'GIC':
    #     pass  # not implemented
    # elif value == 'Inflation':
    #     pass  # not implemented
    # else:
    #     try:
    #         equity = Equity.objects.get(key=value)
    #     except Equity.DoesNotExist:
    #         equity = Equity.objects.create(key=value)
    #     transactions = TransactionHistory(portfolio=portfolio


def equity_update(request,  key):
    """

    :param request:
    :param pk:
    :param key:
    :return:
    """
    equity = get_object_or_404(Equity, key=key)
    equity.update()
    return HttpResponse(status=200)


def portfolio_equity_details(request, pk, key):
    """

    :param request:
    :param pk:
    :param key:
    :return:

    table = pd.pivot_table(p.pd, values=['Cost', 'Value', 'TotalDividends'], index='Date', aggfunc='sum')


>>> df2 = p.pd.loc[:, ['Date', 'Value', 'Equity']]
>>> pt2 = pd.pivot_table(df2, values='Value', index='Date', columns='Equity', aggfunc='sum')
>>> pt2.reset_index(inplace=True)
>>> fig2 = px.line(pt2, x='Date', y=['BCE.TRT', 'BMO.TRT', 'CM.TRT',  'CU.TO', 'EMA.TO','ENB.TO', 'MFC.TRT', 'POW.TRT'], title='FooBar')
>>> fig2.show()Opening in existing browser session.
>>> fig2.show()

    import plotly.express as px
import plotly.io as pio

def my_view(request):
    fig = px.scatter(x=[1, 2, 3], y=[4, 5, 6])
    chart_html = pio.to_html(fig, full_html=False)
    context = {'chart_html': chart_html}
    return render(request, 'my_template.html', context)

<div>
    {{ chart_html|safe }}
</div>

    """
    portfolio = get_object_or_404(Portfolio, pk=pk)
    equity = get_object_or_404(Equity, key=key)
    #summary = EquitySummary(portfolio, equity)
    #list_keys = sorted(summary.history, reverse=True)
    data = []
    chart_html = '<p>No chart data available</p>'

    for element in portfolio.pd.loc[portfolio.pd['Equity'] == equity.key].to_records():
        extra_data = ''
        if element['Date'] in portfolio.transactions[equity.key]:
            xa = portfolio.transactions[equity.key][element['Date']]
            if xa.quantity < 0:
                extra_data = f'Sold {xa.quantity} shares at ${xa.price}'
            else:
                if xa.price == 0:
                    extra_data = f'Received {xa.quantity} shares due to a stock split'
                else:
                    extra_data = f'Bought {xa.quantity} shares at ${xa.price}'

        data.append([element['Date'], element['Shares'], element['Value'], element['Cost'],
                     element['TotalDividends'], element['Yield'], element['Dividend'],
                     element['Value'] / element['Shares'], extra_data])
        data.reverse()

        new = portfolio.pd.loc[portfolio.pd['Equity'] == equity.key]
        new2 = new.loc[:, ['Date', 'Cost', 'Value', 'TotalDividends']]
        new2.set_index('Date', inplace=True)

        # Create a line chart
        fig = px.line(new2, title=f'{equity}: Cost, Value, and Yield Over Time')
        chart_html = pio.to_html(fig, full_html=False)
    return render(request, 'stocks/portfolio_equity_detail.html',
                  {'context': data, 'chart': chart_html})


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
