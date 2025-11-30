import React, { useEffect, useRef, useState } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import axios from 'axios';

const CoinChart = ({ symbol, timeframe }) => {
    const chartContainerRef = useRef();
    const chartRef = useRef(null);
    const seriesRef = useRef(null);     // Mum Grafiği
    const smaSeriesRef = useRef(null);  // SMA Çizgisi

    // --- STATE YÖNETİMİ ---
    const [isPanelOpen, setIsPanelOpen] = useState(false);
    const [chartData, setChartData] = useState([]); // Veriyi burada saklıyoruz
    const [currentPrice, setCurrentPrice] = useState(null);
    const [priceColor, setPriceColor] = useState('#fff');
    
    const [indicators, setIndicators] = useState({
        sma: true,    
        signals: true 
    });

    const toggleIndicator = (name) => {
        setIndicators(prev => ({ ...prev, [name]: !prev[name] }));
    };

    // --- 1. GÖRÜNÜRLÜK YÖNETİMİ (ZOOM BOZMADAN ÇALIŞAN KISIM) ---
    // Bu kısım sadece butona basınca çalışır, veriyi yeniden çekmez.
    useEffect(() => {
        // SMA Çizgisini Aç/Kapa
        if (smaSeriesRef.current) {
            smaSeriesRef.current.applyOptions({ visible: indicators.sma });
        }

        // Sinyalleri (Okları) Aç/Kapa
        if (seriesRef.current && chartData.length > 0) {
            if (indicators.signals) {
                // Eğer açıksa, hafızadaki veriden markerları oluştur ve ekle
                const markers = [];
                chartData.forEach(d => {
                    if (d.signal === 1) markers.push({ time: d.time, position: 'belowBar', color: '#26a69a', shape: 'arrowUp', text: 'AL', size: 2 });
                    else if (d.signal === -1) markers.push({ time: d.time, position: 'aboveBar', color: '#ef5350', shape: 'arrowDown', text: 'SAT', size: 2 });
                });
                markers.sort((a, b) => a.time - b.time);
                seriesRef.current.setMarkers(markers);
            } else {
                // Eğer kapalıysa, markerları temizle (Zoom bozulmaz)
                seriesRef.current.setMarkers([]);
            }
        }
    }, [indicators, chartData]); // Sadece göstergeler veya veri değişince çalışır

    // --- 2. GRAFİĞİ OLUŞTUR (SADECE BİR KERE) ---
    useEffect(() => {
        if (!chartContainerRef.current) return;

        if (chartRef.current) {
            chartRef.current.remove();
            chartRef.current = null;
        }

        try {
            const chart = createChart(chartContainerRef.current, {
                layout: {
                    background: { type: ColorType.Solid, color: '#0e1117' },
                    textColor: '#d1d4dc',
                    fontSize: 14,
                    fontFamily: "'Inter', sans-serif", 
                },
                grid: {
                    vertLines: { color: 'rgba(42, 46, 57, 0.2)' },
                    horzLines: { color: 'rgba(42, 46, 57, 0.2)' },
                },
                width: chartContainerRef.current.clientWidth,
                height: 500,
                timeScale: {
                    timeVisible: true,
                    secondsVisible: false,
                    rightOffset: 12,
                },
                rightPriceScale: {
                    minimumWidth: 75,
                    scaleMargins: { top: 0.1, bottom: 0.1 },
                    borderColor: 'rgba(197, 203, 206, 0.4)',
                },
                crosshair: { mode: 1 },
            });

            const candlestickSeries = chart.addCandlestickSeries({
                upColor: '#26a69a',
                downColor: '#ef5350',
                borderVisible: false,
                wickUpColor: '#26a69a',
                wickDownColor: '#ef5350',
            });

            const smaSeries = chart.addLineSeries({
                color: '#2962FF',
                lineWidth: 2,
                title: 'SMA 9',
                visible: indicators.sma, 
            });

            chartRef.current = chart;
            seriesRef.current = candlestickSeries;
            smaSeriesRef.current = smaSeries;

            const handleResize = () => {
                if (chartContainerRef.current && chartRef.current) {
                    chartRef.current.applyOptions({ width: chartContainerRef.current.clientWidth });
                }
            };
            window.addEventListener('resize', handleResize);

        } catch (err) {
            console.error("Grafik hatası:", err);
        }

        return () => {
            if (chartRef.current) {
                chartRef.current.remove();
                chartRef.current = null;
            }
        };
    }, []); 

    // --- 3. VERİ ÇEKME (PERİYODİK) ---
    useEffect(() => {
        let intervalId;

        const fetchData = async (isUpdate = false) => {
            if (!chartRef.current || !seriesRef.current || !smaSeriesRef.current) return;

            try {
                const response = await axios.get(`http://localhost:8000/data?symbol=${symbol}&timeframe=${timeframe}`);
                let data = response.data;

                if (data && Array.isArray(data) && data.length > 0) {
                    data.sort((a, b) => a.time - b.time);
                    
                    // Veriyi State'e kaydet (Marker yönetimi için)
                    setChartData(data);

                    // Son Fiyat
                    const lastData = data[data.length - 1];
                    const prevData = data.length > 1 ? data[data.length - 2] : lastData;
                    setCurrentPrice(lastData.close);
                    setPriceColor(lastData.close >= prevData.close ? '#26a69a' : '#ef5350');

                    const candleData = data.map(d => ({
                        time: d.time, open: d.open, high: d.high, low: d.low, close: d.close
                    }));

                    const smaData = data.map(d => ({
                        time: d.time, value: d.sma
                    })).filter(d => d.value !== 0);

                    if (!isUpdate) {
                        // İlk yükleme
                        seriesRef.current.setData(candleData);
                        smaSeriesRef.current.setData(smaData);
                        chartRef.current.timeScale().fitContent(); // SADECE BURADA ZOOM SIFIRLANIR
                    } else {
                        // Güncelleme (Zoom bozulmaz)
                        const lastCandle = candleData[candleData.length - 1];
                        const lastSma = smaData[smaData.length - 1];
                        seriesRef.current.update(lastCandle);
                        if (lastSma) smaSeriesRef.current.update(lastSma);
                    }
                }
            } catch (err) {
                console.error("Veri çekme hatası:", err);
            }
        };

        fetchData(false);
        intervalId = setInterval(() => { fetchData(true); }, 5000); 
        return () => clearInterval(intervalId);
    }, [symbol, timeframe]); // indicators.signals BURADAN KALDIRILDI!

    return (
        <div style={{ position: 'relative', width: '100%', border: '1px solid #333', borderRadius: '8px', overflow: 'hidden', backgroundColor: '#0e1117' }}>
            
            {/* CANLI FİYAT */}
            <div style={{
                position: 'absolute', top: '10px', left: '50%', transform: 'translateX(-50%)', zIndex: 15,
                backgroundColor: 'rgba(14, 17, 23, 0.7)', padding: '5px 15px', borderRadius: '20px',
                border: `1px solid ${priceColor}`, backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', gap: '10px'
            }}>
                <span style={{color: '#d1d4dc', fontWeight: 'bold', fontSize: '14px'}}>{symbol}</span>
                <span style={{color: priceColor, fontWeight: 'bold', fontSize: '16px'}}>
                    ${currentPrice ? currentPrice.toFixed(2) : '---'}
                </span>
            </div>

            {/* İNDİKATÖR PANELİ */}
            <div style={{
                position: 'absolute', top: '10px', left: '10px', zIndex: 20,
                backgroundColor: 'rgba(30, 34, 45, 0.8)', padding: '6px 12px', borderRadius: '4px',
                cursor: 'pointer', color: '#d1d4dc', fontSize: '13px', fontWeight: '600',
                border: '1px solid #444', userSelect: 'none', backdropFilter: 'blur(4px)'
            }} onClick={() => setIsPanelOpen(!isPanelOpen)}>
                ⚙️ Göstergeler
            </div>

            {isPanelOpen && (
                <div style={{
                    position: 'absolute', top: '45px', left: '10px', zIndex: 20,
                    backgroundColor: 'rgba(22, 27, 34, 0.95)', padding: '15px', borderRadius: '8px',
                    border: '1px solid #444', minWidth: '160px', boxShadow: '0 8px 16px rgba(0,0,0,0.4)',
                    backdropFilter: 'blur(10px)'
                }}>
                    <div style={{marginBottom: '12px', color: '#8b949e', fontSize: '11px', fontWeight: 'bold', letterSpacing: '1px'}}>GÖRÜNÜRLÜK</div>
                    
                    <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer', marginBottom: '10px', color: '#e6e6e6', fontSize: '13px'}}>
                        <input type="checkbox" checked={indicators.sma} onChange={() => toggleIndicator('sma')} style={{marginRight: '10px', accentColor: '#2962FF'}} />
                        SMA 9 (Trend)
                    </label>

                    <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer', color: '#e6e6e6', fontSize: '13px'}}>
                        <input type="checkbox" checked={indicators.signals} onChange={() => toggleIndicator('signals')} style={{marginRight: '10px', accentColor: '#26a69a'}} />
                        AL/SAT Sinyalleri
                    </label>
                </div>
            )}

            <div ref={chartContainerRef} style={{ height: '500px' }} />
        </div>
    );
};

export default CoinChart;