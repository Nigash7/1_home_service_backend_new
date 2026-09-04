from django.urls import path

from .views import (
    MyBidsListView,
    MyProjectsListView,
    MyTendersListView,
    OpenTendersListView,
    TenderAttachmentDeleteView,
    TenderAttachmentUploadView,
    TenderBidAcceptView,
    TenderBidsListView,
    TenderCancelView,
    TenderCompleteView,
    TenderConfirmationFeeView,
    TenderConfirmationVerifyView,
    TenderCreateView,
    TenderDetailView,
    TenderMilestonePayView,
    TenderMilestoneReachView,
    TenderMyBidView,
    TenderProgressCreateView,
    TenderProgressListView,
    TenderPublishView,
    TenderReviewView,
    TenderStartView,
)

urlpatterns = [
    # ---- Customer: post a requirement ----
    path('', TenderCreateView.as_view(), name='tender-create'),
    path('my/', MyTendersListView.as_view(), name='tender-my-list'),

    # ---- Vendor: browse and track ----
    # Ahead of '<int:pk>/' so these words are never read as an ID.
    path('open/', OpenTendersListView.as_view(), name='tender-open-list'),
    path('my-bids/', MyBidsListView.as_view(), name='tender-my-bids'),
    path('awarded/', MyProjectsListView.as_view(), name='tender-awarded-list'),

    # ---- Confirmation fee ----
    # Ahead of '<int:pk>/' for the same reason as the words above.
    path('confirmation/verify/', TenderConfirmationVerifyView.as_view(),
         name='tender-confirmation-verify'),

    # ---- Bids and milestones by their own ID ----
    path('bids/<int:pk>/accept/', TenderBidAcceptView.as_view(), name='tender-bid-accept'),
    path('milestones/<int:pk>/reach/', TenderMilestoneReachView.as_view(), name='tender-milestone-reach'),
    path('milestones/<int:pk>/pay/', TenderMilestonePayView.as_view(), name='tender-milestone-pay'),
    path('attachments/<int:pk>/', TenderAttachmentDeleteView.as_view(), name='tender-attachment-delete'),

    # ---- One tender ----
    path('<int:pk>/', TenderDetailView.as_view(), name='tender-detail'),
    path('<int:pk>/publish/', TenderPublishView.as_view(), name='tender-publish'),
    path('<int:pk>/cancel/', TenderCancelView.as_view(), name='tender-cancel'),
    path('<int:pk>/attachments/', TenderAttachmentUploadView.as_view(), name='tender-attachment-upload'),
    path('<int:pk>/bids/', TenderBidsListView.as_view(), name='tender-bids-list'),
    path('<int:pk>/confirmation/', TenderConfirmationFeeView.as_view(),
         name='tender-confirmation'),
    path('<int:pk>/bid/', TenderMyBidView.as_view(), name='tender-my-bid'),

    # ---- Execution ----
    path('<int:pk>/start/', TenderStartView.as_view(), name='tender-start'),
    path('<int:pk>/progress/', TenderProgressListView.as_view(), name='tender-progress-list'),
    path('<int:pk>/progress/add/', TenderProgressCreateView.as_view(), name='tender-progress-add'),
    path('<int:pk>/complete/', TenderCompleteView.as_view(), name='tender-complete'),
    path('<int:pk>/review/', TenderReviewView.as_view(), name='tender-review'),
]
