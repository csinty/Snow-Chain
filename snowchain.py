# snowchain.py
from flask import Flask, request, render_template_string
from collections import defaultdict
from math import isclose
import requests
import time

app = Flask(__name__)

MIN_TX_FOR_SPAM = 20
MAX_AVG_FOR_SPAM = 1.0
ROUND_TOLERANCE = 1e-9
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TON_MAX_PAGES = 50
ETH_MAX_PAGES = 50
BTC_MAX_PAGES = 400
USDT_MAX_PAGES = 200


def log(msg):
    print(f"[DEBUG] {msg}", flush=True)


def analyze_transfers(transfers, wallet):
    stats = defaultdict(lambda: {
        'in_cnt': 0, 'out_cnt': 0,
        'in_sum': 0.0, 'out_sum': 0.0,
        'in_amounts': [], 'out_amounts': []
    })
    w = wallet.lower() if wallet else wallet
    for t in transfers:
        f = (t.get('from') or '')
        to = (t.get('to') or '')
        amt = t.get('amount') or 0.0
        fl = f.lower() if f else f
        tl = to.lower() if to else to
        if tl == w and fl and fl != w:
            stats[f]['in_cnt'] += 1
            stats[f]['in_sum'] += amt
            stats[f]['in_amounts'].append(amt)
        elif fl == w and tl and tl != w:
            stats[to]['out_cnt'] += 1
            stats[to]['out_sum'] += amt
            stats[to]['out_amounts'].append(amt)
    return stats


def build_result(stats, flags_enabled=False, top_n=500):
    sorted_items = sorted(
        stats.items(),
        key=lambda x: (x[1]['in_cnt'] + x[1]['out_cnt'],
                       x[1]['in_sum'] + x[1]['out_sum']),
        reverse=True
    )[:top_n]
    result = []
    for addr, data in sorted_items:
        if not addr or not addr.strip():
            continue
        total_cnt = data['in_cnt'] + data['out_cnt']
        total_sum = data['in_sum'] + data['out_sum']
        avg = total_sum / total_cnt if total_cnt else 0
        flags = detect_suspicious(data) if flags_enabled else []
        result.append({
            'address': addr,
            'in_cnt': data['in_cnt'],
            'out_cnt': data['out_cnt'],
            'total_cnt': total_cnt,
            'avg': avg,
            'total_sum': total_sum,
            'flags': ', '.join(flags) if flags else '—'
        })
    return result


def is_round_amount(amount, tolerance=ROUND_TOLERANCE):
    return isclose(amount, round(amount), abs_tol=tolerance)


def detect_suspicious(data):
    flags = []
    total_cnt = data['in_cnt'] + data['out_cnt']
    total_sum = data['in_sum'] + data['out_sum']
    avg_amount = total_sum / total_cnt if total_cnt > 0 else 0
    if total_cnt >= MIN_TX_FOR_SPAM and avg_amount < MAX_AVG_FOR_SPAM:
        flags.append('spam')
    all_amounts = data['in_amounts'] + data['out_amounts']
    if all_amounts and all(is_round_amount(a) for a in all_amounts):
        flags.append('round')
    if (data['in_cnt'] > 0 and data['out_cnt'] == 0) or \
       (data['out_cnt'] > 0 and data['in_cnt'] == 0):
        flags.append('oneway')
    if total_sum == 0:
        flags.append('zero')
    return flags


def fetch_ton_transfers(account, api_key, max_pages=TON_MAX_PAGES):
    all_txs = []
    for page in range(max_pages):
        url = f"https://tonapi.io/v2/blockchain/accounts/{account}/transactions"
        headers = {'User-Agent': 'Mozilla/5.0'}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        params = {"limit": 100, "offset": page * 100, "sort": "desc"}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=30)
            if r.status_code != 200:
                log(f"TON error {r.status_code}: {r.text[:200]}")
                break
            txs = r.json().get("transactions", [])
            if not txs:
                break
            all_txs.extend(txs)
            log(f"TON page {page+1}: {len(txs)} txs (total {len(all_txs)})")
            if len(txs) < 100:
                break
            time.sleep(0.3)
        except Exception as e:
            log(f"TON exception: {e}")
            break
    log(f"TON loaded {len(all_txs)} txs")
    return all_txs


