import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wmc_inventar.settings')
django.setup()
from django.urls import resolve
r = resolve('/geraete/verleih/1/genehmigen/')
print("Func:", r.func.__name__)
print("Kwargs:", r.kwargs)
