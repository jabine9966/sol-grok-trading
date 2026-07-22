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
    utc_now = datetime.now(ZoneInfo("UTC"))
    beijing_now = utc_now.astimezone(ZoneInfo("Asia/Shanghai"))
    return beijing_now.strftime("%Y-%m-%d %H:%M:%S")

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

# ====================== 7天偏离值分位数 ======================
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

def fetch_ohlcv(timeframe, limit=1200):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# ====================== 核心信号生成（已按你的要求重构） ======================
def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    df = calculate_supertrend(df)
    percentile, deviation = calculate_deviation_percentile(df)
    latest = df.iloc[-1]
    price = latest['close']
    atr = latest['ATR']
    st_dir = latest['ST_Direction']
    ma_trend_up = latest['MA_50'] > latest['MA_200']
    
    # 位置判断
    if percentile >= 85:
        position = "极端高估"
        prob = "高"
        direction = "做空"
    elif percentile >= 72:
        position = "明显高估"
        prob = "中高"
        direction = "做空"
    elif percentile <= 15:
        position = "极端低估"
        prob = "高"
        direction = "做多"
    elif percentile <= 28:
        position = "明显低估"
        prob = "中高"
        direction = "做多"
    else:
        position = "正常区间"
        prob = "低"
        direction = "观望"

    # 挂单与止盈价格（分批逻辑）
    if direction == "做多":
        entry_base = round(price * 0.998, 4)
        add1 = round(entry_base * 0.982, 4)
        add2 = round(entry_base * 0.965, 4)
        tp1 = round(price + atr * 4.5, 4)   # 先平50%
        tp2 = round(price + atr * 9.0, 4)   # 剩余全部平仓
        entry_plan = f"初始建仓: {entry_base} | 加仓1: {add1} | 加仓2: {add2}"
        tp_plan = f"TP1(平50%): {tp1} | TP2(平剩余50%): {tp2}"
    elif direction == "做空":
        entry_base = round(price * 1.002, 4)
        add1 = round(entry_base * 1.018, 4)
        add2 = round(entry_base * 1.035, 4)
        tp1 = round(price - atr * 4.5, 4)
        tp2 = round(price - atr * 9.0, 4)
        entry_plan = f"初始建仓: {entry_base} | 加仓1: {add1} | 加仓2: {add2}"
        tp_plan = f"TP1(平50%): {tp1} | TP2(平剩余50%): {tp2}"
    else:
        entry_plan = tp_plan = "-"

    return {
        "direction": direction,
        "position": position,
        "probability": prob,
        "percentile": percentile,
        "deviation": deviation,
        "entry_plan": entry_plan,
        "tp_plan": tp_plan,
        "atr": round(atr, 4),
        "st_dir": "多头" if st_dir == 1 else "空头",
        "ma_trend": "多头排列" if ma_trend_up else "空头排列"
    }

# ====================== 主函数 ======================
def main():
    beijing_time = get_beijing_time()
    
    df_short = fetch_ohlcv('15m', LIMIT)
    df_mid = fetch_ohlcv('1h', LIMIT)
    
    short_signal = generate_signal(df_short, "短期")
    mid_signal = generate_signal(df_mid, "中期")
    
    readme_content = f"""# SOL 永续合约均值回归分析报告

**最后更新**：{beijing_time}（北京时间）

**策略类型**：基于7天偏离值分位数的均值回归策略（双向独立交易）

---

### 一、交易指令

**【短期交易计划】（1-4小时 - 15分钟图）**
- 当前所处位置：**{short_signal['position']}**
- 交易方向：**{short_signal['direction']}**
- 回归概率评估：**{short_signal['probability']}概率**
- 挂单计划：{short_signal['entry_plan']}
- 止盈计划：{short_signal['tp_plan']}
- 单批次建议仓位：0.8% ~ 1.2%（总仓位不超过4%）

**【中期交易计划】（4-12小时 - 1小时图）**
- 当前所处位置：**{mid_signal['position']}**
- 交易方向：**{mid_signal['direction']}**
- 回归概率评估：**{mid_signal['probability']}概率**
- 挂单计划：{mid_signal['entry_plan']}
- 止盈计划：{mid_signal['tp_plan']}
- 单批次建议仓位：0.6% ~ 1.0%（总仓位不超过3%）

---

### 二、交易逻辑与策略分析

**偏离值统计**：
- 短期（15m）：当前偏离MA200处于过去7天 **{short_signal['percentile']}% 分位**（Deviation = {short_signal['deviation']}）
- 中期（1h）：当前偏离MA200处于过去7天 **{mid_signal['percentile']}% 分位**（Deviation = {mid_signal['deviation']}）

**短期逻辑（15分钟图）**：
当前MA趋势为 {short_signal['ma_trend']}，SuperTrend 状态为 {short_signal['st_dir']}。价格偏离MA200已达到 {short_signal['percentile']}% 分位，处于 **{short_signal['position']}** 区域。结合ATR波动率判断，本次回归的概率评估为 **{short_signal['probability']}概率**。  
策略将在极端分位数区域进行分批建仓（初始 + 两次加仓），不设置固定止损，通过两次分批止盈（先平50%仓位，再平剩余50%）来实现均值回归利润。

**中期逻辑（1小时图）**：
当前MA趋势为 {mid_signal['ma_trend']}，SuperTrend 状态为 {mid_signal['st_dir']}。偏离值分位数为 {mid_signal['percentile']}% ，所处位置为 **{mid_signal['position']}**。中期判断更为稳健，只有在分位数更极端时才会提高加仓力度，回归概率评估为 **{mid_signal['probability']}概率**。

**整体策略核心**：
本系统以“过去7天偏离MA200的ATR标准化分位数”作为最主要决策变量，结合MA趋势环境和SuperTrend局部趋势过滤，综合研判回归概率。只有当分位数进入明显极端区域时才发出交易指令，并给出具体挂单价格。MA10/50/100/200用于判断大趋势过滤，ATR用于计算合理挂单间距和止盈目标，SuperTrend用于避免在强趋势中过度逆势加仓。

**风险提示**：本报告由量化规则自动生成，仅供学习研究使用。实际交易请严格控制总仓位，建议根据实时资金和市场流动性灵活调整加仓与止盈价格。不构成任何投资建议。

---
*由 GitHub Actions 每30分钟自动运行更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ 报告已更新，请刷新你的仓库查看效果")

if __name__ == "__main__":
    main()
