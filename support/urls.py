from django.urls import path
from .views import (
    MyTicketsListView, CreateTicketView,
    TicketDetailView, AddTicketMessageView,
)

urlpatterns = [
    path('my/', MyTicketsListView.as_view(), name='my-tickets'),
    path('create/', CreateTicketView.as_view(), name='create-ticket'),
    path('<int:pk>/', TicketDetailView.as_view(), name='ticket-detail'),
    path('<int:ticket_id>/message/', AddTicketMessageView.as_view(), name='add-ticket-message'),
]