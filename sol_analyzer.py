import ccxt
import pandas as pd
import numpy as np
import requests
import os
from datetime import datetime

# ====================== 配置 ======================
SYMBOL = 'SOL/USDT:USDT'
TIMEFRAME_SHORT = '30m'
TIMEFRAME_MID = '1h'
LIMIT = 200

okx = ccxt.okx({'enableRateLimit': True})

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

# ====================== 数据获取 ======================
def fetch_ohlcv(timeframe, limit=200):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def get_derivative_data():
    try:
        headers = {'Content-Type': 'application/json'}
        # 资金费率
        fr = requests.get("https://api.coinglass.com/api/fundingRate?symbol=SOL", headers=headers, timeout=10).json()
        funding_rate = float(fr.get('data', [{}])[0].get('rate', 0))
        # 持仓量
        oi = requests.get("https://api.coinglass.com/api/openInterest?symbol=SOL", headers=headers, timeout=10).json()
        open_interest = oi.get('data', [{}])[0].get('openInterest', 0)
        return {
            "funding_rate": round(funding_rate, 4),
            "open_interest": open_interest,
            "long_short_ratio": 1.15  # 简化值，后续可继续完善API
        }
    except Exception as e:
        return {"funding_rate": 0.0, "open_interest": 0, "long_short_ratio": 1.0}

# ====================== 信号生成 ======================
def generate_signal(df, period_name="短期"):
    latest = df.iloc[-1]
    ma_trend = latest['MA_50'] > latest['MA_200']
    st_dir = latest['ST_Direction']
    atr = latest['ATR']
    price = latest['close']
    
    if st_dir == 1 and ma_trend and price > latest['MA_50']:
        direction = "做多"
        operation = "买入开多"
        entry = round(price * 1.0005, 4)
        stop_loss = round(entry - atr * 2.2, 4)
        tp1 = round(entry + atr * 3.5, 4)
        tp2 = round(entry + atr * 6.5, 4)
    elif st_dir == -1 and not ma_trend and price < latest['MA_50']:
        direction = "做空"
        operation = "卖出开空"
        entry = round(price * 0.9995, 4)
        stop_loss = round(entry + atr * 2.2, 4)
        tp1 = round(entry - atr * 3.5, 4)
        tp2 = round(entry - atr * 6.5, 4)
    else:
        direction = "观望"
        operation = "观望"
        entry = stop_loss = tp1 = tp2 = "-"
    
    return {
        "direction": direction,
        "operation": operation,
        "entry": entry,
        "stop_loss": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "atr": round(atr, 4),
        "funding_rate": get_derivative_data()["funding_rate"]
    }

# ====================== 主函数 ======================
def main():
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S (北京时间)")
    print(f"开始运行分析 - {current_time}")
    
    df_short = fetch_ohlcv(TIMEFRAME_SHORT)
    df_mid = fetch_ohlcv(TIMEFRAME_MID)
    
    df_short = calculate_ma(df_short)
    df_short = calculate_supertrend(df_short)
    
    df_mid = calculate_ma(df_mid)
    df_mid = calculate_supertrend(df_mid)
    
    deriv = get_derivative_data()
    short_signal = generate_signal(df_short, "短期")
    mid_signal = generate_signal(df_mid, "中期")
    
    readme_content = f"""# SOL 永续合约量化分析报告

**最后更新**：{current_time}  
**数据来源**：OKX K线 + Coinglass 衍生数据  
**指标**：MA(10,50,100,200)、ATR(12)、SuperTrend(10,2.0)

---

### 一、交易指令

**【短期交易计划】（1-4小时）**
- 方向：**{short_signal['direction']}**
- 操作：**{short_signal['operation']}**
- 挂单价格：{short_signal['entry']}
- 止损价格：{short_signal['stop_loss']}
- 止盈价格：TP1 {short_signal['tp1']} | TP2 {short_signal['tp2']}
- 建议仓位比例：1.2%

**【中期交易计划】（4-12小时）**
- 方向：**{mid_signal['direction']}**
- 操作：**{mid_signal['operation']}**
- 挂单价格：{mid_signal['entry']}
- 止损价格：{mid_signal['stop_loss']}
- 止盈价格：TP1 {mid_signal['tp1']} | TP2 {mid_signal['tp2']}
- 建议仓位比例：0.8%

---

### 二、交易逻辑与策略分析

**市场结构判断**：当前以 SuperTrend(10,2.0) 为主趋势判断，结合 MA 趋势过滤。

**短期逻辑**：
- SuperTrend 方向：{"多头" if short_signal['direction']=='做多' else '空头' if short_signal['direction']=='做空' else '中性'}
- MA排列：MA50 > MA200 = {"多头趋势" if df_short['MA_50'].iloc[-1] > df_short['MA_200'].iloc[-1] else "空头趋势"}
- ATR(12) = {short_signal['atr']}，止损距离约 2.2 倍 ATR
- 资金费率：{deriv['funding_rate']}% （{ "正费率偏多" if deriv['funding_rate']>0 else "负费率偏空"}）

**中期逻辑**：同上，但基于 1 小时图判断，更注重趋势持续性。

**核心策略**：仅在 SuperTrend 与 MA 共振时开仓，否则观望。止盈止损严格按 ATR 比例设置，风险收益比约 1:3。

**风险提示**：本系统为规则驱动量化程序，仅供学习参考。交易有风险，实际使用请严格风控。

---
*由 GitHub Actions 每 30 分钟自动运行并更新此 README*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ 分析完成，README.md 已更新")

if __name__ == "__main__":
    main()
