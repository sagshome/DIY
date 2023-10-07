from django.shortcuts import render
from django.http import HttpResponse
from .models import Equity

# Create your views here.

def index(request):
    return HttpResponse("You are in the stocks index")

def search(request, text):
    response = Equity.lookup(text)
    return HttpResponse(response)