FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "markov_hedge_fund_method.crypto_routine", "--tickers", "BTC-USD,ETH-USD,SOL-USD,BNB-USD,XRP-USD,DOGE-USD,LINK-USD,TON-USD,SUI-USD,PEPE-USD,SHIB-USD,ADA-USD,AVAX-USD,DOT-USD,NEAR-USD,UNI-USD,POL-USD,LTC-USD,FET-USD,APT-USD,OP-USD,ARB-USD,INJ-USD,TIA-USD,SEI-USD,WIF-USD,JUP-USD,BONK-USD,ENA-USD,STRK-USD", "--style", "swing-intraday"]
