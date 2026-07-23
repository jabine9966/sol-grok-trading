import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

# ====================== 配置 ======================
SYMBOL = 'SOL/USDT:USDT'
LIMIT = 1200
okx = ccxt.okx({'enableRateLimit': True})

def get_beijing_time():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

# ====================== 指标计算 ======================
def calculate_ma(df, periods=[10, 50, 100, 200]):
    for p in periods:
        df[f'MA_{p}'] = df['close'].rolling(window=p).mean()
    return df

def calculate_atr(df, period=12):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_supertrend(df, atr_period=10, multiplier=2.0):
    df = df.copy()
    hl2 = (df['high'] + df['low']) / 2
    atr = calculate_atr(df, atr_period)
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)
    supertrend.iloc[0] = hl2.iloc[0]
    direction.iloc[0] = 1
    for i in range(1, len(df)):
        if df['close'].iloc[i-1] > supertrend.iloc[i-1]:
            supertrend.iloc[i] = max(lower.iloc[i], supertrend.iloc[i-1])
        else:
            supertrend.iloc[i] = min(upper.iloc[i], supertrend.iloc[i-1])
        direction.iloc[i] = 1 if df['close'].iloc[i] > supertrend.iloc[i] else -1
    df['SuperTrend'] = supertrend
    df['ST_Direction'] = direction
    df['ATR'] = calculate_atr(df, 12)
    return df

# ====================== 独立分位数计算 ======================
def calculate_percentile(series, current):
    if len(series) < 300:
        return 50.0
    percentile = (series < current).mean() * 100
    return round(percentile, 2)

def calculate_ma200_deviation_percentile(df):
    df = df.copy()
    df['MA200'] = df['close'].rolling(200).mean()
    df['ATR'] = calculate_atr(df, 12)
    df['MA200_Dev'] = (df['close'] - df['MA200']) / df['ATR']
    recent = df['MA200_Dev'].dropna().tail(900)
    current = df['MA200_Dev'].iloc[-1]
    return calculate_percentile(recent, current), round(current, 4)

def calculate_supertrend_deviation_percentile(df):
    df = calculate_supertrend(df.copy())
    df['ST_Dev'] = (df['close'] - df['SuperTrend']) / df['ATR']
    recent = df['ST_Dev'].dropna().tail(900)
    current = df['ST_Dev'].iloc[-1]
    return calculate_percentile(recent, current), round(current, 4)

def fetch_ohlcv(timeframe):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=LIMIT)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# ====================== 信号生成（核心重构） ======================
def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    ma_p, ma_dev = calculate_ma200_deviation_percentile(df)
    st_p, st_dev = calculate_supertrend_deviation_percentile(df)
    latest = df.iloc[-1]
    price = round(latest['close'], 4)
    atr = round(latest['ATR'], 4)
    st_dir = "多头" if latest['ST_Direction'] == 1 else "空头"
    ma_trend = "多头排列" if latest['MA_50'] > latest['MA_200'] else "空头排列"

    # 综合两个分位数判断位置和概率
    if ma_p >= 82 and st_p >= 78:
        position = "极端高估"
        probability = "高"
        reason = "MA200和SuperTrend分位数均处于极端高位"
        long_tp1 = round(price - atr * 2.0, 4)   # 多头第一止盈（减半）
        long_tp2 = round(price - atr * 5.5, 4)   # 多头第二止盈（全平并反手做空）
        short_entry = round(price + atr * 0.8, 4)
        action_plan = f"多头止盈1(减半): {long_tp1} | 多头止盈2(全平+反手做空): {long_tp2} | 反手做空挂单: {short_entry}"
    elif ma_p >= 70 and st_p >= 68:
        position = "明显高估"
        probability = "中高"
        reason = "两个分位数均进入高估区域"
        long_tp1 = round(price - atr * 1.8, 4)
        long_tp2 = round(price - atr * 4.8, 4)
        short_entry = round(price + atr * 0.6, 4)
        action_plan = f"多头止盈1(减半): {long_tp1} | 多头止盈2(全平+反手做空): {long_tp2} | 反手做空挂单: {short_entry}"
    elif ma_p <= 18 and st_p <= 22:
        position = "极端低估"
        probability = "高"
        reason = "MA200和SuperTrend分位数均处于极端低位"
        short_tp1 = round(price + atr * 2.0, 4)
        short_tp2 = round(price + atr * 5.5, 4)
        long_entry = round(price - atr * 0.8, 4)
        action_plan = f"空头止盈1(减半): {short_tp1} | 空头止盈2(全平+反手做多): {short_tp2} | 反手做多挂单: {long_entry}"
    elif ma_p <= 30 and st_p <= 32:
        position = "明显低估"
        probability = "中高"
        reason = "两个分位数均进入低估区域"
        short_tp1 = round(price + atr * 1.8, 4)
        short_tp2 = round(price + atr * 4.8, 4)
        long_entry = round(price - atr * 0.6, 4)
        action_plan = f"空头止盈1(减半): {short_tp1} | 空头止盈2(全平+反手做多): {short_tp2} | 反手做多挂单: {long_entry}"
    else:
        position = "正常区间"
        probability = "低"
        reason = "两个分位数均处于中间区域，回归动力不足"
        action_plan = "观望，暂不建议挂单"

    return {
        "price": price,
        "atr": atr,
        "ma_percentile": ma_p,
        "st_percentile": st_p,
        "position": position,
        "probability": probability,
        "reason": reason,
        "action_plan": action_plan,
        "st_dir": st_dir,
        "ma_trend": ma_trend
    }

