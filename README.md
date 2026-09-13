<img width="1489" height="1056" alt="b2ba24ce-c9d7-4791-ae42-d58922932829" src="https://github.com/user-attachments/assets/98a411ce-fc47-4909-a9c4-e86205e0035b" />

A lightweight multi-chain contractor analyzer. Fetches transaction data for a wallet and shows counterparty stats — in/out counts, total and average amounts. For TON it also flags suspicious patterns: spam, oneway, round, and zero.

Supported networks: TON, ETH, BTC, USDT (TRC20).

<img width="1768" height="889" alt="20276079-9b1d-4794-95d6-ac036d28643a" src="https://github.com/user-attachments/assets/66dd8cae-285a-42a5-965c-36e46a858906" />

## Features

- Tabbed interface for TON / ETH / BTC / USDT (TRC20)
- Per-network API key input
- Counterparty table: address, in/out counts, total, average, total sum
- Flags for TON wallets (spam / oneway / round / zero)
- Filters: 10 / 25 / 50 / 100 / all
- "Hide zero" toggle for TON
- Dark / light theme (saved in localStorage)
- Export results to CSV and PDF
- Full pagination for all networks

## API Keys

TON — required — https://tonapi.io
ETH — required — https://etherscan.io/myapikey
BTC — not required, uses public mempool.space API
USDT (TRC20) — optional — https://www.trongrid.io

## Installation

```bash
git clone https://github.com/csinty/Snow-Chain.git
cd Snow-Chain
pip install -r requirements.txt
python snowchain.py
