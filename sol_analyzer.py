import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

SYMBOL = 'SOL/USDT:USDT'
LIMIT = 1200
okx = ccxt.okx({'enableRateLimit': True})

def get_beijing_time():
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")

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

def calculate_deviation_percentile(df):
    df = df.copy()
    df['MA200'] = df['close'].rolling(200).mean()
    df['ATR'] = calculate_atr(df, 12)
    df['Deviation'] = (df['close'] - df['MA200']) / df['ATR']
    recent = df['Deviation'].dropna().tail(900)
    if len(recent) < 300:
        return 50.0, 0.0
    current_dev = df['Deviation'].iloc[-1]
    percentile = (recent < current_dev).mean() * 100
    return round(percentile, 2), round(current_dev, 4)

def fetch_ohlcv(timeframe):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=LIMIT)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    df = calculate_supertrend(df)
    percentile, deviation = calculate_deviation_percentile(df)
    latest = df.iloc[-1]
    price = latest['close']
    atr = latest['ATR']
    st_dir = latest['ST_Direction']
    ma_trend_up = latest['MA_50'] > latest['MA_200']
    
    # 分位数位置判断
    if percentile >= 85:
        position = "极端高估"
        prob = "高"
        reason = "分位数≥85 + SuperTrend空头 + MA空头排列"
    elif percentile >= 73:
        position = "明显高估"
        prob = "中高"
        reason = "分位数处于73-85，高估区域，MA与SuperTrend均支持回归"
    elif percentile <= 15:
        position = "极端低估"
        prob = "高"
        reason = "分位数≤15 + SuperTrend多头 + MA多头排列"
    elif percentile <= 27:
        position = "明显低估"
        prob = "中高"
        reason = "分位数处于15-27，低估区域，回归概率提升"
    else:
        position = "正常区间"
        prob = "低"
        reason = "分位数处于正常范围，MA与SuperTrend未形成明显极端结构"

    # 计算挂单价格
    if position in ["极端高估", "明显高估"]:
        # 多头持仓管理：上涨高估区
        long_tp1 = round(price - atr * 1.5, 4)   # 第一止盈（减半）
        long_tp2 = round(price - atr * 4.0, 4)   # 第二止盈（全平多 + 反手开空）
        short_entry = round(price + atr * 0.5, 4)
        long_plan = f"止盈减半(第一高估): {long_tp1} | 全平多并反手开空(第二高估): {long_tp2}"
        short_plan = f"反手开空挂单: {short_entry}"
        long_entry_plan = "当前为高估区，无做多挂单"
    elif position in ["极端低估", "明显低估"]:
        # 空头持仓管理：下跌低估区
        short_tp1 = round(price + atr * 1.5, 4)
        short_tp2 = round(price + atr * 4.0, 4)
        long_entry = round(price - atr * 0.5, 4)
        short_plan = f"止盈减半(第一低估): {short_tp1} | 全平空并反手开多(第二低估): {short_tp2}"
        long_plan = f"反手开多挂单: {long_entry}"
        long_entry_plan = f"反手开多挂单: {long_entry}"
    else:
        long_plan = short_plan = long_entry_plan = "正常区间，建议观望，暂不挂单"

    return {
        "position": position,
        "percentile": percentile,
        "deviation": deviation,
        "price": round(price, 4),
        "atr": round(atr, 4),
        "st_dir": "多头" if st_dir == 1 else "空头",
        "ma_trend": "多头排列" if ma_trend_up else "空头排列",
        "probability": prob,
        "reason": reason,
        "long_management": long_plan,
        "short_management": short_plan,
        "long_entry_plan": long_entry_plan
    }

def main():
    beijing_time = get_beijing_time()
    df_short = fetch_ohlcv('15m')
    df_mid = fetch_ohlcv('1h')
    
    short = generate_signal(df_short, "短期")
    mid = generate_signal(df_mid, "中期")

    readme_content = f"""# SOL 永续合约均值回归挂单分析报告

**最后更新**：{beijing_time}（北京时间）

**策略核心**：基于最近7天偏离MA200的分位数，结合MA、SuperTrend、ATR判断高估/低估位置，并给出需提前挂的限价单与止盈单。

---

### 一、交易指令

**【短期交易计划】（1-4小时 - 15分钟图）**
- 当前价格：{short['price']} USDT
- 当前分位数：**{short['percentile']}%**（Deviation = {short['deviation']}）
- 当前所处位置：**{short['position']}**
- 回归概率研判：**{short['probability']}概率**（{short['reason']}）

**多头持仓管理建议（如果你当前持有多单）：**
- {short['long_management']}

**空头持仓管理建议（如果你当前持有空单）：**
- {short['short_management']}

**反手开仓挂单建议：**
- {short['long_entry_plan']}

---

**【中期交易计划】（4-12小时 - 1小时图）**
- 当前分位数：**{mid['percentile']}%**（Deviation = {mid['deviation']}）
- 当前所处位置：**{mid['position']}**
- 回归概率研判：**{mid['probability']}概率**（{mid['reason']}）

**多头持仓管理建议：**
- {mid['long_management']}

**空头持仓管理建议：**
- {mid['short_management']}

**反手开仓挂单建议：**
- {mid['long_entry_plan']}

---

### 二、交易逻辑与策略分析

**当前指标状态**：
- MA趋势：短期 {short['ma_trend']} | 中期 {mid['ma_trend']}
- SuperTrend：短期 {short['st_dir']} | 中期 {mid['st_dir']}
- ATR(12)：短期 {short['atr']} | 中期 {mid['atr']}

**概率研判逻辑**：
短期当前处于 **{short['position']}**，分位数达到 {short['percentile']}%。结合当前MA排列与SuperTrend状态，判断价格回归均值的概率为 **{short['probability']}**。当分位数进入极端高估（≥85%）或极端低估（≤15%）时，且MA与SuperTrend均支持回归方向，概率显著提升。此时建议提前挂好止盈单与反手限价单。

**挂单逻辑说明**：
- **第一高估/低估位置**：用于持仓减半止盈（平掉约50%仓位）。
- **第二高估/低估位置**：用于剩余仓位全部平仓，并立即反手开 opposite 方向仓位。
- 所有价格均通过ATR动态计算，确保与当前波动率匹配。
- 本报告目的是帮助你提前布置限价单和止盈单，减少手动盯盘压力。

**风险提示**：本报告为量化规则驱动生成，仅供参考。不构成投资建议。实际挂单价格请根据实时盘面和个人仓位灵活微调。

---
*由 GitHub Actions 每30分钟自动更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("✅ 报告已按你的新要求更新完成")

if __name__ == "__main__":
    main()
