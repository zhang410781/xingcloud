"""cmdb stub"""
from django.db import models

class ConfigItem(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, default='')
    class Meta:
        app_label = 'ops'
        managed = False

class ResourceNode(models.Model):
    NODE_TYPE_CHOICES = [('biz', 'biz'), ('env', 'env')]
    id = models.AutoField(primary_key=True)
    node_type = models.CharField(max_length=32, choices=NODE_TYPE_CHOICES, default='biz')
    name = models.CharField(max_length=255, default='')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True)
    class Meta:
        app_label = 'ops'
        managed = False

class CIRelation(models.Model):
    id = models.AutoField(primary_key=True)
    source = models.ForeignKey(ConfigItem, on_delete=models.CASCADE, related_name='relations')
    target = models.ForeignKey(ResourceNode, on_delete=models.CASCADE)
    relation_type = models.CharField(max_length=64, default='runs_on')
    class Meta:
        app_label = 'ops'
        managed = False

class CIType(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255, default='')
    class Meta:
        app_label = 'ops'
        managed = False
