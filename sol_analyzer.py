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

# ====================== 核心生成函数 ======================
def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    df = calculate_supertrend(df)
    percentile, deviation = calculate_deviation_percentile(df)
    latest = df.iloc[-1]
    price = latest['close']
    atr = latest['ATR']
    st_dir = latest['ST_Direction']
    ma50_vs_ma200 = latest['MA_50'] > latest['MA_200']
    
    # 分位数对应的买卖点映射表
    if percentile >= 88:
        position = "极端高估"
        direction = "做空"
        prob = "高"
        reason = "分位数极高 + SuperTrend空头 + MA空头排列"
    elif percentile >= 76:
        position = "明显高估"
        direction = "做空"
        prob = "中高"
        reason = "分位数较高，SuperTrend仍为空头趋势"
    elif percentile <= 12:
        position = "极端低估"
        direction = "做多"
        prob = "高"
        reason = "分位数极低 + SuperTrend多头 + MA多头排列"
    elif percentile <= 24:
        position = "明显低估"
        direction = "做多"
        prob = "中高"
        reason = "分位数较低，价格已严重偏离MA200"
    else:
        position = "正常区间"
        direction = "观望"
        prob = "低"
        reason = "分位数处于中间区域，回归动力不足"

    # 计算挂单价格（分批）
    if direction == "做多":
        initial = round(price * 0.9985, 4)
        add1 = round(initial * 0.978, 4)
        add2 = round(initial * 0.955, 4)
        tp1 = round(price + atr * 5.0, 4)
        tp2 = round(price + atr * 11.0, 4)
        entry_plan = f"初始建仓({percentile:.1f}%分位): {initial} | 加仓1({percentile-8:.1f}%分位参考): {add1} | 加仓2({percentile-15:.1f}%分位参考): {add2}"
        tp_plan = f"TP1(平50%仓位): {tp1} | TP2(平剩余50%): {tp2}"
    elif direction == "做空":
        initial = round(price * 1.0015, 4)
        add1 = round(initial * 1.022, 4)
        add2 = round(initial * 1.045, 4)
        tp1 = round(price - atr * 5.0, 4)
        tp2 = round(price - atr * 11.0, 4)
        entry_plan = f"初始建仓({percentile:.1f}%分位): {initial} | 加仓1({percentile+8:.1f}%分位参考): {add1} | 加仓2({percentile+15:.1f}%分位参考): {add2}"
        tp_plan = f"TP1(平50%仓位): {tp1} | TP2(平剩余50%): {tp2}"
    else:
        entry_plan = tp_plan = "观望，无挂单"

    return {
        "position": position,
        "direction": direction,
        "probability": prob,
        "reason": reason,
        "percentile": percentile,
        "deviation": deviation,
        "price": round(price, 4),
        "atr": round(atr, 4),
        "st_dir": "多头" if st_dir == 1 else "空头",
        "ma_trend": "多头排列" if ma50_vs_ma200 else "空头排列",
        "entry_plan": entry_plan,
        "tp_plan": tp_plan
    }

def main():
    beijing_time = get_beijing_time()
    df_short = fetch_ohlcv('15m')
    df_mid = fetch_ohlcv('1h')
    
    short = generate_signal(df_short, "短期")
    mid = generate_signal(df_mid, "中期")

    readme_content = f"""# SOL 永续合约均值回归分析报告

**最后更新**：{beijing_time}（北京时间）

**策略核心**：以最近7天偏离MA200的ATR标准化分位数作为主要决策依据，结合MA、SuperTrend、ATR进行概率研判。

---

### 一、交易指令

**【短期交易计划】（1-4小时 - 15分钟图）**
- 当前价格：{short['price']}
- 当前分位数：**{short['percentile']}%**（Deviation = {short['deviation']}）
- 当前所处位置：**{short['position']}**
- 交易方向：**{short['direction']}**
- 回归概率研判：**{short['probability']}概率**（{short['reason']}）
- 具体买卖点计划：
  - {short['entry_plan']}
- 止盈计划：{short['tp_plan']}
- 单批次建议仓位：0.8%~1.5%

**【中期交易计划】（4-12小时 - 1小时图）**
- 当前分位数：**{mid['percentile']}%**（Deviation = {mid['deviation']}）
- 当前所处位置：**{mid['position']}**
- 交易方向：**{mid['direction']}**
- 回归概率研判：**{mid['probability']}概率**（{mid['reason']}）
- 具体买卖点计划：
  - {mid['entry_plan']}
- 止盈计划：{mid['tp_plan']}
- 单批次建议仓位：0.6%~1.0%

---

### 二、交易逻辑与策略分析

**当前指标具体情况**：
- MA趋势：短期 {short['ma_trend']}，中期 {mid['ma_trend']}
- SuperTrend状态：短期 {short['st_dir']}，中期 {mid['st_dir']}
- ATR(12)：短期 {short['atr']}，中期 {mid['atr']}

**概率研判详细说明**：
短期当前处于{short['position']}区域，分位数{short['percentile']}%。由于{short['reason']}，因此判断回归概率为{short['probability']}。本策略认为，当分位数进入极端区域（>88或<12）且MA与SuperTrend均支持回归方向时，概率最高。

中期判断逻辑相同，但对分位数要求更高，只有在更极端位置才认为有较高概率进行加仓。

**分批交易与仓位管理说明**：
- 当分位数持续向极端方向移动时，依次触发初始建仓、第一次加仓、第二次加仓。
- 止盈采用两阶段：达到TP1时平掉50%仓位，达到TP2时清掉剩余全部仓位。
- 多空仓位完全独立运行，可同时存在多头和空头持仓。
- 不设置固定止损，依靠分批建仓和分批止盈控制风险。

**风险提示**：本报告基于固定量化规则自动生成，仅供学习和研究。不构成任何投资建议。实际交易请严格根据资金情况和市场流动性调整挂单价格与仓位。

---
*由 GitHub Actions 每30分钟自动更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("✅ 报告已更新，请刷新仓库查看")

if __name__ == "__main__":
    main()
