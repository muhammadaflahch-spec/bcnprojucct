from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='dashboard'),
    path('place/<slug:slug>/', views.index, {'page': 'place'}, name='place'),
    path('bookings/', views.index, {'page': 'bookings'}, name='bookings'),
    path('admin-panel/', views.index, {'page': 'admin'}, name='admin-panel'),
    path('api/overview/', views.overview),
    path('api/places/', views.places),
    path('api/places/<slug:slug>/', views.place_detail),
    path('api/auth/login/', views.sign_in),
    path('api/auth/register/', views.register),
    path('api/auth/demo/', views.demo_sign_in),
    path('api/auth/logout/', views.sign_out),
    path('api/bookings/', views.create_booking),
    path('api/bookings/<int:booking_id>/cancel/', views.cancel_booking),
    path('api/bookings/<int:booking_id>/calendar/', views.booking_calendar),
    path('api/admin/overview/', views.admin_overview),
    path('api/admin/places/', views.admin_add_place),
    path('api/admin/places/<int:place_id>/', views.admin_update_place),
    path('api/admin/slots/', views.admin_add_slot),
    path('api/admin/slots/<int:slot_id>/', views.admin_update_slot),
    path('api/admin/bookings/<int:booking_id>/cancel/', views.admin_cancel_booking),
    path('api/admin/export/', views.export_bookings),
]
