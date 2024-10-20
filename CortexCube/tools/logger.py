import pprint
import numpy as np
import logging
import os

# Global variable to toggle logging
logging_enabled = os.getenv('LOG_ENABLED')
if logging_enabled is None:
    LOG_ENABLED = True

logging_level = os.getenv('LOGGING_LEVEL')
if logging_level is None:
    logging_level = 'INFO'

logging.basicConfig(level=logging.WARNING)

class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance.init()
        return cls._instance

    def init(self):
        self.logger = logging.getLogger('CortexCubeLogger')
        self.logger.setLevel(logging_level)

        if not self.logger.handlers:
            self.file_handler = logging.FileHandler('logs.log', mode='a')
            self.file_handler.setLevel(logging_level)  # Log all levels
            
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            self.file_handler.setFormatter(formatter)

            self.logger.addHandler(self.file_handler)

    def log(self, level, *args, block=False, **kwargs):
        if LOG_ENABLED:
            if block:
                self.logger.log(level, "=" * 80)
            for arg in args:
                if isinstance(arg, dict):
                    message = pprint.pformat(arg, **kwargs)
                else:
                    message = str(arg, **kwargs)
                self.logger.log(level, message)
            if block:
                self.logger.log(level, "=" * 80)

cube_logger = Logger()

# The updated log function

def log(level, *args, block=False, **kwargs):
    cube_logger.log(level, *args, block=block, **kwargs)