import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse

from expenses.models import Template, Item
from wealth.models import Transaction, Funding, CashFlow, ValueBalance, clear_caches
from wealth.models import clear_caches

logger = logging.getLogger(__name__)


@login_required
def delete_action(request):

    action_id = request.GET.get("action_id", None)
    action_type = request.GET.get("action_type", None)
    if action_id and action_type:
        action = Transaction.objects.none
        if action_type in ['XA', 'Buy', 'Sell']:
            action = Transaction.objects.filter(id=action_id, account__user=request.user)
        elif action_type in ['FUND', 'Withdraw', 'Deposit']:
            action = Funding.objects.filter(id=action_id, account__user=request.user)
        elif action_type in ['CASH', 'Balance']:
            action = CashFlow.objects.filter(id=action_id, account__user=request.user)
        elif action_type == 'VALUE':
            action = ValueBalance.objects.filter(id=action_id, account__user=request.user)
        elif action_type == 'Template':
            action = Template.objects.filter(id=action_id, user=request.user)
        elif action_type == 'Item':
            action = Item.objects.filter(id=action_id, user=request.user)

        if action.count() == 1:  # It could be 0 I guess
            action.delete()
            if request.POST.get("refresh", False):
                clear_caches(user=request.user)
            return HttpResponse(status=200)
    return HttpResponse(status=404)