def analyze_ton(wallet, api_key, top_n=500):
    txs = fetch_ton_transfers(wallet, api_key)
    if not txs:
        return [], 0
    stats = defaultdict(lambda: {
        'in_cnt': 0, 'out_cnt': 0,
        'in_sum': 0.0, 'out_sum': 0.0,
        'in_amounts': [], 'out_amounts': []
    })
    for tx in txs:
        in_msg = tx.get('in_msg')
        if isinstance(in_msg, dict):
            src = in_msg.get('source')
            sender = src.get('address') if isinstance(src, dict) else src
            val = in_msg.get('value')
            if sender and val is not None:
                try:
                    amt = int(val) / 1_000_000_000
                    stats[sender]['in_cnt'] += 1
                    stats[sender]['in_sum'] += amt
                    stats[sender]['in_amounts'].append(amt)
                except Exception:
                    pass
        for out_msg in tx.get('out_msgs', []) or []:
            if not isinstance(out_msg, dict):
                continue
            dest = out_msg.get('destination')
            receiver = dest.get('address') if isinstance(dest, dict) else dest
            val = out_msg.get('value')
            if receiver and val is not None:
                try:
                    amt = int(val) / 1_000_000_000
                    stats[receiver]['out_cnt'] += 1
                    stats[receiver]['out_sum'] += amt
                    stats[receiver]['out_amounts'].append(amt)
                except Exception:
                    pass
    return build_result(stats, flags_enabled=True, top_n=top_n), len(txs)


