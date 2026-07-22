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
        return 50.0
    current_dev = df['Deviation'].iloc[-1]
    percentile = (recent < current_dev).mean() * 100
    return round(percentile, 2)

def fetch_ohlcv(timeframe, limit=1200):
    ohlcv = okx.fetch_ohlcv(SYMBOL, timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# ====================== 信号生成（按你的思路重写） ======================
def generate_signal(df, period_name="短期"):
    df = calculate_ma(df)
    df = calculate_supertrend(df)
    percentile = calculate_deviation_percentile(df)
    latest = df.iloc[-1]
    price = latest['close']
    atr = latest['ATR']
    st_dir = latest['ST_Direction']
    ma_trend_up = latest['MA_50'] > latest['MA_200']
    
    if period_name == "短期":
        risk_unit = 1.0
        thresholds = {"short_high": 78, "short_extreme": 87, "long_low": 22, "long_extreme": 13}
    else:
        risk_unit = 0.8
        thresholds = {"short_high": 75, "short_extreme": 85, "long_low": 25, "long_extreme": 15}

    # 多空独立判断
    long_entry = short_entry = "-"
    long_tp1 = long_tp2 = short_tp1 = short_tp2 = "-"
    action = "观望"

    if percentile <= thresholds["long_low"]:          # 低估区域 → 做多
        action = "做多（均值回归）"
        base = round(price * 0.999, 4)
        long_entry = f"初始建仓 {base} | 加仓1 {round(base*0.985,4)} | 加仓2 {round(base*0.97,4)}"
        long_tp1 = round(price + atr * 5.0, 4)       # 先平50%
        long_tp2 = round(price + atr * 10.0, 4)      # 剩余全部平仓
    elif percentile >= thresholds["short_high"]:      # 高估区域 → 做空
        action = "做空（均值回归）"
        base = round(price * 1.001, 4)
        short_entry = f"初始建仓 {base} | 加仓1 {round(base*1.015,4)} | 加仓2 {round(base*1.03,4)}"
        short_tp1 = round(price - atr * 5.0, 4)
        short_tp2 = round(price - atr * 10.0, 4)

    return {
        "action": action,
        "percentile": percentile,
        "long_entry": long_entry,
        "short_entry": short_entry,
        "long_tp1": long_tp1,
        "long_tp2": long_tp2,
        "short_tp1": short_tp1,
        "short_tp2": short_tp2,
        "atr": round(atr, 4),
        "st_dir": "多头" if st_dir == 1 else "空头",
        "ma_trend": "多头排列" if ma_trend_up else "空头排列",
        "risk_unit": risk_unit
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
**策略类型**：均值回归（双向独立交易）  
**决策核心**：最近7天偏离MA200的分位数 + MA + SuperTrend + ATR

---

### 一、交易指令

**【短期交易计划】（1-4小时，15分钟图）**
- 当前分位数：{short_signal['percentile']}%
- 交易方向：**{short_signal['action']}**
- 建仓计划：{short_signal['long_entry'] if '做多' in short_signal['action'] else short_signal['short_entry']}
- 止盈计划：TP1（平50%仓位）{short_signal['long_tp1'] if '做多' in short_signal['action'] else short_signal['short_tp1']} | TP2（平剩余50%仓位）{short_signal['long_tp2'] if '做多' in short_signal['action'] else short_signal['short_tp2']}
- 单批次建议仓位：{short_signal['risk_unit']}%

**【中期交易计划】（4-12小时，1小时图）**
- 当前分位数：{mid_signal['percentile']}%
- 交易方向：**{mid_signal['action']}**
- 建仓计划：{mid_signal['long_entry'] if '做多' in mid_signal['action'] else mid_signal['short_entry']}
- 止盈计划：TP1（平50%仓位）{mid_signal['long_tp1'] if '做多' in mid_signal['action'] else mid_signal['short_tp1']} | TP2（平剩余50%仓位）{mid_signal['long_tp2'] if '做多' in mid_signal['action'] else mid_signal['short_tp2']}
- 单批次建议仓位：{mid_signal['risk_unit']}%

---

### 二、交易逻辑与策略分析

**当前市场偏离状态**：
- 短期（15m）：价格偏离MA200处于过去7天 **{short_signal['percentile']}% 分位**
- 中期（1h）：价格偏离MA200处于过去7天 **{mid_signal['percentile']}% 分位**

**短期逻辑（15分钟图）**：
当前MA趋势为{short_signal['ma_trend']}，SuperTrend为{short_signal['st_dir']}。偏离值分位数达到{short_signal['percentile']}%。本策略以分位数为核心，当分位数进入极端低估（≤22%）或极端高估（≥78%）区域时，启动对应方向的**初始建仓**，之后随着分位数继续恶化（更低或更高），进行两次加仓。多空仓位完全独立管理，不设置传统止损，通过分批止盈（先平50%，后平剩余50%）来锁定回归利润。

**中期逻辑（1小时图）**：
当前MA趋势为{mid_signal['ma_trend']}，SuperTrend为{mid_signal['st_dir']}。偏离值分位数为{mid_signal['percentile']}%。中期采用相对保守的阈值，仅在更极端的分位数下才加仓，适合持有时间更长的仓位。

**整体策略思路**：
本系统完全围绕“偏离值分位数”设计交易计划。分位数是分批建仓的核心触发器，MA和SuperTrend用于辅助判断当前趋势环境是否适合继续加仓。采用双向独立交易模式，允许同时存在多头和空头仓位。止盈采用两阶段平仓（50% + 50%），不设置固定止损，依靠均值回归的概率优势来管理风险。

**风险提示**：本报告由固定量化规则自动生成，仅供学习和研究。不构成任何投资建议。实际交易中请根据实时资金情况和个人风险承受能力灵活调整仓位。

---
*由 GitHub Actions 每30分钟自动运行并更新*
"""

    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)
    
    print("✅ 双向均值回归策略已更新")

if __name__ == "__main__":
    main()
