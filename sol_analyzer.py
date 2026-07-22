import ccxt
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ====================== 配置 ======================
SYMBOL = 'SOL/USDT:USDT'
TIMEFRAME_SHORT = '30m'
TIMEFRAME_MID = '1h'
LIMIT = 200

okx = ccxt.okx({'enableRateLimit': True})

# ====================== 时间函数（已修复） ======================
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

# ====================== 数据获取 ======================
def fetch_ohlcv(timeframe, limit=200):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

def get_derivative_data():
    try:
        headers = {'Content-Type': 'application/json'}
        fr = requests.get("https://api.coinglass.com/api/fundingRate?symbol=SOL", headers=headers, timeout=10).json()
        funding_rate = float(fr.get('data', [{}])[0].get('rate', 0))
        return {"funding_rate": round(funding_rate, 4)}
    except:
        return {"funding_rate": 0.0}

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
    beijing_time = get_beijing_time()
    print(f"开始运行分析 - 北京时间: {beijing_time}")
    
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

**最后更新**：{beijing_time}（北京时间）

**数据来源**：OKX K线 + Coinglass 衍生数据  
**技术指标**：MA(10,50,100,200)、ATR(12)、SuperTrend(10,2.0)

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

**短期逻辑**：
- SuperTrend 方向：{"多头" if short_signal['direction']=='做多' else '空头' if short_signal['direction']=='做空' else '中性'}
- MA趋势：MA50 > MA200 = {"多头排列" if df_short['MA_50'].iloc[-1] > df_short['MA_200'].iloc[-1] else "空头排列"}
- 当前ATR(12) = {short_signal['atr']}，止损距离约 2.2×ATR
- 资金费率：{deriv['funding_rate']}%（{"正费率" if deriv['funding_rate'] > 0 else "负费率"}）

**中期逻辑**：基于1小时图判断，侧重趋势持续性，与短期逻辑一致但更注重大结构。

**核心策略**：仅当 SuperTrend 与 MA50/200 趋势共振时开仓，否则保持观望。止盈止损严格按ATR比例执行。

**风险提示**：本报告由固定量化规则自动生成，仅供学习和研究参考，不构成任何投资建议。交易有风险，请严格控制仓位。

---
*由 GitHub Actions 每 30 分钟自动运行并更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ 分析完成，README.md 已更新")

if __name__ == "__main__":
    main()
