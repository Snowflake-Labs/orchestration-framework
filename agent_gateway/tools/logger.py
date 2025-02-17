# Copyright 2024 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import logging
import os
import pprint
import sys

# Global variable to toggle logging
LOGGING_ENABLED = os.getenv("LOGGING_ENABLED", "True").lower() in ("true", "1", "t")

logging_level = os.getenv("LOGGING_LEVEL", "INFO").upper()
logging_level = getattr(logging, logging_level, logging.DEBUG)

logging.basicConfig(level=logging.WARNING)


class Logger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.init()
        return cls._instance

    def init(self):
        self.logger = logging.getLogger("AgentGatewayLogger")
        self.logger.setLevel(logging_level)
        self.logger.propagate = False

        if not self.logger.handlers:
            self.file_handler = logging.FileHandler("logs.log", mode="a")
            self.file_handler.setLevel(logging_level)  # Log all levels
            self.stream_handler = logging.StreamHandler(sys.stdout)
            self.stream_handler.setLevel(logging_level)

            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            self.file_handler.setFormatter(formatter)
            self.stream_handler.setFormatter(formatter)

            self.logger.addHandler(self.file_handler)
            self.logger.addHandler(self.stream_handler)

    def log(self, level, *args, block=False, **kwargs):
        if isinstance(level, str):
            level = getattr(logging, level.upper())
        if LOGGING_ENABLED:
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


gateway_logger = Logger()
