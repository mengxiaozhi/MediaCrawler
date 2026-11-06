# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/threads/core.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

from media_platform.meta.core import MetaCrawler

from . import adapter


class ThreadsCrawler(MetaCrawler):
    """Crawl visible Threads posts using the user's browser session."""

    def __init__(self):
        super().__init__(adapter)
