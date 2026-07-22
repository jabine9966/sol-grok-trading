import ccxt
import pandas as pd
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

# ====================== 配置 ======================
SYMBOL = 'SOL/USDT:USDT'
LIMIT = 1000

okx = ccxt.okx({'enableRateLimit': True})

# ====================== 时间函数 ======================
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
    recent = df['Deviation'].dropna().tail(800)          # 确保覆盖至少7天
    if len(recent) < 200:
        return 50.0
    current_dev = df['Deviation'].iloc[-1]
    percentile = (recent < current_dev).mean() * 100
    return round(percentile, 2)

# ====================== 数据获取 ======================
def fetch_ohlcv(timeframe, limit=1000):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# ====================== 均值回归信号生成（核心） ======================
def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    df = calculate_supertrend(df)
    percentile = calculate_deviation_percentile(df)
    latest = df.iloc[-1]
    price = latest['close']
    atr = latest['ATR']
    ma200 = latest['MA_200']
    st_dir = latest['ST_Direction']
    ma_trend_up = latest['MA_50'] > latest['MA_200']
    
    # 根据不同时间框架设置不同阈值
    if period_name == "短期":        # 15m 更激进
        high_p, low_p = 85, 15
        risk_percent = 1.5
    else:                            # 1h 更稳健
        high_p, low_p = 80, 20
        risk_percent = 1.0

    # 均值回归逻辑
    if percentile <= low_p and price < ma200 and st_dir == -1:           # 严重低估 + 处于空头趋势中
        direction = "做多"
        operation = "买入开多"
        strength = "强信号"
    elif percentile >= high_p and price > ma200 and st_dir == 1:         # 严重高估 + 处于多头趋势中
        direction = "做空"
        operation = "卖出开空"
        strength = "强信号"
    elif percentile <= 25 or percentile >= 75:
        direction = "观望"
        operation = "观望"
        strength = "中等偏离，需等待更极端分位数"
    else:
        direction = "观望"
        operation = "观望"
        strength = "分位数处于正常区间"

    if direction != "观望":
        entry = round(price * (1.0008 if direction == "做多" else 0.9992), 4)
        stop_loss = round(entry - atr * 2.0 if direction == "做多" else entry + atr * 2.0, 4)
        tp1 = round(entry + atr * 4.5 if direction == "做多" else entry - atr * 4.5, 4)
        tp2 = round(entry + atr * 8.0 if direction == "做多" else entry - atr * 8.0, 4)
    else:
        entry = stop_loss = tp1 = tp2 = "-"

    return {
        "direction": direction,
        "operation": operation,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "percentile": percentile,
        "atr": round(atr, 4),
        "strength": strength,
        "ma_trend": "多头排列" if ma_trend_up else "空头排列",
        "st_dir": "多头" if st_dir == 1 else "空头",
        "risk_percent": risk_percent
    }

# ====================== 主函数 ======================
def main():
    beijing_time = get_beijing_time()
    print(f"开始运行分析 - 北京时间: {beijing_time}")
    
    df_short = fetch_ohlcv('15m', LIMIT)
    df_mid = fetch_ohlcv('1h', LIMIT)
    
    short_signal = generate_signal(df_short, "短期")
    mid_signal = generate_signal(df_mid, "中期")
    
    readme_content = f"""# SOL 永续合约均值回归分析报告

**最后更新**：{beijing_time}（北京时间）

**策略类型**：均值回归策略  
**使用指标**：MA(10,50,100,200)、ATR(12)、SuperTrend(10,2.0) + 最近7天偏离值分位数

---

### 一、交易指令

**【短期交易计划】（1-4小时）**
- 方向：**{short_signal['direction']}**
- 操作：**{short_signal['operation']}**
- 挂单价格：{short_signal['entry']}
- 止损价格：{short_signal['stop_loss']}
- 止盈价格：TP1 {short_signal['tp1']} | TP2 {short_signal['tp2']}
- 建议仓位比例：{short_signal['risk_percent']}%

**【中期交易计划】（4-12小时）**
- 方向：**{mid_signal['direction']}**
- 操作：**{mid_signal['operation']}**
- 挂单价格：{mid_signal['entry']}
- 止损价格：{mid_signal['stop_loss']}
- 止盈价格：TP1 {mid_signal['tp1']} | TP2 {mid_signal['tp2']}
- 建议仓位比例：{mid_signal['risk_percent']}%

---

### 二、交易逻辑与策略分析

**偏离值分位数统计**（基于最近7天数据）：
- 短期（15分钟图）：当前价格偏离MA200的程度处于过去7天 **{short_signal['percentile']}% 分位**
- 中期（1小时图）：当前价格偏离MA200的程度处于过去7天 **{mid_signal['percentile']}% 分位**

**短期逻辑（15分钟图）**：
当前处于{short_signal['ma_trend']}，SuperTrend为{short_signal['st_dir']}。价格偏离MA200达到{short_signal['percentile']}%分位，属于{ "极端低估区域" if short_signal['percentile'] <= 25 else "极端高估区域" if short_signal['percentile'] >= 75 else "正常波动区间"}。结合SuperTrend过滤后，判断为{short_signal['strength']}。本策略核心是在价格严重偏离均值时进行反向回归交易，同时要求SuperTrend方向与大趋势环境配合。

**中期逻辑（1小时图）**：
当前处于{mid_signal['ma_trend']}，SuperTrend为{mid_signal['st_dir']}。价格偏离MA200达到{mid_signal['percentile']}%分位，属于{ "极端低估区域" if mid_signal['percentile'] <= 25 else "极端高估区域" if mid_signal['percentile'] >= 75 else "正常波动区间"}。中期判断更为谨慎，需更极端的偏离度才会触发信号。

**整体策略思路**：
本系统以MA200为均值基准，通过ATR标准化后的偏离值在过去7天的分位数作为主要决策依据。只有当分位数进入极端区域（低估<20或高估>80），同时SuperTrend趋势过滤条件满足时才开仓。止损设置在1.8~2.0倍ATR，止盈设置为4.5倍和8倍ATR，符合均值回归“快止损、让利润回归均值”的特点。非极端分位数一律观望，避免无效交易。

**风险提示**：本报告由量化规则自动生成，仅供学习和研究使用，不构成任何投资建议。交易有风险，请严格控制仓位和风险。

---
*由 GitHub Actions 每30分钟自动运行并更新此文件*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ 均值回归策略分析完成，README.md 已更新")

if __name__ == "__main__":
    main()
