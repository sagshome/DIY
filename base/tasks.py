import logging
import random

from celery import shared_task
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from phonenumbers import PhoneNumber

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Sum
from django.db.models.functions import TruncMonth, TruncYear

from base.models import Profile
from expenses.models import Item, Category, SubCategory
from stocks.models import Inflation, Portfolio, Account, Equity, Transaction, EquityValue, Equity, Inflation, ExchangeRate, Account


logger = logging.getLogger(__name__)


def create_expenses(user: User):
    """
    Rebuild 10 years of expense data.
    - Using inflation values to make it more dynamic
    - Using django bulk create was causing issues so I stop it.  This is much slower but since it runs late in the evening.  Its not a big deal I guess

    """
    # Your cleanup logic here
    seed_data = (
        ("Food", "Grocery", 1, 21, "day", 50),
        ("Food", "TakeOut", 15, 10, "day", 25),
        ("Food", "Dinning", 12, 51, "day", 25),
        ("Housing", "Maintenance", 16, 97, "day", 50),
        ("Housing", "Appliances/Furniture", 40, 125, "day", 50),
        ("Housing", "Appliances/Furniture", 300, 1500, "day", 15),
        ("Housing", "Other", 7, 27, "day", 75),
        ("Healthcare", "Dental", 121, 182, "day", 10),
        ("Healthcare", "Other", 182, 43, "day", 15),
        ("Recreation", "Events", 60, 79, "day", 40),
        ("Recreation", "Computers/Tech", 73, 280, "day", 50),
        ("Recreation", "Other", 14, 29, "day", 50),
        ("Transportation", "Fuel", 7, 75, "day", 15),
        ("Transportation", "Maintenance", 40, 249, "day", 30),
        ("Transportation", "Parking/Tolls", 52, 9, "day", 75),
        ("Personal Care", "Beauty", 45, 134, "day", 10),
        ("Personal Care", "Clothing", 18, 50, "day", 25),
        ("Personal Care", "Other", 7, 15, "day", 50),
        ("Other", "Unknown", 7, 20, "day", 75),
        ("Utilities", "Water", 3, 111, "month", 10),
        ("Utilities", "Electricity", 5, 74, "month", 15),
        ("Utilities", "Heat", 10, 155, "month",  20),
        ("Utilities", "Telecom", 16, 140, "month",  5),
        ("Housing", "Mortgage/Rent", 20, 2200, "month", ),
        ("Transportation", "Lease/Purchase", 22, 500, "month", ),
        ("Healthcare", "Insurance", 25, 152, "month", ),
        ("Recreation", "Streaming", 4, 52, "month", ),
        ("Personal Care", "Fitness", 1, 60, "month", ),
        ("Transportation", "Fees", 120, 32, "year"),
        ("Housing", "Insurance", 210, 900, "year", 5),
        ("Recreation", "Insurance", 95, 400, "year", 5),
        ("Transportation", "Insurance", 210, 1200, "year",),
        ("Housing", "Taxes", 30, 2315, "year",),
        ("Housing", "Taxes", 260, 2315, "year",),
        ("Income", "Government Programs", 10, 171, "year",),
        ("Income", "Government Programs", 100, 171, "year",),
        ("Income", "Government Programs", 190, 171, "year",),
        ("Income", "Government Programs", 270, 171, "year",),
    )
    logger.debug('Cleaning old expenses')
    Item.objects.filter(user=user).delete()
    logger.debug('Creating new expenses')
    seed_date = datetime(2024,10,1).date()
    end_date = datetime.today().date()
    start_date = end_date.replace(year=end_date.year-10)
    for entry in seed_data:
        cat = Category.objects.get(name=entry[0])
        sub = SubCategory.objects.get(name=entry[1], category=cat)
        interval = entry[2]
        value = entry[3]
        entry_type = entry[4]
        if len(entry) > 5:
            lower_limit = int(value - value * entry[5] / 100)
            upper_limit = int(value + value * entry[5] / 100)
        else:
            lower_limit = 0

        if entry_type == 'day':
            next_date = start_date
        elif entry_type == 'month':
            next_date = start_date.replace(day=interval)
        else:  # entry_type == 'year'
            next_date = start_date.replace(month=1).replace(day=1) + timedelta(days=interval)

        while next_date < end_date:
            if lower_limit != 0:
                newvalue = random.randint(lower_limit, upper_limit)
            else:
                newvalue = value

            newvalue = Inflation.inflated(newvalue, seed_date, next_date.replace(day=1))

            logger.debug(f'user={user}, category={cat}, subcategory={sub}, date={next_date}, amount={newvalue}')
            Item.objects.create(user=user, category=cat, subcategory=sub, date=next_date, amount=newvalue, description='Random Data')


            if entry_type == 'day':
                next_date = next_date + timedelta(days=interval)
            elif entry_type == 'month':
                next_date = next_date + relativedelta(months=1)
            elif entry_type == 'year':
                next_date = next_date + relativedelta(years=1)


