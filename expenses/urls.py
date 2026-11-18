from django.urls import path

from . import views

# Base is expenses/
urlpatterns = [
    # path(r"main/", views.expense_main, name="expense_main"),
    path(r"main/", views.ExpenseMainView.as_view(), name="expense_main"),
    path(r"details/", views.DetailEditView.as_view(), name="detail_edit"),

    path(r"upload/", views.upload_expenses, name="expenses_upload"),
    path(r"upload/<uuid>/<headings>/confirm/",views.upload_confirm, name="upload_confirm",),
    path(r"upload/<uuid>/process/", views.upload_process, name="upload_process"),

    path(r"export/", views.export_expense_page, name="expenses_export"),
    path(r"export/download/", views.export_expenses, name="export_expense_page"),

    #path(r"assign/", views.assign_expenses, name="expenses_assign"),
    path(r"assign/", views.DetailEditView.as_view(assigning=True), name="expenses_assign"),
    path(r"add/", views.ItemAdd.as_view(), name="expense_add"),
    path(r"listdup/", views.ItemDups.as_view(), name="expense_dups"),
    path(r"help", views.cash_help, name="cash_help"),

    path(r"subcategories/", views.SubCategoryUpdateView.as_view(), name="subcategory_updates",),
    path(r"tags/", views.TagUpdateView.as_view(), name="tag_updates"),

    path(r"expense/<int:pk>/edit/", views.ItemEdit.as_view(), name="expense_edit"),
    path(r"expense/<int:pk>/split/", views.ItemSplit.as_view(), name="expense_split"),
    path(r"expense/<int:pk>/unsplit/", views.ItemUnSplit.as_view(), name="expense_unsplit"),
    path(r"expense/<int:pk>/delete/", views.ItemDelete.as_view(), name="expense_delete"),
    path(r"expense/<int:pk>/amortize", views.ItemAmortize.as_view(), name="expense_amortize"),
    path(r"expense/<int:pk>/unamortize", views.ItemUnAmortize.as_view(), name="expense_unamortize"),

    path(r"template/", views.ListTemplates.as_view(), name="expenses_templates"),
    path(r"template/<int:item_pk>/add/", views.AddTemplateView.as_view(), name="add_template",),
    #path(r"template/<int:pk>/edit/", views.edit_template, name="template_edit"),

    path("ajax/load-subcategories/", views.load_subcategories, name="ajax-load-subcategories"),
    path("ajax/load-subcategories-search/", views.load_subcategories_search, name="ajax-load-subcategories-search"),

    path("ajax/expense-pie", views.ExpensePieView.as_view(), name="ajax-expenses_pie"),
    path("ajax/expense-bar", views.ExpenseBarView.as_view(), name="ajax-expense-bar"),  # from expense_chart.js
    path("api/cash_flow", views.cash_flow_chart_v2, name="cash_flow_data"),
    path("api/expense/<int:pk>/tags/", views.expense_tags_api, name="set_tags"),
]

