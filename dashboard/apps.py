# from django.apps import AppConfig


# class DashboardConfig(AppConfig):
#     default_auto_field = 'django.db.models.BigAutoField'
#     name = 'dashboard'

#     def ready(self):
#         from django.contrib import admin
#         from django.shortcuts import redirect

#         original_index = admin.site.index

#         def custom_index(request, extra_context=None):
#             return redirect('/admin/dashboard/')

#         admin.site.index = custom_index

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dashboard'