def analyze_eth(wallet, api_key, top_n=500):
    if not api_key:
        return [], 0
    url = "https://api.etherscan.io/v2/api"
    all_txs = []
    page_size = 200

    for page in range(1, ETH_MAX_PAGES + 1):
        params = {
            "chainid": 1,
            "module": "account",
            "action": "txlist",
            "address": wallet,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": page_size,
            "sort": "desc",
            "apikey": api_key,
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            data = r.json()
        except Exception as e:
            log(f"ETH exception on page {page}: {e}")
            break

        status = data.get("status")
        result = data.get("result", [])
        message = data.get("message", "")

        if status != "1":
            if isinstance(result, list) and not result:
                log(f"ETH page {page}: end of history")
                break
            log(f"ETH error: {message} / {str(result)[:200]}")
            break

        if not isinstance(result, list) or not result:
            break

        all_txs.extend(result)
        log(f"ETH page {page}: {len(result)} txs (total {len(all_txs)})")

        if len(result) < page_size:
            break

        time.sleep(0.25)

    log(f"ETH loaded {len(all_txs)} total txs")

    transfers = []
    for tx in all_txs:
        try:
            amt = int(tx.get("value", 0)) / 1e18
        except Exception:
            continue
        transfers.append({
            "from": tx.get("from"),
            "to": tx.get("to"),
            "amount": amt,
        })
    stats = analyze_transfers(transfers, wallet)
    return build_result(stats, flags_enabled=False, top_n=top_n), len(all_txs)


def analyze_btc(wallet, api_key, top_n=500):
    w = wallet.lower()
    all_txs = []
    base = "https://mempool.space/api"
    url = f"{base}/address/{wallet}/txs"

    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200:
            log(f"BTC error {r.status_code}: {r.text[:200]}")
            return [], 0
        page = r.json()
        if not page:
            return [], 0
        all_txs.extend(page)
        log(f"BTC page 1: {len(page)} txs")
    except Exception as e:
        log(f"BTC exception on page 1: {e}")
        return [], 0

    last_txid = page[-1].get("txid")
    pages = 1
    while last_txid and pages < BTC_MAX_PAGES:
        url = f"{base}/address/{wallet}/txs/chain/{last_txid}"
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200:
                log(f"BTC chain page error {r.status_code}")
                break
            page = r.json()
            if not page:
                break
            all_txs.extend(page)
            log(f"BTC page {pages+1}: {len(page)} txs (total {len(all_txs)})")
            last_txid = page[-1].get("txid")
            pages += 1
            time.sleep(0.2)
        except Exception as e:
            log(f"BTC exception on chain page: {e}")
            break

    log(f"BTC loaded {len(all_txs)} total txs for {wallet}")

    stats = defaultdict(lambda: {
        'in_cnt': 0, 'out_cnt': 0,
        'in_sum': 0.0, 'out_sum': 0.0,
        'in_amounts': [], 'out_amounts': []
    })

    for tx in all_txs:
        vin = tx.get("vin", []) or []
        vout = tx.get("vout", []) or []

        my_in = any(
            ((i.get("prevout") or {}).get("scriptpubkey_address") or "").lower() == w
            for i in vin
        )
        my_out = any(
            (o.get("scriptpubkey_address") or "").lower() == w
            for o in vout
        )

        if my_in and not my_out:
            for o in vout:
                to = o.get("scriptpubkey_address") or ""
                if not to or to.lower() == w:
                    continue
                amt = o.get("value", 0) / 1e8
                stats[to]['out_cnt'] += 1
                stats[to]['out_sum'] += amt
                stats[to]['out_amounts'].append(amt)

        elif my_out and not my_in:
            for i in vin:
                prev = i.get("prevout") or {}
                f = prev.get("scriptpubkey_address") or ""
                if not f or f.lower() == w:
                    continue
                amt = prev.get("value", 0) / 1e8
                stats[f]['in_cnt'] += 1
                stats[f]['in_sum'] += amt
                stats[f]['in_amounts'].append(amt)

    return build_result(stats, flags_enabled=False, top_n=top_n), len(all_txs)


def analyze_usdt(wallet, api_key, top_n=500):
    base = f"https://api.trongrid.io/v1/accounts/{wallet}/transactions/trc20"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["TRON-PRO-API-KEY"] = api_key

    all_items = []
    fingerprint = None

    for page in range(1, USDT_MAX_PAGES + 1):
        params = {
            "limit": 200,
            "only_confirmed": "true",
            "contract_address": USDT_TRC20_CONTRACT,
        }
        if fingerprint:
            params["fingerprint"] = fingerprint

        try:
            r = requests.get(base, headers=headers, params=params, timeout=30)
            if r.status_code != 200:
                log(f"USDT error {r.status_code}: {r.text[:200]}")
                break
            payload = r.json()
        except Exception as e:
            log(f"USDT exception on page {page}: {e}")
            break

        data = payload.get("data", [])
        if not data:
            break
        all_items.extend(data)
        log(f"USDT page {page}: {len(data)} items (total {len(all_items)})")

        fingerprint = (payload.get("meta") or {}).get("fingerprint")
        if not fingerprint:
            break
        time.sleep(0.2)

    log(f"USDT loaded {len(all_items)} total txs for {wallet}")

    transfers = []
    for item in all_items:
        try:
            dec = int(item.get("token_info", {}).get("decimals", 6))
            amt = int(item.get("value", 0)) / (10 ** dec)
        except Exception:
            continue
        transfers.append({
            "from": item.get("from"),
            "to": item.get("to"),
            "amount": amt,
        })
    stats = analyze_transfers(transfers, wallet)
    return build_result(stats, flags_enabled=False, top_n=top_n), len(all_items)


def validate_ton(addr):
    return addr.startswith(("EQ", "UQ"))


def validate_eth(addr):
    return addr.startswith("0x") and len(addr) == 42


def validate_btc(addr):
    return len(addr) >= 26 and (addr[0] in "13" or addr.startswith("bc1"))


def validate_usdt(addr):
    return addr.startswith("T") and len(addr) == 34


INDEX_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Snow Chain</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf-autotable/3.5.31/jspdf.plugin.autotable.min.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; min-height: 100vh; display: flex; justify-content: center; align-items: flex-start; padding: 20px; transition: background 0.3s, color 0.3s; }
body.dark-theme { background-color: #2a2a2a; background-image: radial-gradient(circle, rgba(255,255,255,0.03) 1px, transparent 1px); background-size: 20px 20px; color: #e0e0e0; }
body.dark-theme .container { background: rgba(40,40,40,0.85); border: 1px solid rgba(255,255,255,0.06); box-shadow: 0 20px 60px rgba(0,0,0,0.6); }
body.light-theme { background-color: #f0f2f5; background-image: radial-gradient(circle, rgba(0,0,0,0.03) 1px, transparent 1px); background-size: 20px 20px; color: #222; }
body.light-theme .container { background: rgba(255,255,255,0.9); border: 1px solid rgba(0,0,0,0.08); box-shadow: 0 20px 60px rgba(0,0,0,0.1); }
.container { max-width: 1300px; width: 100%; border-radius: 24px; padding: 30px 35px; }
.header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.08); }
body.light-theme .header { border-bottom: 1px solid rgba(0,0,0,0.08); }
.profile { display: flex; align-items: center; gap: 18px; }
.avatar { width: 64px; height: 64px; border-radius: 50%; object-fit: cover; border: 2px solid #6c8cff; box-shadow: 0 4px 12px rgba(108,140,255,0.3); background: #1e1e1e; }
.profile-info { display: flex; flex-direction: column; gap: 4px; }
.profile-name { font-size: 20px; font-weight: 600; }
.social-links { display: flex; gap: 12px; flex-wrap: wrap; }
.social-link { display: inline-flex; align-items: center; gap: 8px; color: #6c8cff; text-decoration: none; font-size: 15px; font-weight: 500; transition: 0.2s; background: rgba(108,140,255,0.12); padding: 4px 14px 4px 10px; border-radius: 20px; border: 1px solid rgba(108,140,255,0.2); width: fit-content; }
.social-link:hover { background: rgba(108,140,255,0.25); transform: translateY(-1px); }
.title-block h1 { font-size: 28px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
.title-block h1 i { color: #6c8cff; font-size: 28px; }
.title-block small { display: block; font-size: 14px; font-weight: 400; margin-top: 2px; margin-left: 42px; color: #999; }
@keyframes spinSnowflake { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.snowflake-icon { display: inline-block; animation: spinSnowflake 8s linear infinite; }
.theme-switch-wrapper { position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; align-items: center; gap: 12px; background: rgba(40,40,40,0.7); padding: 6px 10px 6px 14px; border-radius: 30px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 4px 16px rgba(0,0,0,0.3); user-select: none; }
body.light-theme .theme-switch-wrapper { background: rgba(255,255,255,0.8); border-color: rgba(0,0,0,0.1); }
.theme-switch { position: relative; width: 80px; height: 34px; background: rgba(255,255,255,0.15); border-radius: 20px; cursor: pointer; transition: background 0.3s; }
body.light-theme .theme-switch { background: rgba(0,0,0,0.08); }
.theme-switch .slider { position: absolute; top: 2px; left: 2px; width: 30px; height: 30px; border-radius: 50%; background: #6c8cff; transition: transform 0.35s cubic-bezier(0.34, 1.56, 0.64, 1); display: flex; align-items: center; justify-content: center; color: #fff; font-size: 16px; box-shadow: 0 2px 8px rgba(108,140,255,0.4); }
.theme-switch.light .slider { transform: translateX(46px); }
.theme-icons { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 0 6px; position: absolute; top: 0; left: 0; height: 100%; pointer-events: none; font-size: 14px; color: rgba(255,255,255,0.4); }
body.light-theme .theme-icons { color: rgba(0,0,0,0.3); }
.theme-label { font-size: 13px; font-weight: 500; color: #ccc; }
body.light-theme .theme-label { color: #555; }

.tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 20px; border-bottom: 1px solid rgba(255,255,255,0.08); }
body.light-theme .tabs { border-bottom: 1px solid rgba(0,0,0,0.08); }
.tab-btn { background: transparent; border: none; padding: 12px 22px; font-size: 15px; font-weight: 600; color: #888; cursor: pointer; border-bottom: 3px solid transparent; transition: 0.2s; display: flex; align-items: center; gap: 8px; }
.tab-btn:hover { color: #6c8cff; }
.tab-btn.active { color: #6c8cff; border-bottom-color: #6c8cff; }
body.light-theme .tab-btn { color: #777; }
body.light-theme .tab-btn.active { color: #4a6cf7; border-bottom-color: #4a6cf7; }
.tab-content { display: none; }
.tab-content.active { display: block; }

.form-wrapper { border-radius: 16px; padding: 24px 28px; margin-bottom: 24px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.05); }
body.light-theme .form-wrapper { background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.06); }
.form-group { margin-bottom: 16px; }
.form-group label { display: block; font-weight: 500; font-size: 15px; margin-bottom: 6px; }
.form-group label i { margin-right: 8px; color: #6c8cff; }
.form-group input { width: 100%; padding: 12px 16px; font-size: 15px; border-radius: 10px; outline: none; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); color: inherit; }
body.light-theme .form-group input { background: #fff; border: 1px solid rgba(0,0,0,0.1); }
.form-group .hint { display: block; margin-top: 6px; font-size: 13px; color: #999; }
.form-group .hint a { color: #6c8cff; text-decoration: none; }
.btn-analyze { background: linear-gradient(135deg, #6c8cff, #4a6cf7); border: none; padding: 14px 28px; font-size: 17px; font-weight: 600; border-radius: 12px; color: #fff; cursor: pointer; transition: 0.25s; width: 100%; box-shadow: 0 4px 16px rgba(108,140,255,0.3); }
.btn-analyze:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(108,140,255,0.4); }
.error-box { border-left: 4px solid #ff4a4a; padding: 14px 20px; border-radius: 10px; margin-top: 15px; font-weight: 500; background: rgba(255,74,74,0.08); }

.results-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; flex-wrap: wrap; gap: 12px; }
.results-header h2 { font-weight: 500; font-size: 20px; }
.results-header h2 span { color: #6c8cff; font-weight: 600; }
.results-header h2 .txs-badge { display: inline-block; margin-left: 8px; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; background: rgba(108,140,255,0.15); color: #aac0ff; }
body.light-theme .results-header h2 .txs-badge { background: rgba(108,140,255,0.12); color: #4a6cf7; }
.export-buttons { display: flex; gap: 10px; flex-wrap: wrap; }
.btn-export { background: rgba(108,140,255,0.12); border: 1px solid rgba(108,140,255,0.2); padding: 6px 16px; border-radius: 20px; font-size: 14px; font-weight: 500; color: #6c8cff; cursor: pointer; transition: 0.2s; display: inline-flex; align-items: center; gap: 6px; }
.btn-export:hover { background: rgba(108,140,255,0.2); }
.filters-section { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; padding: 12px 16px; border-radius: 12px; margin-bottom: 16px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
body.light-theme .filters-section { background: rgba(0,0,0,0.03); border: 1px solid rgba(0,0,0,0.06); }
.filter-buttons { display: flex; gap: 6px; flex-wrap: wrap; }
.filter-btn { padding: 4px 12px; border-radius: 16px; border: 1px solid transparent; font-size: 13px; font-weight: 500; cursor: pointer; background: rgba(255,255,255,0.06); color: #ccc; }
body.light-theme .filter-btn { background: rgba(0,0,0,0.05); color: #333; }
.filter-btn:hover { background: rgba(255,255,255,0.12); }
.filter-btn.active { background: #6c8cff; color: #fff; }
.filter-checkbox { display: flex; align-items: center; gap: 6px; font-size: 14px; cursor: pointer; }
.filter-checkbox input { accent-color: #6c8cff; }
.table-wrap { overflow-x: auto; border-radius: 14px; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.06); }
body.light-theme .table-wrap { background: rgba(255,255,255,0.5); border: 1px solid rgba(0,0,0,0.06); }
table { width: 100%; border-collapse: collapse; font-size: 14px; min-width: 700px; }
th { font-weight: 600; padding: 14px 12px; text-align: left; background: rgba(108,140,255,0.12); color: #cfcfcf; border-bottom: 2px solid rgba(108,140,255,0.2); }
body.light-theme th { background: rgba(108,140,255,0.15); color: #333; }
td { padding: 12px 12px; word-break: break-all; color: #d4d4d4; border-bottom: 1px solid rgba(255,255,255,0.04); }
body.light-theme td { color: #333; border-bottom: 1px solid rgba(0,0,0,0.05); }
tr:hover td { background: rgba(255,255,255,0.03); }
.flags { color: #ffb347; font-weight: 500; font-size: 13px; }
.address-cell { font-family: 'Courier New', monospace; font-size: 13px; }
.address-cell a { text-decoration: none; color: #8ab4f8; }
body.light-theme .address-cell a { color: #0056b3; }
.address-cell a:hover { text-decoration: underline; }
.no-data-msg { padding: 20px; text-align: center; color: #999; }
@media (max-width: 768px) {
    .container { padding: 16px; }
    .header { flex-direction: column; align-items: flex-start; gap: 12px; }
    .title-block h1 { font-size: 22px; }
    .tab-btn { padding: 10px 14px; font-size: 13px; }
    table { font-size: 12px; min-width: 500px; }
}
</style>
</head>
<body class="dark-theme">

<div class="theme-switch-wrapper">
    <span class="theme-label">Theme</span>
    <div class="theme-switch" id="themeSwitch">
        <div class="theme-icons"><i class="fas fa-moon"></i><i class="fas fa-sun"></i></div>
        <div class="slider"><i class="fas fa-snowflake"></i></div>
    </div>
</div>

<div class="container">
    <header class="header">
        <div class="profile">
            <img src="https://0807.st/GhGPwHT.jpg" alt="Avatar" class="avatar">
            <div class="profile-info">
                <span class="profile-name">csinty</span>
                <div class="social-links">
                    <a href="https://t.me/csinty" target="_blank" class="social-link"><i class="fab fa-telegram-plane"></i> Telegram</a>
                    <a href="https://github.com/csinty" target="_blank" class="social-link"><i class="fab fa-github"></i> GitHub</a>
                </div>
            </div>
        </div>
        <div class="title-block">
            <h1><i class="fas fa-snowflake snowflake-icon"></i> Snow Chain</h1>
            <small>multi-chain contractor analyzer</small>
        </div>
    </header>

    <div class="tabs" id="tabs">
        <button class="tab-btn {% if active_tab == 'ton' %}active{% endif %}" data-tab="ton"><i class="fas fa-gem"></i> TON</button>
        <button class="tab-btn {% if active_tab == 'eth' %}active{% endif %}" data-tab="eth"><i class="fab fa-ethereum"></i> ETH</button>
        <button class="tab-btn {% if active_tab == 'btc' %}active{% endif %}" data-tab="btc"><i class="fab fa-bitcoin"></i> BTC</button>
        <button class="tab-btn {% if active_tab == 'usdt' %}active{% endif %}" data-tab="usdt"><i class="fas fa-dollar-sign"></i> USDT (TRC20)</button>
    </div>

    {% set tabs = [
        {'id':'ton','title':'TON','addr_ph':'EQ... or UQ...','key_ph':'TonAPI key (required)','key_hint':'Get key at <a href="https://tonapi.io" target="_blank">tonapi.io</a>'},
        {'id':'eth','title':'ETH','addr_ph':'0x...','key_ph':'Etherscan API key (required)','key_hint':'Get key at <a href="https://etherscan.io/myapikey" target="_blank">etherscan.io</a>'},
        {'id':'btc','title':'BTC','addr_ph':'bc1... / 1... / 3...','key_ph':'Not required','key_hint':'Uses public mempool.space API'},
        {'id':'usdt','title':'USDT (TRC20)','addr_ph':'T...','key_ph':'TronGrid API key (optional)','key_hint':'Get key at <a href="https://www.trongrid.io" target="_blank">trongrid.io</a>'}
    ] %}

    {% for t in tabs %}
    <div class="tab-content {% if active_tab == t.id %}active{% endif %}" id="tab-{{ t.id }}">
        <div class="form-wrapper">
            <form method="POST">
                <input type="hidden" name="network" value="{{ t.id }}">

                <div class="form-group">
                    <label for="api_key_{{ t.id }}"><i class="fas fa-key"></i> API Key ({{ t.title }})</label>
                    <input type="text" id="api_key_{{ t.id }}" name="api_key"
                           placeholder="{{ t.key_ph }}"
                           value="{% if active_tab == t.id %}{{ api_key or '' }}{% endif %}">
                    <span class="hint">{{ t.key_hint|safe }}</span>
                </div>

                <div class="form-group">
                    <label for="address_{{ t.id }}"><i class="fas fa-wallet"></i> Wallet address</label>
                    <input type="text" id="address_{{ t.id }}" name="address"
                           placeholder="{{ t.addr_ph }}"
                           value="{% if active_tab == t.id %}{{ address or '' }}{% endif %}">
                </div>

                <button type="submit" class="btn-analyze"><i class="fas fa-chart-line"></i> Analyze</button>
            </form>

            {% if active_tab == t.id and error %}
            <div class="error-box"><i class="fas fa-exclamation-circle"></i> {{ error }}</div>
            {% endif %}
        </div>

        {% if active_tab == t.id and result %}
        <div class="results-header">
            <h2>
                Result (<span id="contractorCount-{{ t.id }}">{{ result|length }}</span> contractors)
                {% if tx_count %}<span class="txs-badge">{{ tx_count }} txs</span>{% endif %}
            </h2>
            <div class="export-buttons">
                <button class="btn-export" data-export="csv" data-tab="{{ t.id }}"><i class="fas fa-file-csv"></i> CSV</button>
                <button class="btn-export" data-export="pdf" data-tab="{{ t.id }}"><i class="fas fa-file-pdf"></i> PDF</button>
            </div>
        </div>

        <div class="filters-section">
            <div class="filter-buttons" data-tab="{{ t.id }}">
                <button class="filter-btn" data-limit="10">10</button>
                <button class="filter-btn" data-limit="25">25</button>
                <button class="filter-btn active" data-limit="50">50</button>
                <button class="filter-btn" data-limit="100">100</button>
                <button class="filter-btn" data-limit="all">All</button>
            </div>
            {% if t.id == 'ton' %}
            <label class="filter-checkbox">
                <input type="checkbox" class="hide-zero" data-tab="{{ t.id }}"> Hide zero
            </label>
            {% endif %}
        </div>

        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>Address</th><th>In</th><th>Out</th><th>Total</th>
                        <th>Avg</th><th>Total</th>
                        {% if t.id == 'ton' %}<th>Flags</th>{% endif %}
                    </tr>
                </thead>
                <tbody class="table-body" data-tab="{{ t.id }}"></tbody>
            </table>
            <div class="no-data-msg" data-tab="{{ t.id }}" style="display:none;">No contractors match the filters.</div>
        </div>
        {% endif %}
    </div>
    {% endfor %}
</div>

<script>
(function(){
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
        });
    });

    const themeSwitch = document.getElementById('themeSwitch');
    function setTheme(t){
        if (t === 'light'){ document.body.classList.replace('dark-theme','light-theme'); themeSwitch.classList.add('light'); }
        else { document.body.classList.replace('light-theme','dark-theme'); themeSwitch.classList.remove('light'); }
        localStorage.setItem('theme', t);
    }
    setTheme(localStorage.getItem('theme') || 'dark');
    themeSwitch.addEventListener('click', () => {
        setTheme(document.body.classList.contains('light-theme') ? 'dark' : 'light');
    });

    const DATA = {{ result_map | tojson | safe }};
    const TX_COUNTS = {{ tx_count_map | tojson | safe }};
    const EXPLORERS = {
        ton:  'https://tonscan.org/address/',
        eth:  'https://etherscan.io/address/',
        btc:  'https://mempool.space/address/',
        usdt: 'https://tronscan.org/#/address/'
    };
    const FLAGS_ENABLED = { ton: true, eth: false, btc: false, usdt: false };

    const state = {};
    Object.keys(DATA).forEach(tab => {
        state[tab] = { limit: 50, hideZero: false };
    });

    function renderTab(tab){
        const fullData = DATA[tab] || [];
        const body = document.querySelector(`.table-body[data-tab="${tab}"]`);
        const countEl = document.getElementById('contractorCount-' + tab);
        const noData = document.querySelector(`.no-data-msg[data-tab="${tab}"]`);
        if (!body) return;

        let filtered = fullData;
        if (state[tab].hideZero) filtered = filtered.filter(c => !c.flags.includes('zero'));
        let limited = state[tab].limit === 'all' ? filtered : filtered.slice(0, state[tab].limit);

        if (countEl) countEl.textContent = limited.length;
        if (limited.length === 0){
            body.innerHTML = '';
            if (noData) noData.style.display = 'block';
            return;
        }
        if (noData) noData.style.display = 'none';

        let html = '';
        limited.forEach((c, i) => {
            const short = c.address.length > 22
                ? c.address.slice(0,12) + '…' + c.address.slice(-8)
                : c.address;
            html += `<tr>
                <td>${i+1}</td>
                <td class="address-cell"><a href="${EXPLORERS[tab]}${c.address}" target="_blank">${short}</a></td>
                <td>${c.in_cnt}</td>
                <td>${c.out_cnt}</td>
                <td>${c.total_cnt}</td>
                <td>${c.avg.toFixed(6)}</td>
                <td>${c.total_sum.toFixed(9)}</td>
                ${FLAGS_ENABLED[tab] ? `<td class="flags">${c.flags}</td>` : ''}
            </tr>`;
        });
        body.innerHTML = html;
    }

    document.querySelectorAll('.filter-buttons').forEach(group => {
        const tab = group.dataset.tab;
        group.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                group.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state[tab].limit = btn.dataset.limit === 'all' ? 'all' : parseInt(btn.dataset.limit, 10);
                renderTab(tab);
            });
        });
    });
    document.querySelectorAll('.hide-zero').forEach(cb => {
        cb.addEventListener('change', () => {
            const tab = cb.dataset.tab;
            state[tab].hideZero = cb.checked;
            renderTab(tab);
        });
    });

    Object.keys(DATA).forEach(renderTab);

    document.querySelectorAll('.btn-export').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            const kind = btn.dataset.export;
            const fullData = DATA[tab] || [];
            const txCount = TX_COUNTS[tab] || 0;
            let data = fullData;
            if (state[tab].hideZero) data = data.filter(c => !c.flags.includes('zero'));
            if (state[tab].limit !== 'all') data = data.slice(0, state[tab].limit);
            if (!data.length) return;

            if (kind === 'csv'){
                let csv = '\uFEFFSnow Chain – ' + tab.toUpperCase() + ' Report\n';
                csv += `Generated: ${new Date().toLocaleString()}\n`;
                csv += `Total contractors: ${data.length}\n`;
                csv += `Total transactions: ${txCount}\n\n`;
                csv += '№;Address;In;Out;Total;Avg;TotalSum;Flags\n';
                data.forEach((c,i) => {
                    csv += `${i+1};${c.address};${c.in_cnt};${c.out_cnt};${c.total_cnt};${c.avg.toFixed(6)};${c.total_sum.toFixed(9)};${c.flags}\n`;
                });
                const blob = new Blob([csv], {type:'text/csv;charset=utf-8;'});
                const a = document.createElement('a');
                a.href = URL.createObjectURL(blob);
                a.download = `snow_chain_${tab}_${new Date().toISOString().slice(0,10)}.csv`;
                a.click();
                URL.revokeObjectURL(a.href);
            } else if (kind === 'pdf'){
                const { jsPDF } = window.jspdf;
                const doc = new jsPDF('landscape', 'mm', 'a4');
                doc.setFillColor(108,140,255);
                doc.rect(0,0,doc.internal.pageSize.getWidth(),20,'F');
                doc.setTextColor(255,255,255);
                doc.setFontSize(16); doc.setFont('helvetica','bold');
                doc.text(`Snow Chain – ${tab.toUpperCase()} Report`, 14, 14);
                doc.setTextColor(0,0,0);
                doc.setFontSize(10); doc.setFont('helvetica','normal');
                doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 28);
                doc.text(`Total contractors: ${data.length}`, 14, 34);
                doc.text(`Total transactions: ${txCount}`, 14, 40);
                const head = [['#','Address','In','Out','Total','Avg','TotalSum','Flags']];
                const rows = data.map((c,i) => [i+1, c.address, c.in_cnt, c.out_cnt, c.total_cnt, c.avg.toFixed(6), c.total_sum.toFixed(9), c.flags]);
                doc.autoTable({ head, body: rows, startY: 46, theme:'striped',
                    headStyles:{fillColor:[108,140,255], textColor:[255,255,255], fontSize:9},
                    styles:{fontSize:7, cellPadding:2},
                    columnStyles:{1:{cellWidth:'auto', fontSize:6}}
                });
                doc.save(`snow_chain_${tab}_${new Date().toISOString().slice(0,10)}.pdf`);
            }
        });
    });
})();
</script>
</body>
</html>
"""


@app.route('/', methods=['GET', 'POST'])
def index():
    active_tab = 'ton'
    result_map = {}
    tx_count_map = {}
    error = None
    address = ''
    api_key = ''

    if request.method == 'POST':
        network = request.form.get('network', 'ton')
        active_tab = network
        address = request.form.get('address', '').strip()
        api_key = request.form.get('api_key', '').strip()

        try:
            if network == 'ton':
                if not api_key:
                    error = '❌ TonAPI key required. Get it at tonapi.io'
                elif not validate_ton(address):
                    error = '❌ TON address must start with EQ or UQ.'
                else:
                    contractors, tx_count = analyze_ton(address, api_key)
                    result_map['ton'] = contractors
                    tx_count_map['ton'] = tx_count
                    if not contractors:
                        error = '❌ No contractors found or wallet is empty.'

            elif network == 'eth':
                if not api_key:
                    error = '❌ Etherscan API key required.'
                elif not validate_eth(address):
                    error = '❌ ETH address must start with 0x and be 42 chars long.'
                else:
                    contractors, tx_count = analyze_eth(address, api_key)
                    result_map['eth'] = contractors
                    tx_count_map['eth'] = tx_count
                    if not contractors:
                        error = '❌ No transactions found or API error.'

            elif network == 'btc':
                if not validate_btc(address):
                    error = '❌ Invalid BTC address.'
                else:
                    contractors, tx_count = analyze_btc(address, api_key)
                    result_map['btc'] = contractors
                    tx_count_map['btc'] = tx_count
                    if not contractors:
                        error = '❌ No transactions found.'

            elif network == 'usdt':
                if not validate_usdt(address):
                    error = '❌ USDT TRC20 address must start with T and be 34 chars long.'
                else:
                    contractors, tx_count = analyze_usdt(address, api_key)
                    result_map['usdt'] = contractors
                    tx_count_map['usdt'] = tx_count
                    if not contractors:
                        error = '❌ No USDT TRC20 transactions found.'
        except Exception as e:
            error = f'❌ Error: {e}'

    return render_template_string(
        INDEX_HTML,
        active_tab=active_tab,
        result=result_map.get(active_tab, []),
        result_map=result_map,
        tx_count_map=tx_count_map,
        tx_count=tx_count_map.get(active_tab, 0),
        error=error,
        address=address,
        api_key=api_key,
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
