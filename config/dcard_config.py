# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/dcard_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


# Dcard: article IDs or URLs for detail mode; handles or profile URLs for creator mode.
DCARD_SPECIFIED_ID_LIST = []
DCARD_CREATOR_ID_LIST = []

# Public API pagination limits. Page size must be between 1 and 100.
DCARD_MAX_PAGES = 30
DCARD_PAGE_SIZE = 30

# Dcard browser workflow settings.
DCARD_LOGIN_TIMEOUT_SEC = 180
DCARD_PAGE_TIMEOUT_MS = 30000
DCARD_SCROLL_MAX_ROUNDS = 30
DCARD_SCROLL_IDLE_ROUNDS = 3
DCARD_SCROLL_WAIT_SEC = 1.5
