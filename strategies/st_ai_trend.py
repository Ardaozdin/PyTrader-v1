import pandas as pd
import numpy as np
import pandas_ta as pta

try:
    from sklearn.ensemble import RandomForestClassifier
except ImportError:
    RandomForestClassifier = None


def calistir(df):
    # --- AI TREND PREDICTOR (MAKSİMUM SİNYAL) ---
    if RandomForestClassifier is None:
        return df

    ai_df = df.copy()
    ai_df["Returns"] = ai_df["close"].pct_change().fillna(0)

    if "RSI" in df.columns:
        ai_df["RSI"] = df["RSI"].fillna(50)
    else:
        ai_df["RSI"] = pta.rsi(ai_df["close"], length=14).fillna(50)

    ai_df["Target"] = np.where(ai_df["close"].shift(-1) > ai_df["close"], 1, 0)
    ai_df.replace([np.inf, -np.inf], 0, inplace=True)
    ai_df.fillna(0, inplace=True)

    if len(ai_df) > 10:
        features = ["Returns", "RSI"]
        model = RandomForestClassifier(
            n_estimators=100, min_samples_split=2, random_state=42
        )
        model.fit(ai_df[features], ai_df["Target"])
        predictions = model.predict(ai_df[features])

        # Her tahmini sinyale çevir
        for i, idx in enumerate(ai_df.index):
            if predictions[i] == 1:
                if df.loc[idx - 1, "Signal"] != 1 if idx > 0 else True:
                    df.loc[idx, "Signal"] = 1
            else:
                if df.loc[idx - 1, "Signal"] != -1 if idx > 0 else True:
                    df.loc[idx, "Signal"] = -1

    return df
