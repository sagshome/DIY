from datetime import datetime
from django.http import JsonResponse
from django.urls import reverse

from base.forms import ModalForm
from base.ioom_dates import IOOMDates, IOOM_RANGES

import logging
logger = logging.getLogger(__name__)

from django import forms

class BootstrapFormMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            widget = field.widget

            if isinstance(widget, forms.Select):
                css_class = 'form-select'

            elif isinstance(widget, (forms.CheckboxInput,
                                     forms.RadioSelect,
                                     forms.CheckboxSelectMultiple)):
                css_class = 'form-check-input'

            elif isinstance(widget, forms.HiddenInput):
                continue

            else:
                css_class = 'form-control'

            existing = widget.attrs.get('class', '')

            if css_class not in existing.split():
                widget.attrs['class'] = f'{existing} {css_class}'.strip()

class ContextMixinBase:
    """
    This must be the last Mixin on the views
    Ensure the starting point of context
    Ensure required test variables are defined
    """

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.explicit_date = None
        self.reconcile_view = False

        if "explicit_date" in self.request.GET:
            date_parm = self.request.GET.get("explicit_date")
            formats = ["%Y-%b", "%b-%Y", "%b-%y", "%b-%y"]
            for this_format in formats:
                try:
                    self.explicit_date = datetime.strptime(date_parm, this_format)
                    break
                except ValueError:
                    pass

        if "range" in self.request.GET:
            wealth_range = self.request.GET.get("range")
            if wealth_range in IOOM_RANGES:
                self.request.session["wealth_range"] = wealth_range
        self.wealth_range = self.request.session.get("wealth_range", "year")

    def get_context_data(self, **kwargs):
        context = {}
        context["range"] = self.wealth_range
        context["range_string"] = IOOMDates.range_to_string(self.wealth_range)
        context["explicit_date"] = self.explicit_date
        return context

class RangeMixin:
    """
    Consistently support range= as a url parameter, default value is "year"
    """
    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

        if "range" in self.request.GET:
            r = self.request.GET.get("range")
            if r in IOOM_RANGES:
                self.request.session["ioom_range"] = r

        self.ioom_range = self.request.session.get("ioom_range", "year")

        dates = IOOMDates(build=False)
        self.start_date = dates.range_start(self.ioom_range)
        self.end_date = dates.range_end(self.ioom_range)

    def get_context_data(self, **kwargs):
        try:
            context = super().get_context_data(**kwargs)
        except:
            logger.debug('No super for get_context_data')
            context = {}

        context["range"] = self.ioom_range
        context["range_string"] = IOOMDates.range_to_string(self.ioom_range)
        return context

class ModalMixin:
    """
    Used for Create/Update/Delete/List/Detail Views
    """
    modal_form_class = ModalForm

    def get_modal_form(self):
        if not hasattr(self, '_modal_form'):
            data = self.request.POST if self.request.method == 'POST' else None

            initial = {
                'caller': self.request.META.get('HTTP_REFERER', '/'),
            }

            self._modal_form = self.modal_form_class(
                data=data,
                initial=initial
            )

        return self._modal_form

    def get_context_data(self, **kwargs):
        try:
            context = super().get_context_data(**kwargs)
        except AttributeError:
            context = {}

        context["modal"] = self.get_modal_form()
        context['modal_form'] = self.get_modal_form()
        return context

    def get_success_url(self):
        """
        todo:  validate the self.modal_caller value,  just incase someone is farting around with the form data
        """
        return self.modal_caller if self.modal_caller else super().get_success_url()

    @property
    def is_modal(self):
        form = self.get_modal_form()
        if form.is_bound:
            return form['is_modal'].value() in (True, 'true', 'True', 'on', '1')
        return bool(form.initial.get('is_modal'))

    @property
    def modal_caller(self):
        return self.get_modal_form()['caller'].value()


class ModalBaseMixin:
    """
    Used for CreateView and UpdateView
    """
    def form_valid(self, form):
        return JsonResponse({"ok": True, "redirect": self.get_success_url()})

    def form_invalid(self, form):
        return JsonResponse({'ok': True, 'errors': form.errors})