def main():
    beijing_time = get_beijing_time()
    df_short = fetch_ohlcv('15m')
    df_mid = fetch_ohlcv('1h')
    
    short = generate_signal(df_short, "短期")
    mid = generate_signal(df_mid, "中期")

    readme_content = f"""# SOL 永续合约均值回归挂单分析报告

**最后更新**：{beijing_time}（北京时间）

**核心逻辑**：MA200偏离分位数与SuperTrend偏离分位数**独立统计**，综合判断高估/低估位置，给出止盈与反手挂单建议。

---

### 一、交易指令

**【短期交易计划】（1-4小时 - 15分钟图）**
- 当前价格：**{short['price']}** USDT
- 当前位置：**{short['position']}**
- 回归概率：**{short['probability']}**
- MA200分位数：{short['ma_percentile']}% 
- SuperTrend分位数：{short['st_percentile']}%
- 建议挂单与止盈计划：
  - **{short['action_plan']}**

**【中期交易计划】（4-12小时 - 1小时图）**
- 当前位置：**{mid['position']}**
- 回归概率：**{mid['probability']}**
- MA200分位数：{mid['ma_percentile']}% 
- SuperTrend分位数：{mid['st_percentile']}%
- 建议挂单与止盈计划：
  - **{mid['action_plan']}**

---

### 二、交易逻辑与策略分析

**当前指标状态**：
- MA趋势：短期 {short['ma_trend']}，中期 {mid['ma_trend']}
- SuperTrend状态：短期 {short['st_dir']}，中期 {mid['st_dir']}
- ATR(12)：短期 {short['atr']}，中期 {mid['atr']}

**概率研判依据**：
- 当 **MA200分位数** 和 **SuperTrend分位数** 同时处于极端高位（均>78左右）时，判定为**极端高估**，多头止盈并反手做空的概率为**高**。
- 当两个分位数同时处于极端低位（均<22左右）时，判定为**极端低估**，空头止盈并反手做多的概率为**高**。
- 仅当两个指标分位数方向一致且极端时，才给出明确挂单建议；若只有一个指标极端，另一个处于正常区间，则概率降低或观望。

**挂单与仓位管理逻辑**：
- **第一档止盈**：用于减半仓位（建议平掉约50%仓位）。
- **第二档止盈**：用于剩余仓位全部平仓，并立即反手开相反方向仓位。
- 本策略不设置固定止损，通过分批止盈 + 反手操作来管理双向持仓风险。
- 所有价格均结合当前ATR动态计算，具有一定适应性。

**风险提示**：本报告由量化规则自动生成，仅供学习和参考。不构成任何投资建议。请根据你的实际持仓情况和风险偏好调整挂单价格。

---
*由 GitHub Actions 每30分钟自动更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("✅ 重构版报告已生成完成")

if __name__ == "__main__":
    main()
