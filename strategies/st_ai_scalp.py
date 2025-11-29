import pandas as pd
import numpy as np
import pandas_ta as pta

try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:
    RandomForestClassifier = None


def calistir(df):
    # --- ULTRA AGRESİF AI HYBRID SCALPER + DYNAMIC TP/SL ---
    if RandomForestClassifier is None:
        return df

    ai_df = df.copy()
    ai_df["Returns"] = ai_df["close"].pct_change().fillna(0)
    ai_df["Body"] = (ai_df["close"] - ai_df["open"]) / ai_df["open"]
    ai_df["Range"] = (ai_df["high"] - ai_df["low"]) / ai_df["low"]
    ai_df["UpperWick"] = (ai_df["high"] - ai_df["close"]) / ai_df["close"]
    ai_df["LowerWick"] = (ai_df["close"] - ai_df["low"]) / ai_df["low"]
    ai_df["Mom1"] = ai_df["close"] - ai_df["close"].shift(1)
    ai_df["Mom2"] = ai_df["close"] - ai_df["close"].shift(2)
    ai_df["Mom3"] = ai_df["close"] - ai_df["close"].shift(3)
    ai_df["Direction"] = np.where(ai_df["close"] > ai_df["close"].shift(3), 1, -1)

    # HMA kontrolü
    if "HMA_9" in df.columns:
        hma_col = "HMA_9"
    elif "HMA_14" in df.columns:
        hma_col = "HMA_14"
    else:
        return df

    ai_df["HMA_Slope"] = (
        ai_df[hma_col].diff().rolling(3, min_periods=1).mean().fillna(0)
    )
    ai_df["HMA_Distance"] = (ai_df["close"] - ai_df[hma_col]) / ai_df["close"]

    # Wick ratio
    range_series = (ai_df["high"] - ai_df["low"]).replace(0, np.nan)
    top_wick = (ai_df["high"] - ai_df["close"]).fillna(0)
    bot_wick = (ai_df["close"] - ai_df["low"]).fillna(0)
    ai_df["Wick_Ratio"] = (
        ((top_wick + bot_wick) / range_series).replace([np.inf, -np.inf], 0).fillna(0)
    )

    # Volume spike
    if "volume" in ai_df.columns:
        vol_mean = ai_df["volume"].rolling(20, min_periods=1).mean().replace(0, np.nan)
        ai_df["VOL_SPIKE"] = (ai_df["volume"] / vol_mean).fillna(1)
    else:
        ai_df["VOL_SPIKE"] = 1.0

    # Target
    ai_df["Target"] = np.where(ai_df["close"].shift(-1) > ai_df["close"], 1, 0)
    ai_df.replace([np.inf, -np.inf], 0, inplace=True)
    ai_df.fillna(0, inplace=True)

    # --- MODEL ---
    if len(ai_df) > 30:
        features = [
            "Returns",
            "Body",
            "Range",
            "UpperWick",
            "LowerWick",
            "Mom1",
            "Mom2",
            "Mom3",
            "Direction",
            "HMA_Slope",
            "HMA_Distance",
            "Wick_Ratio",
            "VOL_SPIKE",
        ]

        model = RandomForestClassifier(
            n_estimators=500,
            max_depth=None,
            min_samples_split=2,
            min_samples_leaf=1,
            random_state=42,
            n_jobs=-1,
        )

        model.fit(ai_df[features], ai_df["Target"])
        predictions = model.predict_proba(ai_df[features])[:, 1]

        # --- ULTRA AGRESİF SİNYAL VE DYNAMIC TP/SL ---
        df["Signal"] = 0
        df["TP"] = np.nan
        df["SL"] = np.nan

        BASE_TP = 0.006  # %0.6
        BASE_SL = 0.008  # %0.8

        for i, idx in enumerate(ai_df.index):
            prob = predictions[i]
            # mum volatilitesi (range) bazlı dinamik TP/SL
            volatility = ai_df["Range"].iloc[i]
            tp_dynamic = BASE_TP * (1 + volatility)  # volatilite artınca TP de açılır
            sl_dynamic = BASE_SL * (1 + volatility)  # volatilite artınca SL de genişler

            if prob > 0.51:
                df.loc[idx, "Signal"] = 1
                df.loc[idx, "TP"] = df["close"].iloc[i] * (1 + tp_dynamic)
                df.loc[idx, "SL"] = df["close"].iloc[i] * (1 - sl_dynamic)
            elif prob < 0.49:
                df.loc[idx, "Signal"] = -1
                df.loc[idx, "TP"] = df["close"].iloc[i] * (1 - tp_dynamic)
                df.loc[idx, "SL"] = df["close"].iloc[i] * (1 + sl_dynamic)

    return df