def create_salary(user: User):
    end_date = datetime.today().date()
    start_date = end_date.replace(year=end_date.year-10)

    logger.debug('Creating new salary')
    expenses = Item.objects.filter(user=user).exclude(category__name='Income'). \
        annotate(year=TruncYear('date')).values('year'). \
        annotate(sum=Sum('amount')).values('year', 'sum')
    starting_salary = round(expenses[1]['sum'] / 24, -3)  # 12 months * 2 pay / month
    logger.debug('Starting Income')
    sal1 = float(starting_salary / 4)
    sal2 = float(starting_salary) - sal1
    cat = Category.objects.get(name='Income')
    sub = SubCategory.objects.get(name='Salary')
    next_date = start_date.replace(day=1)
    while next_date < end_date:
        if next_date.month == 1:  # Sal1 gets a raise
            sal1 += sal1 * (random.randint(0, 6) / 100)
        elif next_date.month == 5:
            sal2 += sal2 * (random.randint(0, 4) / 100)


        Item.objects.create(user=user, category=cat, subcategory=sub, date=next_date.replace(day=1), amount=sal1, description='Dan')
        Item.objects.create(user=user, category=cat, subcategory=sub, date=next_date.replace(day=15), amount=sal1, description='Dan')

        Item.objects.create(user=user, category=cat, subcategory=sub, date=next_date.replace(day=8), amount=sal2, description='Debbie')
        Item.objects.create(user=user, category=cat, subcategory=sub, date=next_date.replace(day=22), amount=sal2, description='Debbie')
        next_date = next_date + relativedelta(months=1)


def create_portfolios(user: User):
    end_date = datetime.today().date()
    start_date = end_date.replace(year=end_date.year-10)

    logger.debug('Start Investing')

    portfolio1 = Portfolio.objects.create(user=user, name='Company Retirement', currency='CAD')
    account1 = Account.objects.create(user=user, name="Dan's Account", account_type='Value', currency='CAD', account_name='Foo_007', managed=True, portfolio=portfolio1)
    account2 = Account.objects.create(user=user, name="Debbie's Account", account_type='Value', currency='CAD', account_name='Bar_007', managed=True, portfolio=portfolio1)
    for pay in Item.objects.filter(user=user, description__icontains='Dan', subcategory__name='Salary'):
        Transaction(account=account1, user=user, real_date=pay.date, xa_action=Transaction.FUND, value=float(pay.amount) * 16 / 100)
    for pay in Item.objects.filter(user=user, description__icontains='Debbie', subcategory__name='Salary'):
        Transaction(account=account2, user=user, real_date=pay.date, xa_action=Transaction.FUND, value=float(pay.amount) * 8 / 100)



#@shared_task
def daily_refresh():
    logger.debug('Starting Refresh')
    User.objects.filter(email=settings.EMAIL_HOST_USER).delete()
    logger.debug('Demo User Deleted')
    User.objects.create(email=settings.EMAIL_HOST_USER, first_name='Demo', last_name='Dan', username='demo')
    user = User.objects.get(email=settings.EMAIL_HOST_USER)
    user.set_password('demo')
    user.save()

    Profile.objects.create(user=user,  country='CA',  phone_number=PhoneNumber(country_code=1, national_number=2345678910),
                           address1='123 Fake Street', city='Brampton', state='ON', postal_code='HOH OHO',
                           birth_date=datetime.now().replace(year=datetime.now().year - 39).date())

    create_expenses(user)
    create_salary(user)


