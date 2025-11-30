import React from 'react';
import CoinChart from './components/CoinChart'; 

function App() {
  // 1. URL'den "symbol" parametresini al
  const queryParameters = new URLSearchParams(window.location.search);
  const urlSymbol = queryParameters.get("symbol");

  return (
    <>
      {/* --- KRİTİK DÜZELTME: BEYAZLIKLARI KALDIRAN GLOBAL STİL --- */}
      <style>
        {`
          body, html, #root {
            margin: 0;
            padding: 0;
            background-color: #0e1117; /* Streamlit ile aynı koyu renk */
            height: 100%;
            width: 100%;
            overflow: hidden; /* Yanlarda kaydırma çubuğu çıkmasın */
          }
        `}
      </style>

      <div className="App" style={{
        backgroundColor: '#0e1117',
        minHeight: '100vh', 
        width: '100vw', // Tam genişlik
        color: 'white',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        
        {urlSymbol ? (
          // --- MOD A: TEK COIN MODU (Streamlit İçin) ---
          // Kenar boşluğu (padding) olmadan tam ekran grafik
          <div style={{width: '100%', height: '100vh'}}>
             <CoinChart symbol={urlSymbol} timeframe="15m" />
          </div>
        ) : (
          // --- MOD B: DASHBOARD MODU (Tarayıcı İçin) ---
          <>
            <header style={{
              padding: '20px', 
              borderBottom: '1px solid #333',
              textAlign: 'center',
              marginBottom: '20px',
              width: '100%',
              backgroundColor: '#161b22'
            }}>
              <h1 style={{margin: 0, fontSize: '1.5rem', color: '#e6e6e6'}}>🚀 Profesyonel Grafik Ekranı</h1>
              <p style={{margin: '5px 0 0 0', opacity: 0.6, fontSize: '0.9rem'}}>TradingView Lightweight Charts & Python API</p>
            </header>

            <div style={{
              display: 'flex', 
              flexDirection: 'column',
              alignItems: 'center', 
              gap: '30px', 
              padding: '0 20px 40px 20px',
              width: '100%',
              boxSizing: 'border-box' // Padding'in genişliği taşirmasını engeller
            }}>
              {/* Örnek BTC Grafiği */}
              <div style={{width: '100%', maxWidth: '1000px', border: '1px solid #30363d', borderRadius: '6px', overflow: 'hidden', backgroundColor: '#0d1117'}}>
                <h3 style={{padding: '10px 15px', margin: 0, borderBottom: '1px solid #30363d', fontSize: '1rem', backgroundColor: '#161b22'}}>BTCUSDT - 15 Dakika</h3>
                <CoinChart symbol="BTCUSDT" timeframe="15m" />
              </div>

              {/* Örnek ETH Grafiği */}
              <div style={{width: '100%', maxWidth: '1000px', border: '1px solid #30363d', borderRadius: '6px', overflow: 'hidden', backgroundColor: '#0d1117'}}>
                <h3 style={{padding: '10px 15px', margin: 0, borderBottom: '1px solid #30363d', fontSize: '1rem', backgroundColor: '#161b22'}}>ETHUSDT - 1 Saat</h3>
                <CoinChart symbol="ETHUSDT" timeframe="1h" />
              </div>
            </div>
          </>
        )}

      </div>
    </>
  );
}

export default App;