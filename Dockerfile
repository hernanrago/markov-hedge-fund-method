FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-m", "markov_hedge_fund_method.crypto_routine", "--tickers", "BTC-USD,ETH-USD,SOL-USD,ZEC-USD,XRP-USD,DOGE-USD,NEAR-USD,BNB-USD,SUI-USD", "--years", "2"]
