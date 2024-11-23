import copy
import decimal
import logging
import re

from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Union

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum, QuerySet

# Create your models here.

# This works VERY well
logger = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [('- ALL -', '- ALL -'), ('- NONE -', '- NONE -')]


class Category(models.Model):
    """
    Top level classification for expense categorization
    Income: 'Green' #2ECC71
    Other: Grey
    Personal Care: Yellow
    Transportation: Blue
    Recreation: Orange
    HealthCare
    Housing
    Utilities:
    Food: Green

    #2ECC71 (Green)
    #FF6F61 (Coral Red)
    #6B8E23 (Olive Drab)
    #4A90E2 (Sky Blue)
    #50E3C2 (Turquoise)
    #F5A623 (Golden Yellow)
    #9013FE (Purple)
    #D0021B (Red)
    #8B572A (Chestnut Brown)

    Color Overview:
    #FF6F61 (Coral Red) and #6B8E23 (Olive Drab) are complementary because they are on opposite sides of the color wheel, creating a striking contrast.
    #4A90E2 (Sky Blue) and #F5A623 (Golden Yellow) provide a warm-cool color pairing, which is visually dynamic but not jarring.
    #50E3C2 (Turquoise) complements #9013FE (Purple), providing a balance of cool hues with a slight pop of vivid color.
    #D0021B (Red) and #8B572A (Chestnut Brown) create a grounded, earthy combination that feels organic and balanced.


    Food: This category includes food purchased from stores, restaurants, and institutions, such as groceries, meals, and snacks.
    Shelter: This category includes housing costs, such as rent, mortgage interest, property taxes, and maintenance.
    Household operations, furnishings and equipment: This category includes costs for household supplies, appliances, and services, such as cleaning, laundry, and pest control.
    Clothing and footwear: This category includes costs for clothing, shoes, and accessories.
    Transportation: This category includes costs for vehicles, gasoline, maintenance, insurance, and public transportation.
    Health and personal care: This category includes costs for medical services, prescription drugs, and personal care items, such as toiletries and cosmetics.
    Recreation, education and reading: This category includes costs for entertainment, hobbies, and educational services, such as movies, concerts, and books.
    Alcoholic beverages, tobacco products and recreational cannabis: This category includes costs for beer, wine, spirits, tobacco products, and recreational cannabis.


    """
    name = models.CharField(unique=True, max_length=32, null=False, blank=False, verbose_name="Expense Category")
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)


    def __str__(self):
        return self.name


    # def filter_amount(self, qfilter: Union[QuerySet | None]) -> float:
    def filter_amount(self, qfilter) -> float:

        if not qfilter:
            qfilter = Item.objects.filter(category=self)
        value = qfilter.aggregate(sum=Sum('amount'))['sum']
        value = value if value else 0
        return value

    def filter_count(self, qfilter) -> int:
        if not qfilter:
            qfilter = Item.objects.filter(category=self)
        return qfilter.filter(category=self).count()


class SubCategory(models.Model):
    """
    Second level classification for expense categorization
    """
    name = models.CharField(max_length=32, null=False, blank=False, verbose_name="SubCategory")
    category = models.ForeignKey(Category, null=False, blank=False, verbose_name="Category", on_delete=models.CASCADE)
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("name", "category")

    def __str__(self):
        return self.name

    def filter_amount(self, qfilter) -> float:

        if not qfilter:
            qfilter = Item.objects.filter(subcategory=self)
        else:
            qfilter = qfilter.filter(subcategory=self)
        value = qfilter.aggregate(sum=Sum('amount'))['sum']
        value = value if value else 0
        return value

    def filter_count(self, qfilter) -> int:
        if not qfilter:
            qfilter = Item.objects.filter(subcategory=self)
        return qfilter.filter(subcategory=self).count()


