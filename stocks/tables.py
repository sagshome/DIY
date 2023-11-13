import django_tables2 as tables
from .models import Portfolio

class PortfolioTable(tables.Table):
    class Meta:
        model = Portfolio
        template_name = 'django_tables2/bootstrap.html'
        fields = ('name', 'cost', 'value')