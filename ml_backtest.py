# ml_backtest.py
import pandas as pd
import numpy as np
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier
from sklearn.metrics import accuracy_score

# 加载数据
df = pd.read_csv("klines_auto.csv", parse_dates=["time"])
df.set_index("time", inplace=True)
df.sort_index(inplace=True)


# 特征工程
def add_features(df, lookback=5):
    df = df.copy()
    # 价格变化率
    for lag in range(1, lookback + 1):
        df[f"return_{lag}"] = df["close"].pct_change(lag)
    # 成交量变化率
    df["volume_change"] = df["volume"].pct_change()
    # 收盘价相对于近期高低点的位置
    df["close_pct_high5"] = df["close"] / df["high"].rolling(5).max() - 1
    df["close_pct_low5"] = df["close"] / df["low"].rolling(5).min() - 1
    # RSI (14)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))
    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    # 布林带宽度
    bb_mid = df["close"].rolling(20).mean()
    bb_std = df["close"].rolling(20).std()
    df["bb_width"] = (bb_mid + 2 * bb_std - (bb_mid - 2 * bb_std)) / bb_mid
    # 目标变量：下一根K线是否上涨（1涨，0跌/平）
    df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)
    df.dropna(inplace=True)
    return df


df_feat = add_features(df)
# 特征列
feature_cols = [c for c in df_feat.columns if c not in ["target", "open", "high", "low", "close", "volume"]]
X = df_feat[feature_cols]
y = df_feat["target"]

# 时间序列交叉验证
tscv = TimeSeriesSplit(n_splits=5)
acc_list = []
for train_idx, test_idx in tscv.split(X):
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
    model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    acc = accuracy_score(y_test, pred)
    acc_list.append(acc)
print(f"平均准确率: {np.mean(acc_list):.3f}")

# 使用全部数据训练最终模型
model = XGBClassifier(n_estimators=50, max_depth=3, learning_rate=0.1, random_state=42)
model.fit(X, y)
importance = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
print("特征重要性:\n", importance.head(10))

# 回测交易
position = None
entry_price = 0
stop_loss = 0
take_profit = 0
trades = []
for i in range(20, len(df_feat) - 1):
    current = df_feat.iloc[i]
    price = current["close"]
    # 预测下一根K线方向
    feat = current[feature_cols].values.reshape(1, -1)
    prob_up = model.predict_proba(feat)[0][1]
    # 开仓条件：概率 > 0.6
    if position is None:
        if prob_up > 0.6:
            position = "LONG"
            entry_price = price
            stop_loss = price - 4
            take_profit = price + 6
            print(f"{current.name} 开多 @{price} 止损{stop_loss} 止盈{take_profit}")
        elif prob_up < 0.4:
            position = "SHORT"
            entry_price = price
            stop_loss = price + 4
            take_profit = price - 6
            print(f"{current.name} 开空 @{price} 止损{stop_loss} 止盈{take_profit}")
    else:
        if position == "LONG":
            if price >= take_profit:
                pnl = take_profit - entry_price
                trades.append({"entry": entry_price, "exit": take_profit, "pnl": pnl, "side": "LONG"})
                print(f"{current.name} 止盈多 @{take_profit} 盈亏{pnl}点")
                position = None
            elif price <= stop_loss:
                pnl = stop_loss - entry_price
                trades.append({"entry": entry_price, "exit": stop_loss, "pnl": pnl, "side": "LONG"})
                print(f"{current.name} 止损多 @{stop_loss} 盈亏{pnl}点")
                position = None
        elif position == "SHORT":
            if price <= take_profit:
                pnl = entry_price - take_profit
                trades.append({"entry": entry_price, "exit": take_profit, "pnl": pnl, "side": "SHORT"})
                print(f"{current.name} 止盈空 @{take_profit} 盈亏{pnl}点")
                position = None
            elif price >= stop_loss:
                pnl = entry_price - stop_loss
                trades.append({"entry": entry_price, "exit": stop_loss, "pnl": pnl, "side": "SHORT"})
                print(f"{current.name} 止损空 @{stop_loss} 盈亏{pnl}点")
                position = None

if trades:
    df_trades = pd.DataFrame(trades)
    print("\n回测统计：")
    print(f"总交易次数: {len(df_trades)}")
    print(f"盈利次数: {len(df_trades[df_trades['pnl']>0])}")
    print(f"胜率: {len(df_trades[df_trades['pnl']>0])/len(df_trades):.2%}")
    print(f"总盈亏: {df_trades['pnl'].sum()}点")
    df_trades.to_csv("ml_trades.csv", index=False)
else:
    print("无交易")
