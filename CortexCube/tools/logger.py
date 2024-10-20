import json
import time
from collections import defaultdict
import pprint

import numpy as np
import logging

# Global variable to toggle logging
LOG_ENABLED = True


import logging
import pprint

LOG_ENABLED = True

class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance.init()
        return cls._instance

    def init(self):
        self.logger = logging.getLogger('CortexCubeLogger')
        self.logger.setLevel(logging.INFO)

        if not self.logger.handlers:
            self.file_handler = logging.FileHandler('logs.log', mode='a')
            self.file_handler.setLevel(logging.INFO)

            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.file_handler.setFormatter(formatter)

            self.logger.addHandler(self.file_handler)

    def log(self, *args, block=False, **kwargs):
        if LOG_ENABLED:
            if block:
                self.logger.info("=" * 80)
            for arg in args:
                if isinstance(arg, dict):
                    self.logger.info(pprint.pformat(arg, **kwargs))
                else:
                    self.logger.info(str(arg, **kwargs))

logger = Logger()

def log(*args, block=False, **kwargs):
    logger.log(*args, block=block, **kwargs)