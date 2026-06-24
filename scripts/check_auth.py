#!/usr/bin/env python3
"""Check Confluence / Shimo credentials used by update_data.py."""

import json
import os
import sys
import urllib.request

WORKSPACE = os.environ.get('RELEASE_PLATFORM_HOME', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WORKSPACE)

WORK_ORDER_COOKIE_PATH = os.path.join(WORKSPACE, '.config/tokens/work-order.cookie')

from update_data import (  # noqa: E402
    CONF_COOKIE_PATH,
    CONF_TOKEN_PATH,
    SHIMO_TOKEN_PATH,
    fetch_confluence,
    fetch_shimo,
    load_conf_auths,
    load_shimo_token,
)


def main():
    print('=== Confluence ===')
    try:
        auths = load_conf_auths()
        print(f'found {len(auths)} auth method(s): {[a[0] for a in auths]}')
        html, auth_type, _ = fetch_confluence()
        print(f'OK: {auth_type}, html={len(html)} chars')
    except Exception as e:
        print(f'FAIL: {e}')
        print(f'  token file: {CONF_TOKEN_PATH}')
        print(f'  cookie file: {CONF_COOKIE_PATH}')

    print('\n=== Shimo ===')
    try:
        token, user_id = load_shimo_token()
        text = fetch_shimo(token, user_id)
        print(f'OK: user_id={user_id}, text={len(text)} chars')
    except Exception as e:
        print(f'FAIL: {e}')
        print(f'  token file: {SHIMO_TOKEN_PATH}')

    print('\n=== JUST 工单 ===')
    try:
        from scripts.fetch_tickets import check_auth as check_work_order  # noqa: E402

        check_work_order()
    except Exception as e:
        print(f'FAIL: {e}')
        print(f'  cookie file: {WORK_ORDER_COOKIE_PATH}')


if __name__ == '__main__':
    main()
