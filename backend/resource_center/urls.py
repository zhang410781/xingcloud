from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r'types', views.ResourceTypeViewSet, basename='resource-type')
router.register(r'resources', views.ResourceViewSet, basename='resource')
router.register(r'relations', views.ResourceRelationViewSet, basename='resource-relation')
router.register(r'contacts', views.ResourceContactViewSet, basename='resource-contact')
router.register(r'discovery-sources', views.DiscoverySourceViewSet, basename='discovery-source')
router.register(r'discovery-runs', views.DiscoveryRunViewSet, basename='discovery-run')
router.register(r'nodes', views.ResourceNodeViewSet, basename='resource-node')

urlpatterns = [path('', include(router.urls))]
