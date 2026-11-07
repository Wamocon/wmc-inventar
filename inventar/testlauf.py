"""Testlauf: Das Testsiegel entsteht vor den Tests, wenn es noch fehlt (N-10)."""
from django.test.runner import DiscoverRunner


class Testlauf(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from geraete.siegel import SIEGEL_P12, testsiegel_anlegen

        if not SIEGEL_P12.exists():
            testsiegel_anlegen()
