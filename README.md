# Crypto Reversal 反轉機會雷達

日線為主、4 小時為輔的加密貨幣反轉型態觀察機器人。它只發送 Telegram 觀察訊號，不自動交易。

## 偵測型態

U 型底、W 底、頭肩底、杯柄底、倒 U 型頂、頭肩頂。U 型底擁有最高權重，但其他型態只要達標也會推送，不再互相排優先級。

## 資料來源

- K 線：Bybit -> BingX -> Binance
- CMC：Keyless Public API 優先，若有金鑰則先使用正式 API；快取預設 2 小時
- 市值與排名：CMC
- 合約 24H 成交量、OI、資金費率：交易所衍生品資料
- 現貨 24H 成交量：Bybit 現貨，Binance 現貨作備援

## 時間與推送

- 日線抓 240 根、4H 抓 360 根
- 每 12 小時掃描一次，並在收線時補掃
- 沒有結果也會發送摘要
- 預設先掃描最多 120 個 CMC 市值候選，再對日線候選補抓 4H/OI
- 同一幣種、同一型態、同一方向預設 cooldown 24 小時
- `SCAN_LIMIT` 預設每次最多 5 個結果

## 評分

型態結構 40 分、日線趨勢 15 分、4H 確認 15 分、成交量 15 分、OI/資金費率 10 分、流動性與市值 5 分。80 分以上為 HIGH，70-79 為 EARLY，60-69 為 WATCH。

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
cp .env.example .env
python scanner.py
```

請勿把 `.env`、Telegram token、CMC key 或資料庫提交到 GitHub。
