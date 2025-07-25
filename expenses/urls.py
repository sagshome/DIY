from django.urls import path

from . import views

# Base is expenses/
urlpatterns = [
    path(r'main/', views.expense_main, name='expense_main'),

    path(r'upload/', views.upload_expenses, name='expenses_upload'),
    path(r'upload/<uuid>/<headings>/confirm/', views.upload_confirm, name='upload_confirm'),
    path(r'upload/<uuid>/process/', views.upload_process, name='upload_process'),

    path(r'export/', views.export_expense_page, name='expenses_export'),
    path(r'export/download/', views.export_expenses, name='export_expense_page'),

    path(r'assign/', views.assign_expenses, name='expenses_assign'),

    path(r'expense/add/', views.ItemAdd.as_view(), name='expense_add'),
    path(r'expense/help', views.cash_help, name='cash_help'),
    path('subcategory/add/', views.SubCategoryAdd.as_view(), name='subcategory_add'),
    path(r'subcategory/<pk>/delete/', views.SubCategoryDelete.as_view(), name='subcategory_delete'),
    path('subcategory/list/', views.SubCategoryList.as_view(), name='subcategory_list'),

    path(r'expense/<int:pk>/edit/', views.ItemEdit.as_view(), name='expense_edit'),
    path(r'expense/<int:pk>/delete/', views.ItemDelete.as_view(), name='expense_delete'),

    path(r'template/', views.ListTemplates.as_view(), name='expenses_templates'),
    path(r'template/<int:item_pk>/add/', views.AddTemplateView.as_view(), name='add_template'),
    path(r'template/<int:pk>/delete/', views.DeleteTemplateView.as_view(), name='template_delete'),
    path(r'template/<int:pk>/edit/', views.edit_template, name='template_edit'),

    path('ajax/load-subcategories/', views.load_subcategories, name='ajax-load-subcategories'),
    path('ajax/load-subcategories-search/', views.load_subcategories_search, name='ajax-load-subcategories-search'),
    # path('ajax/load-categories-search/', views.load_categories_search, name='ajax-load-categories-search'),

    path('ajax/expense-pie', views.expense_pie, name='ajax-expense-pie'),
    path('ajax/expense-bar', views.expense_bar, name='ajax-expense-bar'),
    path('api/cash_flow', views.cash_flow_chart_v2, name='cash_flow_data')
]

