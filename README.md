<img width="1489" height="1056" alt="b2ba24ce-c9d7-4791-ae42-d58922932829" src="https://github.com/user-attachments/assets/98a411ce-fc47-4909-a9c4-e86205e0035b" />

Snow Chain is a lightweight web tool for TON wallet analysis.
It fetches transaction data through the TonAPI service, displays counterparty stats (in/out counts, total and average amounts), and automatically flags suspicious patterns: spam, oneway, round, and zero.
You can filter results, switch between dark/light themes, and export the table to CSV or PDF.

<img width="1771" height="888" alt="image" src="https://github.com/user-attachments/assets/fa4a3b20-8461-4cd6-981a-4a8f8a3dffd1" />

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
