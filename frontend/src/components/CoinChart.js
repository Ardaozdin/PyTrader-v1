import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import axios from 'axios';

const CoinChart = ({ symbol, timeframe, strategy, tp, sl }) => {
    const chartContainerRef = useRef();
    const chartRef = useRef(null);
    const seriesRef = useRef(null);     
    const smaSeriesRef = useRef(null);  

    // --- STATE ---
    const [isPanelOpen, setIsPanelOpen] = useState(false);
    const [currentPrice, setCurrentPrice] = useState(null);
    const [priceColor, setPriceColor] = useState('#fff');
    const [statusMsg, setStatusMsg] = useState("Veri Bekleniyor..."); // Kullanıcıya bilgi vermek için
    const [indicators, setIndicators] = useState({ sma: true, signals: true });
    const [chartData, setChartData] = useState([]);

    const toggleIndicator = (name) => {
        setIndicators(prev => ({ ...prev, [name]: !prev[name] }));
    };

    // --- 1. GÖRÜNÜRLÜK YÖNETİMİ ---
    useEffect(() => {
        if (!chartRef.current || !seriesRef.current || !smaSeriesRef.current) return;
        
        // SMA
        smaSeriesRef.current.applyOptions({ visible: indicators.sma });

        // SİNYALLER
        if (chartData.length > 0) {
            if (indicators.signals) {
                const markers = [];
                chartData.forEach(d => {
                    if (d.signal === 1) markers.push({ time: d.time, position: 'belowBar', color: '#26a69a', shape: 'arrowUp', text: 'AL', size: 2 });
                    else if (d.signal === -1) markers.push({ time: d.time, position: 'aboveBar', color: '#ef5350', shape: 'arrowDown', text: 'SAT', size: 2 });
                });
                markers.sort((a, b) => a.time - b.time);
                seriesRef.current.setMarkers(markers);
            } else {
                seriesRef.current.setMarkers([]);
            }
        }
    }, [indicators, chartData]);

    // --- 2. GRAFİK OLUŞTURMA ---
    useEffect(() => {
        if (!chartContainerRef.current) return;
        if (chartRef.current) { chartRef.current.remove(); chartRef.current = null; }

        try {
            const chart = createChart(chartContainerRef.current, {
                layout: { background: { type: ColorType.Solid, color: '#0e1117' }, textColor: '#d1d4dc', fontSize: 13, fontFamily: "'Inter', sans-serif" },
                grid: { vertLines: { color: 'rgba(42, 46, 57, 0.1)' }, horzLines: { color: 'rgba(42, 46, 57, 0.1)' } },
                width: chartContainerRef.current.clientWidth, height: 500,
                timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 10 },
                rightPriceScale: { minimumWidth: 75, borderColor: 'rgba(197, 203, 206, 0.2)' },
                crosshair: { mode: 1 },
            });

            const candlestickSeries = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350' });
            const smaSeries = chart.addLineSeries({ color: '#2962FF', lineWidth: 2, title: 'Trend', visible: indicators.sma });

            chartRef.current = chart;
            seriesRef.current = candlestickSeries;
            smaSeriesRef.current = smaSeries;

            const handleResize = () => { if (chartContainerRef.current && chartRef.current) chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth }); };
            window.addEventListener('resize', handleResize);
            return () => { window.removeEventListener('resize', handleResize); chart.remove(); };
        } catch (err) { console.error("Grafik başlatma hatası:", err); }
    }, []); 

    // --- 3. VERİ ÇEKME ---
    useEffect(() => {
        let intervalId;
        const fetchData = async (isUpdate = false) => {
            if (!chartRef.current || !seriesRef.current) return;
            
            try {
                // URL Parametreleri
                const activeStrategy = strategy || "Pure_Supertrend_Strategy";
                const activeTp = tp || "0.006";
                const activeSl = sl || "0.01";
                const timestamp = new Date().getTime(); // Cache Buster
                
                const url = `http://localhost:8000/data?symbol=${symbol}&timeframe=${timeframe}&strategy=${activeStrategy}&tp=${activeTp}&sl=${activeSl}&_t=${timestamp}`;
                
                if(!isUpdate) setStatusMsg("Veri Yükleniyor...");
                
                const response = await axios.get(url);
                let rawData = response.data;

                if (rawData && Array.isArray(rawData) && rawData.length > 0) {
                    setStatusMsg(""); // Veri geldi, mesajı sil
                    
                    const processedData = rawData.map(d => ({ ...d, time: parseInt(d.time), sma: parseFloat(d.sma) || 0 })).sort((a, b) => a.time - b.time);
                    setChartData(processedData);

                    const lastData = processedData[processedData.length - 1];
                    const prevData = processedData.length > 1 ? processedData[processedData.length - 2] : lastData;
                    setCurrentPrice(lastData.close);
                    setPriceColor(lastData.close >= prevData.close ? '#26a69a' : '#ef5350');

                    const candleData = processedData.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close }));
                    const smaData = processedData.map(d => ({ time: d.time, value: d.sma })).filter(d => d.value !== 0);

                    if (!isUpdate) {
                        seriesRef.current.setData(candleData);
                        smaSeriesRef.current.setData(smaData);
                        chartRef.current.timeScale().fitContent();
                    } else {
                        seriesRef.current.update(candleData[candleData.length - 1]);
                        if (smaData.length > 0) smaSeriesRef.current.update(smaData[smaData.length - 1]);
                    }
                } else {
                    setStatusMsg("Veri Yok veya Hatalı.");
                }
            } catch (err) {
                console.error("API Hatası:", err);
                setStatusMsg("API Bağlantı Hatası!");
            }
        };

        fetchData(false);
        intervalId = setInterval(() => { fetchData(true); }, 5000); 
        return () => clearInterval(intervalId);

    }, [symbol, timeframe, strategy, tp, sl]); 

    return (
        <div style={{ position: 'relative', width: '100%', height: '500px', border: '1px solid #333', borderRadius: '8px', overflow: 'hidden', backgroundColor: '#0e1117' }}>
            
            {/* DURUM MESAJI (Veri yoksa ortada görünür) */}
            {statusMsg && (
                <div style={{position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', color: '#fff', zIndex: 50}}>
                    {statusMsg}
                </div>
            )}

            {/* CANLI FİYAT */}
            <div style={{ position: 'absolute', top: '10px', left: '50%', transform: 'translateX(-50%)', zIndex: 15, backgroundColor: 'rgba(14, 17, 23, 0.85)', padding: '5px 15px', borderRadius: '20px', border: `1px solid ${priceColor}`, backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span style={{color: '#d1d4dc', fontWeight: 'bold', fontSize: '14px'}}>{symbol}</span>
                <span style={{color: priceColor, fontWeight: 'bold', fontSize: '16px'}}>${currentPrice ? currentPrice.toFixed(2) : '---'}</span>
            </div>

            {/* AYAR BUTONU */}
            <div style={{ position: 'absolute', top: '10px', left: '10px', zIndex: 20, backgroundColor: 'rgba(30, 34, 45, 0.9)', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', color: '#d1d4dc', fontSize: '13px', fontWeight: '600', border: '1px solid #444' }} onClick={() => setIsPanelOpen(!isPanelOpen)}>⚙️</div>

            {/* PANEL */}
            {isPanelOpen && (
                <div style={{ position: 'absolute', top: '45px', left: '10px', zIndex: 20, backgroundColor: 'rgba(22, 27, 34, 0.95)', padding: '15px', borderRadius: '8px', border: '1px solid #444', minWidth: '160px' }}>
                    <div style={{marginBottom: '10px', color: '#8b949e', fontSize: '11px', fontWeight: 'bold'}}>GÖRÜNÜRLÜK</div>
                    <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer', marginBottom: '8px', color: '#fff', fontSize: '13px'}}><input type="checkbox" checked={indicators.sma} onChange={() => toggleIndicator('sma')} style={{marginRight: '8px'}} />Trend Çizgisi</label>
                    <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer', color: '#fff', fontSize: '13px'}}><input type="checkbox" checked={indicators.signals} onChange={() => toggleIndicator('signals')} style={{marginRight: '8px'}} />AL/SAT Sinyalleri</label>
                </div>
            )}

            <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
        </div>
    );
};

export default CoinChart;