class Template(models.Model):
    """
for t in Template.objects.all():
   ...:     c = t.missed
   ...:     if c.count()  != 0:
   ...:         for i in c:
   ...:             if i.template:
   ...:                 print (f'Item:{i} Existing Template:{i.template.type} {i.template} Also...{t.type} {t}')
   ...:             else:
   ...:                 print (f'Item:{i} Existing Template:----------  Also...{t.type} {t}')
    """

    CHOICES = [("", "-----"),
               ("starts", "Starts With"),
               ("ends", "Ends With"),
               ("contains", "Contains")]

    type = models.CharField(max_length=8, null=False, blank=False, choices=CHOICES)
    expression: str = models.CharField(max_length=120, blank=False, null=False)
    category = models.ForeignKey(Category, blank=True, null=True, on_delete=models.CASCADE)
    subcategory = models.ForeignKey(SubCategory, blank=True, null=True, on_delete=models.CASCADE)
    count = models.IntegerField(default=0)
    ignore = models.BooleanField(default=False)  # Used to indicate an expression is to ignore the item
    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)

    def __str__(self):
        return(self.expression)

    def save(self, *args, **kwargs):
        if self.ignore:
            self.category = None
            self.subcategory = None
        else:
            if not self.category or not self.subcategory:
                logger.critical('Attempting to save template without category and subcategory')
                return
        super().save(*args, **kwargs)

    @classmethod
    def choice(cls, value):
        for key, string in cls.CHOICES:
            if key == value:
                return string
        return "----"

    @classmethod
    def test_expression(cls, template_type, description, expression):
        if template_type == 'starts':
            return description.startswith(expression)
        if template_type == 'ends':
            return description.endswith(expression)
        return re.search(expression, description)

    def test_item(self, description: str):
        if Template.test_expression(self.type, description, self.expression):
            return self
        return None

    @classmethod
    def update_counts(cls):
        for t in Template.objects.all():
            usage = Item.objects.filter(template=t).count()
            if usage != t.count:
                t.count = usage
                t.save()

        Template.objects.filter(count=0).delete()

    def amount(self, queryset=None):
        if not queryset:
            queryset = Item.objects.all()
        value = queryset.filter(template=self).aggregate(sum=Sum('amount'))['sum']
        value = value if value else 0
        return value


