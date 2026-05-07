import logging
import pandas as pd
from django.core.management.base import BaseCommand
from base.models import API
from stocks.models import Account, Portfolio, Transaction, EquityValue, FundValue, DataSource, Account
from pathlib import Path
logger = logging.getLogger(__name__)

accounts = {account.id: account for account in Account.objects.all()}

class Command(BaseCommand):
    help = 'Dump all Transactions in a format useful to re-import'

    def handle(self, *args, **options):
        df = pd.DataFrame(API.objects.values())
        output_file = Path.home().joinpath('API.csv')
        df.to_csv(output_file, index=False)

        df = pd.DataFrame(Account.objects.values(
            'id', 'name', 'currency', 'account_type', 'account_name', 'managed', 'portfolio__id', 'portfolio__name', 'portfolio__currency', 'user__username'))
        output_file = Path.home().joinpath('Accounts.csv')
        df.to_csv(output_file, index=False)

        df = pd.DataFrame(Transaction.objects.values(
            'account__id', 'equity__symbol', 'equity__name', 'real_date', 'price', 'quantity', 'value', 'xa_action', 'estimated'))
        df["action"] = df["xa_action"].map(Transaction.TRANSACTION_MAP)
        output_file = Path.home().joinpath('Transactions.csv')
        df.to_csv(output_file, index=False)

        df = pd.DataFrame(EquityValue.objects.filter(source__lt=DataSource.ESTIMATE.value).values('equity__symbol', 'real_date', 'price', 'split_fixed', 'source'))
        output_file = Path.home().joinpath('EquityValues.csv')
        df.to_csv(output_file, index=False)

        fixed_dict = []
        for rec in FundValue.objects.filter(source__lt=DataSource.ESTIMATE.value).values('equity__symbol', 'real_date', 'value', 'source'):
            _, acct_id = rec['equity__symbol'].split('-')
            rec['account__id'] = int(acct_id)
            fixed_dict.append(rec)
        df = pd.DataFrame(fixed_dict)

        output_file = Path.home().joinpath('FundValues.csv')
        df.to_csv(output_file, index=False)






