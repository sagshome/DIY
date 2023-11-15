from django.forms import formset_factory
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect
from django.urls import reverse
from .models import Equity, Portfolio, Transaction, EquitySummary
from .forms import AddEquityForm, AddPortfolioForm, TransactionForm
from django.views import View
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, DetailView, CreateView, DeleteView, FormView
from datetime import datetime
# Create your views here.


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

    print(f'String is:{string} and Region is:{region}')

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
        print(kwargs)
        context = super().get_context_data(**kwargs)
        print(context)

        e_list = list()
        for equity in context['portfolio'].equities:
            e_list.append(EquitySummary(context['portfolio'], equity))
        context['equities'] = e_list
        return context


def portfolio_add(request):

    if request.method == 'POST':
        form = AddPortfolioForm(request.POST)
        if form.is_valid():
            new_portfolio = Portfolio.objects.create(name=form.cleaned_data['name'])
            return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': new_portfolio.id}))
    else:  # Initial get
        form = AddPortfolioForm(initial={'portfolio_name': 'New Portfolio'})

    context = {
        'form': form,
    }
    return render(request, 'stocks/add_portfolio.html', context)


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


class PortfolioBuy(CreateView):
    model = Transaction
    template_name = "stocks/add_bulk_equity.html"
    fields = ['equity', 'date', 'quantity', 'price']

    def get_initial(self):
        return {'date': datetime.now().date(), 'price': 1, 'quantity': 1}

    def form_valid(self, form):
        transaction = form.save(commit=False)
        transaction.portfolio_id = self.kwargs['pk']
        transaction.equity_fk = Equity.objects.get(key=transaction.equity)
        transaction.save()

        return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': self.kwargs['pk']}))


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


def portfolio_copy(request, pk):
    original = get_object_or_404(Portfolio, pk=pk)
    print(request.__dict__, pk)

    if request.method == 'POST':
        form = AddPortfolioForm(request.POST)
        if form.is_valid():
            new_portfolio = Portfolio.objects.create(name=form.cleaned_data['portfolio_name'])
            for t in Transaction.objects.filter(portfolio=original):
                Transaction.objects.create(portfolio=new_portfolio, equity_fk=t.equity, equity=t.equity, date=t.date, price=t.price,
                                           quantity=t.quantity, buy_action=t.buy_action)

            return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': new_portfolio.id}))
    else:  # Initial get
        form = AddPortfolioForm(initial={'portfolio_name': f'{original.name}_copy'})

    context = {
        'form': form,
        'portfolio': original,
    }
    return render(request, 'stocks/add_portfolio.html', context)


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
    """
    portfolio = get_object_or_404(Portfolio, pk=pk)
    equity = get_object_or_404(Equity, key=key)
    summary = EquitySummary(portfolio, equity)
    list_keys = sorted(summary.history, reverse=True)

    data = []
    for key in list_keys:
        extra_data = ''
        if summary.history[key].change != 0:
            if summary.history[key].change < 0:
                extra_data = f'Sold {summary.history[key].change} shares at ${summary.history[key].xa_price}'
            else:
                if summary.history[key].xa_price == 0:
                    extra_data = f'Received {summary.history[key].change} shares due to a stock split'
                else:
                    extra_data = f'Bought {summary.history[key].change} shares at ${summary.history[key].xa_price}'
        data.append([key, summary.history[key].shares, summary.history[key].value, summary.history[key].cost,
                     summary.history[key].dividends, summary.history[key].returns, summary.history[key].dividend,
                     summary.history[key].price, extra_data])

    return render(request, 'stocks/portfolio_equity_detail.html', {'context': data})


# def add_equity_to_portfolio(request, pk):
#     portfolio = get_object_or_404(Portfolio, pk=pk)
#     if request.method == 'POST':
#         if form.is_valid():
#             for form in formset:
#                 new = form.save(commit=False)
#                 new.portfolio = portfolio
#                 new.equity_fk = Equity.objects.get(key=new.equity)
#                 new.save()
#             return HttpResponseRedirect(reverse('portfolio_details', kwargs={'pk': portfolio.id}))
#
#     else:
#         formset = transaction_form_set
#     return render(request, 'stocks/add_bulk_equity.html', {'formset': formset,
#                                                            'portfolio': portfolio,
#                                                            'keys': formset.form.base_fields.keys()})


    # def add_equity(request, pk):
    #     if request.method == 'POST':
    #         form = AddEquityForm(request.POST)
    #         if form.is_valid():
    #             symbol = form.cleaned_data['symbol']
    #             equity = Equity.objects.create(name=form.cleaned_data['key'])
    #             return HttpResponseRedirect(reverse('portfolio_list'))
    #     else:  # Initial get
    #         form = AddEquityForm()
    #
    #     context = {
    #         'form': form,
    #         'symbol_list': {}
    #     }
    #     return render(request, 'stocks/add_equity.html', context)

#
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


# class TransactionFormView(CreateView):
#     model = Transaction
#     template_name = 'stocks/add_bulk_equity.html'
#     form_class = TransactionForm
#
#     def get_success_url(self):
#         return reverse('portfolio_details', kwargs={'pk': self.kwargs['pk']})
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         if self.request.POST:
#             context['new_player'] = TransactionFormSet(self.request.POST)
#         else:
#             context['new_player'] = TransactionFormSet()
#         return context
#
#     def form_valid(self, form):
#         context = self.get_context_data()
#         new_player_form = context['new_player']
#         if new_player_form.is_valid():
#             self.object = form.save()
#             new_player_form.instance = self.object
#             new_player_form.save()
#             # Additional logic if needed
#             return super().form_valid(form)
#         else:
#             return self.render_to_response(self.get_context_data(form=form))
