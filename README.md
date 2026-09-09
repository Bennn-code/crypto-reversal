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

## 小幣候選池

掃描只針對符合以下條件的 USDT 合約幣種：

- 排除 BTC、ETH、穩定幣與常見美元錨定代幣
- 市值 2,000 萬～30 億美元
- CMC 24H 交易量至少 100 萬美元
- 交易所必須能取得日線與 4H K 線；Bybit 優先，BingX、Binance 備援

## 時間與推送

- 日線抓 240 根、4H 抓 360 根
- 每 12 小時掃描一次，並在收線時補掃
- 每輪固定發送摘要；即使所有候選都在 cooldown 或完全沒有結果，也會說明掃描狀態
- 全量推送時每則詳細訊息預設間隔 3.2 秒；遇到 Telegram 限流會依其要求自動等待後重試
- 預設掃描 CMC Public API 前 1,000 筆中所有符合小幣池規則的候選，不設候選數或推送數上限
- 日線採受控平行掃描，再只對日線候選補抓 4H/OI，減少不必要請求
- 同一幣種、同一型態、同一方向預設 cooldown 24 小時
- `SCAN_LIMIT` 預設每次最多 5 個結果

## 評分

型態結構 40 分、日線趨勢 15 分、4H 確認 15 分、成交量 15 分、OI/資金費率 10 分、流動性與市值 5 分。80 分以上為 HIGH，70-79 為 EARLY，60-69 為 WATCH。所有達門檻的中小幣型態都會推送，同幣同型態同方向仍有 24 小時 cooldown。

逐則推送門檻預設為 70 分，每日最多 5 則；機器人會先完成全量掃描，再挑選最高分的新型態。60-69 分 WATCH 只保留在摘要中，不會硬推詳細訊息。若沒有可推送的新型態，摘要會明確顯示「本次沒有可推送的新型態」。

## 安裝

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
cp .env.example .env
python scanner.py
```

請勿把 `.env`、Telegram token、CMC key 或資料庫提交到 GitHub。
