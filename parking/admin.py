from django.contrib import admin

from .models import Booking, Lot, ParkingSlot, Place


class LotInline(admin.TabularInline):
    model = Lot
    extra = 1


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'area', 'city', 'price_per_hour', 'rating', 'is_active')
    list_filter = ('category', 'city', 'is_active')
    search_fields = ('name', 'area', 'city', 'address', 'keywords')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [LotInline]


@admin.register(Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = ('place', 'code', 'name', 'walk')
    list_filter = ('place',)
    search_fields = ('place__name', 'name')


@admin.register(ParkingSlot)
class ParkingSlotAdmin(admin.ModelAdmin):
    list_display = ('code', 'place', 'lot', 'vehicle_type', 'is_disabled')
    list_filter = ('place', 'lot', 'vehicle_type', 'is_disabled')
    search_fields = ('code', 'place__name')


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('reference', 'user', 'place_name', 'slot', 'starts_at', 'ends_at', 'fee', 'status')
    list_filter = ('status', 'slot__place', 'slot__lot')
    search_fields = ('reference', 'vehicle_plate', 'user__email', 'slot__place__name')
    readonly_fields = ('reference', 'created_at', 'cancelled_at')

    @admin.display(description='Place')
    def place_name(self, booking):
        return booking.slot.place.name
