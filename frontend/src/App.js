import React from 'react';
import CoinChart from './components/CoinChart'; 

function App() {
  // URL'den Parametreleri Oku
  const queryParameters = new URLSearchParams(window.location.search);
  
  const urlSymbol = queryParameters.get("symbol");
  const urlTimeframe = queryParameters.get("timeframe") || "15m";
  
  // Strateji ve Risk Ayarları (Yoksa Varsayılan)
  const urlStrategy = queryParameters.get("strategy");
  const urlTp = queryParameters.get("tp");
  const urlSl = queryParameters.get("sl");

  return (
    <>
      <style>
        {`
          body, html, #root {
            margin: 0;
            padding: 0;
            background-color: #0e1117;
            height: 100%;
            width: 100%;
            overflow: hidden; /* Kaydırma çubuğunu gizle */
          }
        `}
      </style>

      <div className="App" style={{
        backgroundColor: '#0e1117',
        minHeight: '100vh', 
        width: '100vw',
        color: 'white',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        
        {urlSymbol ? (
          // --- MOD A: STREAMLIT MODU (URL DOLU) ---
          <div style={{width: '100%', height: '100vh'}}>
             <CoinChart 
                symbol={urlSymbol} 
                timeframe={urlTimeframe} 
                strategy={urlStrategy}
                tp={urlTp}
                sl={urlSl}
             />
          </div>
        ) : (
          // --- MOD B: TARAYICI MODU (URL BOŞ) ---
          <div style={{textAlign: 'center', padding: '20px'}}>
             <h2>🚀 React Grafik Motoru Hazır</h2>
             <p>Lütfen Streamlit üzerinden bir coin seçin.</p>
             
             {/* Test İçin Örnek Grafik */}
             <div style={{width: '800px', height: '500px', margin: '20px auto', border: '1px solid #333'}}>
                <CoinChart symbol="BTCUSDT" timeframe="15m" />
             </div>
          </div>
        )}

      </div>
    </>
  );
}

export default App;