class Item(models.Model):
    """
    One item will exist for each expense,   any item that does not have a category/subcategory will be process by
    applying templates on entry (import or single item)
    """
    date = models.DateField(null=False, blank=False, verbose_name="Date")
    description: str = models.CharField(max_length=120, null=False, blank=False)
    amount: decimal = models.DecimalField(null=False, max_digits=9, decimal_places=2, blank=False)
    source = models.CharField(max_length=40, null=False, blank=False)
    template = models.ForeignKey(Template, blank=True, null=True, on_delete=models.SET_NULL)
    category = models.ForeignKey(Category, blank=True, null=True, on_delete=models.SET_NULL)
    subcategory = models.ForeignKey(SubCategory, blank=True, null=True, on_delete=models.SET_NULL)
    details = models.CharField(max_length=80, blank=True, null=True)
    ignore = models.BooleanField(default=False)
    income = models.BooleanField(default=False)
    amortized = models.ForeignKey('Item', blank=True, null=True, on_delete=models.CASCADE, related_name='parent')
    split = models.ForeignKey('Item', blank=True, null=True, on_delete=models.CASCADE, related_name='split_from')

    user = models.ForeignKey(User, blank=True, null=True, on_delete=models.CASCADE)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        if self.template:
            return f'{self.date}: {self.description} - {self.amount} ({self.template.expression})'
        else:
            return f'{self.date}: {self.description} - {self.amount}'

    def save(self, *args, **kwargs):
        if self.category and self.category.name == 'Income':
            if self.amount < 0:
                self.amount *= -1
            self.income = True
        else:
            self.income = False

        super().save(*args, **kwargs)

    @property
    def can_delete(self) -> bool:
        """
        Split items
        """
        if self.split:
            siblings = Item.objects.filter(split=self.split).exclude(pk=self.pk)
            if siblings.count() == 1:
                if Item.objects.filter(split=siblings[0]).count() != 0:
                    return False
        return True

    @property
    def was_split(self) -> bool:
        return Item.objects.filter(split=self).count() != 0

    @property
    def is_split(self) -> bool:
        return self.split_id is not None

    @property
    def is_amortized(self) -> bool:
        return Item.objects.filter(amortized=self).count() != 0

    def split_item(self, amount: float, description: str) -> str:
        if amount > self.amount:
            error = 'Attempted to split %s with too large of an amount %s' % (self, amount)
            logger.error(error)
            return error

        if not description:
            description = self.description

        # new item
        Item.objects.create(date=self.date,
                            description=description,
                            amount=amount,
                            category=None,
                            subcategory=None,
                            ignore=False,
                            source='Split',
                            details=self.details,
                            user=self.user,
                            split=self)
        # remaining item
        if self.amount - amount != 0:
            Item.objects.create(date=self.date,
                                description=self.description,
                                amount=self.amount - amount,
                                category=None,
                                subcategory=None,
                                ignore=self.ignore,
                                source='Split',
                                details=self.details,
                                user=self.user,
                                split=self)
        return ''

    def amortize(self, months:int, direction:str = 'forward') -> str:
        if self.amortized:
            logger.error('Attempted to re-amoritize %s' % self)
            return 'Attempted to re-amoritize %s' % self
        if direction not in ['forward', 'backward', 'around']:
            logger.error('Invalid amortization value %s' % direction)
            return 'Invalid amortization value %s' % direction
        if months < 2:
            logger.error("Amortization must be at least two months")
            return "Amortization must be at least two months"

        new_amount = self.amount / months
        self.ignore = True
        self.save()

        if direction == 'forward':
            start_date = self.date
        elif direction == 'backward':
            start_date = self.date - relativedelta(months=months)
        else:
            start_date = self.date - relativedelta(months=months/2)

        for mcount in range(months):
            Item.objects.create(date=start_date + relativedelta(months=mcount),
                                description=self.description,
                                amount=new_amount,
                                category=self.category,
                                subcategory=self.subcategory,
                                ignore=False,
                                source='Amortized',
                                details=self.details,
                                user=self.user,
                                amortized=self)

        return ''

    def deamortize(self):
        Item.objects.filter(amortized=self).delete()
        self.ignore = False
        self.save()


    def apply_template(self, template: Template = None) -> bool:
        """
        Clear out template values and reapply,   return false if we no longer match the template
        """
        matched = None
        if template:
            matched = template.test_item(self.description)
        else:  # Try them all but don't be greedy
            for template in Template.objects.filter(Q(type='starts') | Q(type='ends')).order_by('count'):
                matched = template.test_item(self.description)
                if matched:
                    break
            if not matched:
                for template in Template.objects.filter(type='contains'):
                    matched = template.test_item(self.description)
                    if matched:
                        break
        self.set_template(matched)
        self.save()
        return matched

    @classmethod
    def apply_templates(cls, user):
        """
        For each item that has not been processed,  try all the templates to see if the item should be automatically
        categorized (or ignored).   The contains is 'greedy' so do those last.   Also use a count to order this list
        for efficiencies
        """
        items = Item.unassigned(user)
        starts_ends = list(Template.objects.filter(Q(type='starts') | Q(type='ends')).order_by('count').values())
        contains = list(Template.objects.filter(type='contains').order_by('count').values())

        for item in items:
            found = False
            for template in starts_ends:  # Short-circuit searches
                found = template['type'] == 'starts' and item.description.startswith(template["expression"])
                found = found | (template['type'] == 'ends' and item.description.endswith(template["expression"]))
                if found:
                    if template["ignore"]:
                        item.ignore = True
                    else:
                        item.category_id = template['category_id']
                        item.subcategory_id = template['subcategory_id']
                    item.template_id = template['id']
                    item.save()
                    break
            if not found:
                for template in contains:
                    if re.search(template["expression"], item.description):
                        if template["ignore"]:
                            item.ignore = True
                        else:
                            item.category_id = template['category_id']
                            item.subcategory_id = template['subcategory_id']
                        item.template_id = template['id']
                        item.save()
                        break
        Template.update_counts()

    def set_template(self, template: Template = None):
        self.category = None
        self.subcategory = None
        self.ignore = False

        if template:
            if template.ignore:
                self.ignore = True
            else:
                self.category = template.category
                self.subcategory = template.subcategory
            self.template = template
        else:
            self.template = None

    @classmethod
    def unassigned(cls, user):
        return Item.objects.filter(user=user).filter(Q(category__isnull=True) | Q(subcategory__isnull=True)).exclude(ignore=True)

    @classmethod
    def update_templates(cls):
        this_template = None
        for template in Template.objects.all().order_by("expression", "-count"):
            if this_template and this_template.expression == template.expression:
                if this_template.category == template.category and this_template.subcategory == template.subcategory:
                    Item.objects.filter(template=template).update(template=this_template)
                else:
                    logger.error('Template mismatch = ids: %s and %s' % (this_template.id, template.id))
            this_template = template
        Template.update_counts()

    @classmethod
    def filter_search(cls, item_filter, search_dict):
        '''
        This is kludged up to support Income searches
        '''
        income_search = True if ('income' in search_dict and search_dict['income'] == 'true' or
                                 'search_category' in search_dict and search_dict['search_category'] == 'Income') else False
        income_category = True if 'search_category' in search_dict and search_dict['search_category'] == 'Income' else False
        if 'search_description' in search_dict and search_dict['search_description']:
            item_filter = item_filter.filter(Q(description__icontains=search_dict['search_description']) |
                                             Q(notes__icontains=search_dict['search_description']))
        if 'search_category' in search_dict:
            if income_search:
                item_filter = item_filter.filter(category__name='Income')
            else:
                item_filter = item_filter.exclude(category__name='Income')
                category = search_dict['search_category']
                if category == '- NONE -':
                    item_filter = item_filter.filter(category__isnull=True)
                elif category != '- ALL -' and not income_category:
                    item_filter = item_filter.filter(category__name=category)
        if 'search_subcategory' in search_dict:
            if not income_search or income_search and income_category:
                subcategory = search_dict['search_subcategory']
                if subcategory == '- NONE -':
                    item_filter = item_filter.filter(subcategory__isnull=True)
                elif subcategory != '- ALL -' and not income_category:
                    item_filter = item_filter.filter(subcategory__name=subcategory)
        if 'search_ignore' in search_dict:
            if search_dict['search_ignore'] == 'Yes':
                item_filter = item_filter.filter(ignore=True)
            elif search_dict['search_ignore'] == 'No':
                item_filter = item_filter.filter(ignore=False)
        if 'search_start_date' in search_dict and search_dict['search_start_date']:
            item_filter = item_filter.filter(date__gte=search_dict['search_start_date'])
        if 'search_end_date' in search_dict and search_dict['search_end_date']:
            item_filter = item_filter.filter(date__lte=search_dict['search_end_date'])
        if 'search_amount' in search_dict and search_dict['search_amount']:  # todo: fix bug if 0
            if search_dict['search_amount_qualifier'] == 'equal':
                item_filter = item_filter.filter(amount=search_dict['search_amount'])
            elif search_dict['search_amount_qualifier'] == 'lte':
                item_filter = item_filter.filter(amount__lte=search_dict['search_amount'])
            elif search_dict['search_amount_qualifier'] == 'gte':
                item_filter = item_filter.filter(amount__gte=search_dict['search_amount'])

        item_filter = item_filter.order_by('-date')
        return item_filter

