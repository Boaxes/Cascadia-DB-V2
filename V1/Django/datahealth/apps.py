from django.apps import AppConfig


class DataHealthConfig(AppConfig):
    name = "datahealth"
    verbose_name = "Cascadia Admin"

    def ready(self):
        from . import signals
        signals.connect()
