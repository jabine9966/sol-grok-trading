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
    df['ATR'] = tr.rolling(window=period).mean()
    return df

def calculate_supertrend(df, atr_period=10, multiplier=2.0):
    df = df.copy()
    hl2 = (df['high'] + df['low']) / 2
    atr = df['ATR']
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
    df['MA200_Dev'] = (df['close'] - df['MA200']) / df['ATR']
    recent = df['MA200_Dev'].dropna().tail(900)
    current = df['MA200_Dev'].iloc[-1]
    return calculate_percentile(recent, current), round(current, 4)

def calculate_supertrend_deviation_percentile(df):
    df = df.copy()
    df['ST_Dev'] = (df['close'] - df['SuperTrend']) / df['ATR']
    recent = df['ST_Dev'].dropna().tail(900)
    current = df['ST_Dev'].iloc[-1]
    return calculate_percentile(recent, current), round(current, 4)

def fetch_ohlcv(timeframe):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=LIMIT)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# ====================== 信号生成（已修复） ======================
def generate_signal(df, period_name="短期"):
    # 必须按顺序计算指标，保证 ATR 存在
    df = calculate_ma(df)
    df = calculate_atr(df, 12)                    # ← 关键修复：确保 ATR 被加入 df
    df = calculate_supertrend(df)
    
    ma_p, ma_dev = calculate_ma200_deviation_percentile(df)
    st_p, st_dev = calculate_supertrend_deviation_percentile(df)
    
    latest = df.iloc[-1]
    price = round(latest['close'], 4)
    atr = round(latest['ATR'], 4)
    st_dir = "多头" if latest['ST_Direction'] == 1 else "空头"
    ma_trend = "多头排列" if latest['MA_50'] > latest['MA_200'] else "空头排列"

    # ==================== 信号条件逻辑 ====================
    if ma_p >= 82 and st_p >= 78:
        position = "极端高估"
        probability = "高"
        reason = "MA200分位数≥82 且 SuperTrend分位数≥78"
        action_plan = f"多头止盈1(减半): {round(price - atr*2.0,4)} | 多头止盈2(全平+反手做空): {round(price - atr*5.5,4)} | 反手做空挂单: {round(price + atr*0.8,4)}"
    elif ma_p >= 70 and st_p >= 68:
        position = "明显高估"
        probability = "中高"
        reason = "MA200分位数≥70 且 SuperTrend分位数≥68"
        action_plan = f"多头止盈1(减半): {round(price - atr*1.8,4)} | 多头止盈2(全平+反手做空): {round(price - atr*4.8,4)} | 反手做空挂单: {round(price + atr*0.6,4)}"
    elif ma_p <= 18 and st_p <= 22:
        position = "极端低估"
        probability = "高"
        reason = "MA200分位数≤18 且 SuperTrend分位数≤22"
        action_plan = f"空头止盈1(减半): {round(price + atr*2.0,4)} | 空头止盈2(全平+反手做多): {round(price + atr*5.5,4)} | 反手做多挂单: {round(price - atr*0.8,4)}"
    elif ma_p <= 30 and st_p <= 32:
        position = "明显低估"
        probability = "中高"
        reason = "MA200分位数≤30 且 SuperTrend分位数≤32"
        action_plan = f"空头止盈1(减半): {round(price + atr*1.8,4)} | 空头止盈2(全平+反手做多): {round(price + atr*4.8,4)} | 反手做多挂单: {round(price - atr*0.6,4)}"
    else:
        position = "正常区间"
        probability = "低"
        reason = "两个分位数均处于中间区域（MA200: {ma_p}%, ST: {st_p}%)"
        action_plan = "观望，暂不建议挂任何止盈或反手单"

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

**核心逻辑**：MA200偏离分位数与SuperTrend偏离分位数**独立统计**，两者同时满足极端条件才触发挂单建议。

---

### 一、交易指令

**【短期交易计划】（1-4小时 - 15分钟图）**
- 当前价格：**{short['price']}** USDT
- 当前位置：**{short['position']}**
- 回归概率：**{short['probability']}**
- MA200分位数：{short['ma_percentile']}% 
- SuperTrend分位数：{short['st_percentile']}%
- 建议操作：
  - **{short['action_plan']}**

**【中期交易计划】（4-12小时 - 1小时图）**
- 当前位置：**{mid['position']}**
- 回归概率：**{mid['probability']}**
- MA200分位数：{mid['ma_percentile']}% 
- SuperTrend分位数：{mid['st_percentile']}%
- 建议操作：
  - **{mid['action_plan']}**

---

### 二、交易逻辑与策略分析

**当前指标状态**：
- MA趋势：短期 {short['ma_trend']} | 中期 {mid['ma_trend']}
- SuperTrend：短期 {short['st_dir']} | 中期 {mid['st_dir']}
- ATR(12)：短期 {short['atr']} | 中期 {mid['atr']}

**信号触发条件总结**：
1. **极端高估**：MA200分位数 ≥ 82 **且** SuperTrend分位数 ≥ 78 → 概率「高」，挂多头分批止盈 + 反手做空单。
2. **明显高估**：MA200分位数 ≥ 70 **且** SuperTrend分位数 ≥ 68 → 概率「中高」。
3. **极端低估**：MA200分位数 ≤ 18 **且** SuperTrend分位数 ≤ 22 → 概率「高」，挂空头分批止盈 + 反手做多单。
4. **明显低估**：MA200分位数 ≤ 30 **且** SuperTrend分位数 ≤ 32 → 概率「中高」。
5. 其余情况 → 「正常区间」，概率「低」，建议观望。

**挂单逻辑**：
- 第一档止盈用于减半仓位，第二档用于清仓并反手。
- 所有价格均基于当前ATR动态计算。

**风险提示**：本报告仅供参考，不构成投资建议。请根据实际持仓灵活调整挂单价格。

---
*由 GitHub Actions 每30分钟自动更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("✅ 程序已修复并运行成功")

if __name__ == "__main__":
    main()
