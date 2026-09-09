<img width="1771" height="888" alt="image" src="https://github.com/user-attachments/assets/a4ef7fa1-310e-4c56-921a-0f705e3b1493" />

Snow Chain is a lightweight web tool for TON wallet analysis.
It fetches transaction data through the TonAPI service, displays counterparty stats (in/out counts, total and average amounts), and automatically flags suspicious patterns: spam, oneway, round, and zero.
You can filter results, switch between dark/light themes, and export the table to CSV or PDF.

API Key
Get a free API key at https://tonapi.io and paste it into the form on the website.

Contacts: 
Telegram: t.me/csinty
Discord: csinty_osint

 ```bash
git clone https://github.com/csinty/Snow-Chain.git
cd Snow-Chain
pip install -r requirements.txt
python snowchain.py
