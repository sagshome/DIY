from django.shortcuts import render


def diy_main(request):
    return render(request, "diy_main.html")
