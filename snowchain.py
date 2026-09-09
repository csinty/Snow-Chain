from flask import Flask, request, render_template
from collections import defaultdict
from math import isclose
import requests
import time

app = Flask(__name__)

# ===== CONFIG =====
MIN_TX_FOR_SPAM = 20
MAX_AVG_FOR_SPAM = 1.0
ROUND_TOLERANCE = 1e-9

# ===== DEBUG LOG =====
def log(msg):
    print(f"[DEBUG] {msg}", flush=True)

# ===== FETCH TRANSACTIONS =====
def fetch_tonapi(account, api_key, limit=100, offset=0):
    url = f"https://tonapi.io/v2/blockchain/accounts/{account}/transactions"
    headers = {'User-Agent': 'Mozilla/5.0'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    params = {"limit": limit, "offset": offset, "sort": "desc"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            txs = data.get("transactions", [])
            log(f"Loaded {len(txs)} transactions")
            return txs
        else:
            log(f"Error {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        log(f"Exception: {e}")
        return None

def get_all_transactions(account, api_key, limit_per_page=100, max_pages=10):
    all_txs = []
    for page in range(max_pages):
        offset = page * limit_per_page
        txs = fetch_tonapi(account, api_key, limit_per_page, offset)
        if txs is None or not txs:
            break
        all_txs.extend(txs)
        time.sleep(0.3)
    log(f"Total loaded: {len(all_txs)}")
    return all_txs

# ===== ANALYSIS =====
def analyze_all_transfers(txs):
    stats = defaultdict(lambda: {
        'in_cnt': 0, 'out_cnt': 0,
        'in_sum': 0.0, 'out_sum': 0.0,
        'in_amounts': [], 'out_amounts': []
    })
    for tx in txs:
        # Incoming
        in_msg = tx.get('in_msg')
        if in_msg and isinstance(in_msg, dict):
            src = in_msg.get('source')
            if isinstance(src, dict):
                sender = src.get('address')
            else:
                sender = src
            value = in_msg.get('value')
            if sender and value is not None:
                try:
                    amount = int(value) / 1_000_000_000
                    stats[sender]['in_cnt'] += 1
                    stats[sender]['in_sum'] += amount
                    stats[sender]['in_amounts'].append(amount)
                except Exception as e:
                    log(f"Error in in_msg: {e}")

        # Outgoing
        out_msgs = tx.get('out_msgs', [])
        if isinstance(out_msgs, list):
            for out_msg in out_msgs:
                if not isinstance(out_msg, dict):
                    continue
                dest = out_msg.get('destination')
                if isinstance(dest, dict):
                    receiver = dest.get('address')
                else:
                    receiver = dest
                value = out_msg.get('value')
                if receiver and value is not None:
                    try:
                        amount = int(value) / 1_000_000_000
                        stats[receiver]['out_cnt'] += 1
                        stats[receiver]['out_sum'] += amount
                        stats[receiver]['out_amounts'].append(amount)
                    except Exception as e:
                        log(f"Error in out_msg: {e}")

    log(f"Stats: {len(stats)} unique addresses")
    return stats

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
    if (data['in_cnt'] > 0 and data['out_cnt'] == 0) or (data['out_cnt'] > 0 and data['in_cnt'] == 0):
        flags.append('oneway')
    if total_sum == 0:
        flags.append('zero')
    return flags

def analyze_contractors(wallet_address, api_key, top_n=500):
    """
    Возвращает до top_n контрагентов (по умолчанию 500).
    Клиент сам обрежет до нужного количества.
    """
    txs = get_all_transactions(wallet_address, api_key)
    if not txs:
        return []
    stats = analyze_all_transfers(txs)
    if not stats:
        return []
    sorted_items = sorted(stats.items(), key=lambda x: (x[1]['in_cnt'] + x[1]['out_cnt'], x[1]['in_sum'] + x[1]['out_sum']), reverse=True)
    filtered = [(addr, data) for addr, data in sorted_items if addr and addr.strip()]
    filtered = filtered[:top_n]   # теперь лимит 500
    result = []
    for addr, data in filtered:
        total_cnt = data['in_cnt'] + data['out_cnt']
        total_sum = data['in_sum'] + data['out_sum']
        avg = total_sum / total_cnt if total_cnt > 0 else 0
        flags = detect_suspicious(data)
        result.append({
            'address': addr,
            'in_cnt': data['in_cnt'],
            'out_cnt': data['out_cnt'],
            'total_cnt': total_cnt,
            'avg': avg,
            'total_sum': total_sum,
            'flags': ', '.join(flags) if flags else '—'
        })
    log(f"Found {len(result)} contractors")
    return result

# ===== WEB INTERFACE =====
@app.route('/', methods=['GET', 'POST'])
def index():
    result = None
    error = None
    address = ''
    api_key = ''
    if request.method == 'POST':
        address = request.form.get('address', '').strip()
        api_key = request.form.get('api_key', '').strip()
        if not api_key:
            error = '❌ Please enter your API key (get it at https://tonapi.io).'
        elif not address.startswith(('EQ', 'UQ')):
            error = '❌ Wallet address must start with EQ or UQ.'
        else:
            try:
                # Увеличили лимит до 500
                contractors = analyze_contractors(address, api_key, top_n=500)
                if not contractors:
                    error = '❌ No contractors found or wallet is empty.'
                else:
                    result = contractors
            except Exception as e:
                error = f'❌ Error: {e}'
    return render_template('index.html', result=result, error=error, address=address, api_key=api_key)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
