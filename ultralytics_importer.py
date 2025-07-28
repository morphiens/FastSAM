import sys
import importlib

class UltralyticsVersionLoader:
    def __init__(self, site_packages_path):
        self.site_packages_path = site_packages_path
        self.ultralytics_module = None

    def load(self):
        sys.path.insert(0, self.site_packages_path)
        self.ultralytics_module = importlib.import_module("ultralytics")
        sys.path.pop(0)
        return self.ultralytics_module