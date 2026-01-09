/**
 * PolySurge - Polymarket 异常信号雷达
 * 前端应用逻辑
 */

// 使用本地代理解决 CORS 问题
const API_BASE = '/api';
const GAMMA_BASE = '/api/gamma';

// 全局状态
let allEvents = [];
let markets = [];
let isLoading = false;
let lastEventCount = 0;  // 用于通知
let timeFilter = 'all';  // 时间筛选: 1h, 6h, 24h, all

// 异常类型配置
const ANOMALY_CONFIG = {
    volume_spike: {
        name: '成交量飙升',
        color: 'green',
        icon: '📈',
        multiplier: 5
    },
    whale_trade: {
        name: '大额交易',
        color: 'blue',
        icon: '🐋',
        multiplier: 20
    },
    imbalance: {
        name: '买卖失衡',
        color: 'yellow',
        icon: '⚖️',
        threshold: 0.8
    },
    price_move: {
        name: '价格异动',
        color: 'pink',
        icon: '💹',
        threshold: 0.1
    },
    high_frequency: {
        name: '高频交易',
        color: 'red',
        icon: '⚡',
        threshold: 10
    }
};

// 市场类型配置
const MARKET_TYPES = {
    short_term: { name: '短期市场', color: 'blue' },
    sports: { name: '体育市场', color: 'green' },
    general: { name: '一般市场', color: 'purple' }
};

/**
 * 初始化应用
 */
async function init() {
    console.log('PolySurge 初始化...');

    // 显示加载状态
    updateLoadingStatus('连接 Polymarket API...', 5);

    await refreshData();

    // 隐藏加载界面
    hideLoading();

    // 每30秒自动刷新
    setInterval(refreshData, 30000);
}

/**
 * 更新加载状态和进度
 */
function updateLoadingStatus(status, percent = null) {
    const el = document.getElementById('loading-status');
    if (el) el.textContent = status;

    if (percent !== null) {
        const progressBar = document.getElementById('loading-progress');
        const percentText = document.getElementById('loading-percent');
        if (progressBar) progressBar.style.width = `${percent}%`;
        if (percentText) percentText.textContent = `${Math.round(percent)}%`;
    }
}

/**
 * 隐藏加载界面
 */
function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.style.transition = 'opacity 0.5s ease';
        overlay.style.opacity = '0';
        setTimeout(() => {
            overlay.style.display = 'none';
        }, 500);
    }
}

/**
 * 刷新所有数据
 */
async function refreshData() {
    if (isLoading) return;
    isLoading = true;

    try {
        // 获取市场列表 - 智能选择高价值市场
        updateLoadingStatus('获取市场列表...', 10);
        markets = await fetchMarkets(100);

        // 获取交易数据并检测异常
        updateLoadingStatus(`分析 ${markets.length} 个市场...`, 30);
        allEvents = await analyzeAllMarkets(markets);

        // 统计钱包活跃度
        updateLoadingStatus('统计钱包活跃度...', 80);
        updateWalletStats(allEvents);

        // 检查新事件并通知
        checkNewEvents(allEvents.length);

        // 更新所有UI组件
        updateLoadingStatus('渲染界面...', 95);
        updateUI();
    } catch (error) {
        console.error('刷新数据失败:', error);
    } finally {
        isLoading = false;
    }
}

/**
 * 统计钱包活跃度（鲸鱼追踪）
 */
function updateWalletStats(events) {
    walletStats = {};
    events.forEach(e => {
        // 简化：用conditionId+时间作为唯一交易标识
        const key = `${e.conditionId}_${e.timestamp}`;
        // 这里我们无法获取具体钱包，但可以统计事件中的钱包数
    });
}

/**
 * 检查新事件并发送通知
 */
function checkNewEvents(newCount) {
    if (lastEventCount > 0 && newCount > lastEventCount) {
        const diff = newCount - lastEventCount;
        // 发送浏览器通知
        if (Notification.permission === 'granted') {
            new Notification('PolySurge 异常信号', {
                body: `检测到 ${diff} 个新异常事件`,
                icon: '⚡'
            });
        }
        // 播放提示音
        playAlertSound();
    }
    lastEventCount = newCount;
}

/**
 * 播放提示音
 */
function playAlertSound() {
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2teleR4HJGWs0dyxbSQKF0xtnsLQqXErIChWfpKxwo1mOh8nPV9/kYxzW0MdKS84Vmo=');
        audio.volume = 0.3;
        audio.play().catch(() => {});
    } catch (e) {}
}

/**
 * 获取市场列表 - 智能选择高价值市场
 */
async function fetchMarkets(limit) {
    const resp = await fetch(`${GAMMA_BASE}/markets?limit=${limit * 3}&active=true&closed=false&order=volume24hr&ascending=false`);
    const data = await resp.json();

    // 智能过滤和排序
    const processed = data
        .filter(m => {
            // 必须有 conditionId
            if (!m.conditionId) return false;

            // 必须有一定的成交量（过滤冷清市场）
            const volume = m.volume24hrClob || m.volume24hr || 0;
            if (volume < 100) return false;  // 最少 $100 日成交

            // 必须有流动性
            const liquidity = m.liquidity || 0;
            if (liquidity < 10) return false;  // 最少 $10 流动性

            return true;
        })
        .map(m => {
            const slug = (m.slug || '').toLowerCase();
            let type = 'general';

            if (/15m|30m|1h|hour|minute|daily|today|intraday/.test(slug)) {
                type = 'short_term';
            } else if (/nba|nfl|mlb|nhl|soccer|football|match|game|vs|win-on|warriors|lakers|celtics|bulls|knicks|heat|jazz/.test(slug)) {
                type = 'sports';
            }

            const volume = m.volume24hrClob || m.volume24hr || 0;
            const liquidity = m.liquidity || 0;

            // 计算市场价值分数
            // 高成交量 + 高流动性 = 高分
            const score = (volume * 0.7) + (liquidity * 0.3);

            return {
                conditionId: m.conditionId,
                question: m.question || '',
                slug: slug,
                eventSlug: (m.events && m.events[0] && m.events[0].slug) || slug,  // 使用 event slug
                type: type,
                volume24h: volume,
                liquidity: liquidity,
                score: score,
                // 额外的市场数据
                bestBid: m.bestBid || 0,
                bestAsk: m.bestAsk || 1,
                lastPrice: m.lastTradePrice || 0,
                spread: m.spread || 0,
                priceChange: m.oneDayPriceChange || m.oneWeekPriceChange || 0,
                outcomes: m.outcomes || '["Yes", "No"]'
            };
        })
        // 按价值分数排序
        .sort((a, b) => b.score - a.score)
        .slice(0, limit);

    console.log(`智能选择了 ${processed.length} 个高价值市场`);
    console.log(`  - 短期市场: ${processed.filter(m => m.type === 'short_term').length}`);
    console.log(`  - 体育市场: ${processed.filter(m => m.type === 'sports').length}`);
    console.log(`  - 一般市场: ${processed.filter(m => m.type === 'general').length}`);

    return processed;
}

/**
 * 获取市场交易数据
 */
async function fetchTrades(conditionId, limit = 500) {
    try {
        const resp = await fetch(`${API_BASE}/trades?market=${conditionId}&limit=${limit}`);
        return await resp.json();
    } catch {
        return [];
    }
}

/**
 * 分析所有市场
 */
async function analyzeAllMarkets(markets) {
    const events = [];
    const batchSize = 10;

    for (let i = 0; i < markets.length; i += batchSize) {
        const batch = markets.slice(i, i + batchSize);
        const promises = batch.map(async market => {
            const trades = await fetchTrades(market.conditionId);
            if (trades.length < 10) return [];

            const marketEvents = detectAnomalies(trades, market);
            return marketEvents;
        });

        const results = await Promise.all(promises);
        results.forEach(r => events.push(...r));

        // 更新进度
        const progress = 30 + (i / markets.length) * 50;
        updateLoadingStatus(`分析市场 ${Math.min(i + batchSize, markets.length)}/${markets.length}...`, progress);

        // 短暂延迟避免请求过快
        await new Promise(resolve => setTimeout(resolve, 100));
    }

    // 按时间排序
    return events.sort((a, b) => b.timestamp - a.timestamp);
}

/**
 * 检测异常
 */
function detectAnomalies(trades, market) {
    const events = [];
    const windowSec = 300; // 5分钟窗口

    // 按时间排序
    trades = trades.sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

    // 计算基准值
    const allStats = [];
    for (let i = 0; i < trades.length; i++) {
        const currentTime = trades[i].timestamp;
        const window = trades.slice(0, i + 1).filter(t =>
            currentTime - windowSec <= t.timestamp && t.timestamp <= currentTime
        );

        if (window.length >= 3) {
            const wallets = new Set(window.map(t => t.proxyWallet)).size;
            const volume = window.reduce((sum, t) => sum + (t.size || 0) * (t.price || 0), 0);
            allStats.push({ wallets, volume });
        }
    }

    if (allStats.length === 0) return events;

    const medianWallets = median(allStats.map(s => s.wallets));
    const medianVolume = median(allStats.map(s => s.volume));
    const medianTradeSize = median(trades.map(t => (t.size || 0) * (t.price || 0)));

    // 检测每个时间点
    for (let i = 0; i < trades.length; i++) {
        const t = trades[i];
        const currentTime = t.timestamp;

        const window = trades.slice(0, i + 1).filter(x =>
            currentTime - windowSec <= x.timestamp && x.timestamp <= currentTime
        );

        if (window.length < 3) continue;

        // 计算指标
        const wallets = new Set(window.map(x => x.proxyWallet));
        const walletCount = wallets.size;

        const buyVol = window.filter(x => x.side === 'BUY')
            .reduce((sum, x) => sum + (x.size || 0) * (x.price || 0), 0);
        const sellVol = window.filter(x => x.side === 'SELL')
            .reduce((sum, x) => sum + (x.size || 0) * (x.price || 0), 0);
        const totalVol = buyVol + sellVol;
        const netVol = buyVol - sellVol;

        const prices = window.map(x => x.price || 0);
        const priceRange = Math.max(...prices) - Math.min(...prices);
        const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;

        const currentSize = (t.size || 0) * (t.price || 0);
        const tradeFreq = window.length;

        // 检测异常
        const anomalies = [];

        // 成交量飙升
        if (medianVolume > 0 && totalVol > medianVolume * 5) {
            anomalies.push('volume_spike');
        }

        // 大额交易
        if (medianTradeSize > 0 && currentSize > medianTradeSize * 20) {
            anomalies.push('whale_trade');
        }

        // 买卖失衡 - 提高阈值减少噪音，同时要求最小成交量
        if (totalVol > 100 && Math.abs(netVol) / totalVol > 0.85) {
            anomalies.push('imbalance');
        }

        // 价格异动
        if (avgPrice > 0 && priceRange / avgPrice > 0.1) {
            anomalies.push('price_move');
        }

        // 高频交易
        if (tradeFreq > 10) {
            anomalies.push('high_frequency');
        }

        if (anomalies.length > 0) {
            // 计算智能评分
            const score = calculateAnomalyScore({
                anomalies,
                volumeRatio: medianVolume > 0 ? totalVol / medianVolume : 0,
                tradeSizeRatio: medianTradeSize > 0 ? currentSize / medianTradeSize : 0,
                priceRangePct: avgPrice > 0 ? (priceRange / avgPrice * 100) : 0,
                tradeCount: window.length,
                imbalanceRatio: totalVol > 0 ? Math.abs(netVol) / totalVol : 0,
                marketLiquidity: market.liquidity || 0,
                marketVolume: market.volume24h || 0
            });

            // 计算后续价格变化 (信号验证)
            const priceChange = calculatePriceChange(trades, i, currentTime);

            events.push({
                timestamp: currentTime,
                datetime: new Date(currentTime * 1000).toLocaleString('zh-CN'),
                market: market.question,
                marketType: market.type,
                conditionId: market.conditionId,
                slug: market.slug,
                eventSlug: market.eventSlug,  // 添加 event slug
                anomalies: anomalies,
                walletCount: walletCount,
                totalVolume: totalVol,
                netVolume: netVol,
                volumeRatio: medianVolume > 0 ? totalVol / medianVolume : 0,
                tradeSize: currentSize,
                tradePrice: t.price || 0,
                priceRangePct: avgPrice > 0 ? (priceRange / avgPrice * 100) : 0,
                isBuy: netVol > 0,
                tradeCount: window.length,
                score: score,  // 异常强度评分
                priceChange: priceChange,  // 信号验证: 后续价格变化
                outcome: t.outcome || 'N/A'  // 交易的 outcome (Yes/No)
            });
        }
    }

    // 去重：每5秒只保留一个事件
    const deduped = [];
    let lastTs = 0;
    for (const e of events) {
        if (e.timestamp - lastTs >= 5) {
            deduped.push(e);
            lastTs = e.timestamp;
        }
    }

    return deduped;
}

/**
 * 计算中位数
 */
function median(arr) {
    if (arr.length === 0) return 0;
    const sorted = [...arr].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * 计算异常强度评分 (0-100)
 * 智能评分考虑多个因素
 */
function calculateAnomalyScore(params) {
    let score = 0;

    // 1. 异常类型数量和权重 (最高40分)
    const typeWeights = {
        whale_trade: 15,      // 大额交易权重高
        volume_spike: 12,     // 成交量飙升
        price_move: 10,       // 价格异动
        imbalance: 8,         // 买卖失衡
        high_frequency: 5     // 高频交易
    };

    params.anomalies.forEach(type => {
        score += typeWeights[type] || 5;
    });

    // 多类型叠加奖励
    if (params.anomalies.length >= 3) score += 10;
    else if (params.anomalies.length >= 2) score += 5;

    // 2. 成交量倍数 (最高20分)
    if (params.volumeRatio > 20) score += 20;
    else if (params.volumeRatio > 10) score += 15;
    else if (params.volumeRatio > 5) score += 10;
    else if (params.volumeRatio > 3) score += 5;

    // 3. 单笔交易规模 (最高15分)
    if (params.tradeSizeRatio > 50) score += 15;
    else if (params.tradeSizeRatio > 30) score += 12;
    else if (params.tradeSizeRatio > 20) score += 8;
    else if (params.tradeSizeRatio > 10) score += 5;

    // 4. 价格波动幅度 (最高10分)
    if (params.priceRangePct > 20) score += 10;
    else if (params.priceRangePct > 10) score += 7;
    else if (params.priceRangePct > 5) score += 4;

    // 5. 买卖失衡程度 (最高10分)
    if (params.imbalanceRatio > 0.95) score += 10;
    else if (params.imbalanceRatio > 0.9) score += 7;
    else if (params.imbalanceRatio > 0.85) score += 4;

    // 6. 市场流动性奖励 - 高流动性市场的异常更有意义 (最高5分)
    if (params.marketLiquidity > 10000) score += 5;
    else if (params.marketLiquidity > 5000) score += 3;
    else if (params.marketLiquidity > 1000) score += 1;

    return Math.min(100, Math.round(score));
}

/**
 * 计算信号后的价格变化
 * 用已获取的交易数据,计算异常发生后的价格走势
 */
function calculatePriceChange(trades, eventIndex, eventTime) {
    // 获取事件发生时的价格
    const eventPrice = trades[eventIndex].price || 0;
    if (eventPrice === 0) return null;

    // 查找事件后5分钟内的交易
    const futureWindow = 300; // 5分钟
    const futureTrades = trades.slice(eventIndex + 1).filter(t =>
        t.timestamp <= eventTime + futureWindow
    );

    if (futureTrades.length === 0) return null;

    // 获取最后一笔交易的价格
    const lastPrice = futureTrades[futureTrades.length - 1].price || eventPrice;

    // 计算价格变化百分比
    const change = ((lastPrice - eventPrice) / eventPrice * 100);

    return {
        change: change,
        direction: change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
        futurePrice: lastPrice,
        eventPrice: eventPrice,
        tradeCount: futureTrades.length
    };
}

/**
 * 获取筛选后的事件
 */
function getFilteredEvents() {
    if (timeFilter === 'all') return allEvents;

    const now = Date.now() / 1000;
    const hours = {
        '1h': 1,
        '6h': 6,
        '24h': 24
    };

    const cutoff = now - (hours[timeFilter] || 24) * 3600;
    return allEvents.filter(e => e.timestamp >= cutoff);
}

/**
 * 设置时间筛选
 */
function setTimeFilter(filter) {
    timeFilter = filter;

    // 更新按钮状态
    document.querySelectorAll('.time-filter-btn').forEach(btn => {
        btn.classList.remove('bg-neon-blue', 'text-dark-900');
        btn.classList.add('bg-dark-700');
    });
    document.getElementById(`filter-${filter}`).classList.remove('bg-dark-700');
    document.getElementById(`filter-${filter}`).classList.add('bg-neon-blue', 'text-dark-900');

    // 重新渲染UI
    updateUI();
}

/**
 * 更新所有UI组件
 */
function updateUI() {
    updateStats();
    updateEventFeed();
    updateHotMarkets();
    updateAnomalyTypes();
    updateMarketTypes();
    updateWhaleTrades();
    updateMarketSentiment();
    updateVolumeSpikes();
    updatePriceMoves();
}

/**
 * 更新统计数据
 */
function updateStats() {
    document.getElementById('stat-markets').textContent = markets.length;
    document.getElementById('stat-events').textContent = allEvents.length.toLocaleString();

    // 计算活跃钱包数 - 使用事件中的钱包数总和（去重估算）
    const totalWallets = allEvents.reduce((sum, e) => sum + (e.walletCount || 0), 0);
    // 估算去重后的数量（假设有50%重复）
    const uniqueWallets = Math.floor(totalWallets * 0.5);
    document.getElementById('stat-wallets').textContent = uniqueWallets.toLocaleString();

    // 计算总成交量 - 按市场去重避免重复计算
    const volumeByMarket = {};
    allEvents.forEach(e => {
        if (!volumeByMarket[e.conditionId]) {
            volumeByMarket[e.conditionId] = 0;
        }
        // 只取每个市场的最大成交量
        volumeByMarket[e.conditionId] = Math.max(volumeByMarket[e.conditionId], e.totalVolume || 0);
    });
    const totalVol = Object.values(volumeByMarket).reduce((sum, v) => sum + v, 0);
    document.getElementById('stat-volume').textContent = formatCurrency(totalVol);
}

/**
 * 更新事件流
 */
function updateEventFeed() {
    const container = document.getElementById('event-feed');
    const filteredEvents = getFilteredEvents();
    const recentEvents = filteredEvents.filter(e => e.marketType !== 'sports').slice(0, 50);

    if (recentEvents.length === 0) {
        container.innerHTML = `
            <div class="p-8 text-center text-gray-500">
                ${timeFilter === 'all' ? '暂无异常事件' : `最近${timeFilter}内暂无异常事件`}
            </div>
        `;
        document.getElementById('event-count').textContent = `0 事件`;
        return;
    }

    container.innerHTML = recentEvents.map(event => {
        const tags = event.anomalies.map(type => {
            const config = ANOMALY_CONFIG[type] || { name: type, color: 'gray', icon: '•' };
            return `<span class="tag bg-neon-${config.color}/20 text-neon-${config.color}">${config.icon} ${config.name}</span>`;
        }).join('');

        const direction = event.isBuy ?
            '<span class="text-neon-green">买入主导</span>' :
            '<span class="text-neon-red">卖出主导</span>';

        const marketTypeConfig = MARKET_TYPES[event.marketType] || MARKET_TYPES.general;
        const marketUrl = `https://polymarket.com/event/${event.eventSlug}`;
        const outcome = event.outcome || 'N/A';

        // 评分颜色和等级
        const score = event.score || 0;
        let scoreColor, scoreLevel;
        if (score >= 70) {
            scoreColor = 'neon-red';
            scoreLevel = '强';
        } else if (score >= 40) {
            scoreColor = 'neon-yellow';
            scoreLevel = '中';
        } else {
            scoreColor = 'gray-400';
            scoreLevel = '弱';
        }

        // 信号验证 - 价格变化
        let priceChangeHtml = '';
        if (event.priceChange) {
            const pc = event.priceChange;
            const changeColor = pc.change > 0 ? 'neon-green' : pc.change < 0 ? 'neon-red' : 'gray-400';
            const changeIcon = pc.change > 0 ? '↑' : pc.change < 0 ? '↓' : '→';
            priceChangeHtml = `
                <span class="text-${changeColor}" title="信号后5分钟价格变化: ${pc.eventPrice.toFixed(2)} → ${pc.futurePrice.toFixed(2)}">
                    ${changeIcon}${Math.abs(pc.change).toFixed(1)}%
                </span>
            `;
        }

        return `
            <div class="event-item p-3 border-b border-white/5 ${score >= 70 ? 'bg-neon-red/5' : score >= 40 ? 'bg-neon-yellow/5' : ''} relative">
                <div class="flex items-start justify-between mb-2">
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-${scoreColor} font-bold text-xs px-1.5 py-0.5 rounded bg-${scoreColor}/20"
                                  title="异常强度评分: ${score}/100 (${scoreLevel})">
                                ${score}分
                            </span>
                            <a href="${marketUrl}" target="_blank" rel="noopener"
                               class="text-sm font-medium truncate hover:text-neon-blue transition-colors flex-1" title="${event.market}">
                                ${event.market.slice(0, 45)}${event.market.length > 45 ? '...' : ''}
                                <svg class="w-3 h-3 inline ml-1 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
                                </svg>
                            </a>
                        </div>
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="tag bg-${marketTypeConfig.color}-500/20 text-${marketTypeConfig.color}-400">${marketTypeConfig.name}</span>
                            ${tags}
                        </div>
                    </div>
                    <div class="text-xs text-gray-500 ml-2 whitespace-nowrap">${formatTime(event.timestamp)}</div>
                </div>
                <div class="flex items-center justify-between text-xs text-gray-400">
                    <div class="flex items-center gap-3">
                        <span title="5分钟窗口内的总成交金额">💰 ${formatCurrency(event.totalVolume)}</span>
                        <span title="买入金额vs卖出金额的对比">${direction}</span>
                        <span class="text-neon-blue" title="交易结果">📊 ${outcome}</span>
                        ${priceChangeHtml}
                    </div>
                    <div class="flex items-center gap-2">
                        <span class="text-neon-blue" title="成交量是该市场平均水平的倍数">${event.volumeRatio.toFixed(1)}x均值</span>
                        ${event.anomalies.includes('whale_trade') ? 
                            `<span class="text-neon-purple font-medium" title="检测到大额交易 (>20x均值)">🐋 ${event.isBuy ? '大额买入' : '大额卖出'}</span>` 
                            : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');

    document.getElementById('event-count').textContent = `${filteredEvents.length} 事件`;
}

/**
 * 更新热门市场
 */
function updateHotMarkets() {
    const container = document.getElementById('hot-markets');
    const filteredEvents = getFilteredEvents();

    // 按市场聚合事件数
    const marketEvents = {};
    filteredEvents.forEach(e => {
        if (!marketEvents[e.conditionId]) {
            marketEvents[e.conditionId] = {
                market: e.market,
                type: e.marketType,
                count: 0,
                volume: 0
            };
        }
        marketEvents[e.conditionId].count++;
        marketEvents[e.conditionId].volume += e.totalVolume || 0;
    });

    const sorted = Object.values(marketEvents)
        .sort((a, b) => b.count - a.count)
        .slice(0, 5);

    if (sorted.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无数据</div>';
        return;
    }

    const maxCount = sorted[0].count;

    container.innerHTML = sorted.map((m, i) => {
        const pct = (m.count / maxCount * 100).toFixed(0);
        const typeConfig = MARKET_TYPES[m.type] || MARKET_TYPES.general;

        return `
            <div class="space-y-1">
                <div class="flex items-center justify-between">
                    <span class="text-sm truncate flex-1">${m.market.slice(0, 35)}${m.market.length > 35 ? '...' : ''}</span>
                    <span class="text-xs text-neon-blue ml-2">${m.count}</span>
                </div>
                <div class="h-1.5 bg-dark-600 rounded-full overflow-hidden">
                    <div class="h-full progress-bar rounded-full transition-all duration-500" style="width: ${pct}%"></div>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 更新异常类型分布
 */
function updateAnomalyTypes() {
    const container = document.getElementById('anomaly-types');
    const filteredEvents = getFilteredEvents();

    // 统计各类型数量
    const typeCounts = {};
    filteredEvents.forEach(e => {
        e.anomalies.forEach(type => {
            typeCounts[type] = (typeCounts[type] || 0) + 1;
        });
    });

    const sorted = Object.entries(typeCounts)
        .sort((a, b) => b[1] - a[1]);

    if (sorted.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无数据</div>';
        return;
    }

    const total = sorted.reduce((sum, [, count]) => sum + count, 0);

    container.innerHTML = sorted.map(([type, count]) => {
        const config = ANOMALY_CONFIG[type] || { name: type, color: 'gray', icon: '•' };
        const pct = (count / total * 100).toFixed(0);

        return `
            <div class="flex items-center justify-between">
                <div class="flex items-center space-x-2">
                    <span class="text-neon-${config.color}">${config.icon}</span>
                    <span class="text-sm">${config.name}</span>
                </div>
                <div class="flex items-center space-x-2">
                    <span class="text-xs text-gray-500">${pct}%</span>
                    <span class="text-sm font-medium">${count}</span>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 更新市场类型统计
 */
function updateMarketTypes() {
    const container = document.getElementById('market-types');
    const filteredEvents = getFilteredEvents();

    // 统计各类型
    const typeCounts = {};
    filteredEvents.forEach(e => {
        typeCounts[e.marketType] = (typeCounts[e.marketType] || 0) + 1;
    });

    const sorted = Object.entries(typeCounts)
        .sort((a, b) => b[1] - a[1]);

    if (sorted.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-4">暂无数据</div>';
        return;
    }

    const total = sorted.reduce((sum, [, count]) => sum + count, 0);

    container.innerHTML = sorted.map(([type, count]) => {
        const config = MARKET_TYPES[type] || { name: type, color: 'gray' };
        const pct = (count / total * 100).toFixed(0);

        return `
            <div class="flex items-center justify-between">
                <span class="text-sm">${config.name}</span>
                <div class="flex items-center space-x-2">
                    <div class="w-24 h-1.5 bg-dark-600 rounded-full overflow-hidden">
                        <div class="h-full bg-neon-${config.color} rounded-full" style="width: ${pct}%"></div>
                    </div>
                    <span class="text-sm font-medium w-12 text-right">${count}</span>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 更新大额交易
 */
function updateWhaleTrades() {
    const container = document.getElementById('whale-trades');
    const filteredEvents = getFilteredEvents();

    const whales = filteredEvents
        .filter(e => e.anomalies.includes('whale_trade') && e.marketType !== 'sports')
        .sort((a, b) => b.tradeSize - a.tradeSize) // 先按金额挑出最大
        .slice(0, 20)
        .sort((a, b) => b.timestamp - a.timestamp); // 对挑出的20条按时间排序

    if (whales.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-2 text-xs">暂无大额交易</div>';
        return;
    }

    container.innerHTML = whales.map(e => {
        // 判断买入还是卖出方向
        const isBuy = e.isBuy || e.netVolume > 0;
        const directionIcon = isBuy ? '📈' : '📉';
        const directionText = isBuy ? '买入' : '卖出';
        const directionColor = isBuy ? 'neon-green' : 'neon-red';
        const tradeSizeRatio = e.volumeRatio || 0;
        const outcome = e.outcome || 'N/A';
        const tradePrice = e.tradePrice || 0;
        
        return `
        <div class="text-xs p-2 bg-dark-600/50 rounded hover:bg-dark-600 transition-colors whale-trade-item">
            <a href="https://polymarket.com/event/${e.eventSlug}" target="_blank" rel="noopener"
               class="font-medium block hover:text-neon-blue break-words" title="${e.market}">${e.market}</a>
            <div class="flex items-center justify-between mt-1">
                <span class="text-gray-400">${formatTime(e.timestamp)}</span>
                <span class="text-${directionColor} font-medium" title="交易方向">
                    ${directionIcon} ${directionText}
                </span>
            </div>
            <div class="flex items-center justify-between mt-1">
                <div class="flex items-center gap-3">
                    <span class="text-neon-blue font-medium" title="单笔交易金额">${formatCurrency(e.tradeSize)}</span>
                    <span class="text-neon-green font-medium" title="成交价格">$${tradePrice.toFixed(3)}</span>
                    <span class="text-neon-blue text-xs" title="交易结果">📊 ${outcome}</span>
                </div>
                <span class="text-gray-400 text-xs" title="相对平均交易规模">×${tradeSizeRatio.toFixed(1)}</span>
            </div>
        </div>
        `;
    }).join('');
}

/**
 * 更新市场情绪
 */
function updateMarketSentiment() {
    const container = document.getElementById('market-sentiment');
    const filteredEvents = getFilteredEvents();

    if (filteredEvents.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-2 text-xs">暂无数据</div>';
        return;
    }

    // 计算整体买卖情绪
    let totalBuy = 0;
    let totalSell = 0;
    let buyCount = 0;
    let sellCount = 0;

    filteredEvents.forEach(e => {
        if (e.netVolume > 0) {
            totalBuy += e.netVolume;
            buyCount++;
        } else {
            totalSell += Math.abs(e.netVolume);
            sellCount++;
        }
    });

    const total = totalBuy + totalSell;
    const buyPct = total > 0 ? (totalBuy / total * 100) : 50;
    const sellPct = 100 - buyPct;

    // 情绪判断
    let sentiment, sentimentColor, sentimentIcon;
    if (buyPct > 65) {
        sentiment = '强烈看涨';
        sentimentColor = 'neon-green';
        sentimentIcon = '🚀';
    } else if (buyPct > 55) {
        sentiment = '偏向看涨';
        sentimentColor = 'green-400';
        sentimentIcon = '📈';
    } else if (buyPct < 35) {
        sentiment = '强烈看跌';
        sentimentColor = 'neon-red';
        sentimentIcon = '📉';
    } else if (buyPct < 45) {
        sentiment = '偏向看跌';
        sentimentColor = 'red-400';
        sentimentIcon = '⬇️';
    } else {
        sentiment = '中性';
        sentimentColor = 'gray-400';
        sentimentIcon = '➡️';
    }

    container.innerHTML = `
        <div class="space-y-3">
            <div class="text-center">
                <span class="text-2xl">${sentimentIcon}</span>
                <div class="text-lg font-bold text-${sentimentColor}">${sentiment}</div>
            </div>
            <div class="space-y-2">
                <div class="flex justify-between text-xs">
                    <span class="text-neon-green">买入 ${buyPct.toFixed(1)}%</span>
                    <span class="text-neon-red">卖出 ${sellPct.toFixed(1)}%</span>
                </div>
                <div class="h-2 bg-dark-600 rounded-full overflow-hidden flex">
                    <div class="h-full bg-neon-green" style="width: ${buyPct}%"></div>
                    <div class="h-full bg-neon-red" style="width: ${sellPct}%"></div>
                </div>
                <div class="flex justify-between text-xs text-gray-500">
                    <span title="买入主导的事件数">${buyCount} 事件</span>
                    <span title="卖出主导的事件数">${sellCount} 事件</span>
                </div>
            </div>
            <div class="pt-2 border-t border-white/10 text-xs text-gray-500">
                <div class="flex justify-between">
                    <span>买入量</span>
                    <span class="text-neon-green">${formatCurrency(totalBuy)}</span>
                </div>
                <div class="flex justify-between mt-1">
                    <span>卖出量</span>
                    <span class="text-neon-red">${formatCurrency(totalSell)}</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * 更新成交量飙升
 */
function updateVolumeSpikes() {
    const container = document.getElementById('volume-spikes');
    const filteredEvents = getFilteredEvents();

    const spikes = filteredEvents
        .filter(e => e.anomalies.includes('volume_spike'))
        .sort((a, b) => b.volumeRatio - a.volumeRatio)
        .slice(0, 8);

    if (spikes.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-2 text-xs">暂无成交量飙升</div>';
        return;
    }

    container.innerHTML = spikes.map(e => `
        <div class="text-xs p-2 bg-dark-600/50 rounded flex items-center justify-between">
            <a href="https://polymarket.com/event/${e.eventSlug}" target="_blank" rel="noopener"
               class="truncate flex-1 hover:text-neon-blue" title="${e.market}">${e.market.slice(0, 25)}...</a>
            <div class="flex items-center gap-2 ml-2">
                <span class="text-gray-500" title="5分钟成交量">${formatCurrency(e.totalVolume)}</span>
                <span class="text-neon-green font-medium" title="相对平均值的倍数">${e.volumeRatio.toFixed(1)}x</span>
            </div>
        </div>
    `).join('');
}

/**
 * 更新价格异动
 */
function updatePriceMoves() {
    const container = document.getElementById('price-moves');
    const filteredEvents = getFilteredEvents();

    const moves = filteredEvents
        .filter(e => e.anomalies.includes('price_move'))
        .sort((a, b) => b.priceRangePct - a.priceRangePct)
        .slice(0, 8);

    if (moves.length === 0) {
        container.innerHTML = '<div class="text-center text-gray-500 py-2 text-xs">暂无价格异动</div>';
        return;
    }

    container.innerHTML = moves.map(e => `
        <div class="text-xs p-2 bg-dark-600/50 rounded flex items-center justify-between">
            <a href="https://polymarket.com/event/${e.eventSlug}" target="_blank" rel="noopener"
               class="truncate flex-1 hover:text-neon-blue" title="${e.market}">${e.market.slice(0, 25)}...</a>
            <div class="flex items-center gap-2 ml-2">
                <span class="text-gray-500">${formatTime(e.timestamp)}</span>
                <span class="text-neon-pink font-medium" title="5分钟内价格波动幅度">${e.priceRangePct.toFixed(1)}%</span>
            </div>
        </div>
    `).join('');
}

/**
 * 格式化货币
 */
function formatCurrency(value) {
    if (value >= 1000000) {
        return `$${(value / 1000000).toFixed(1)}M`;
    } else if (value >= 1000) {
        return `$${(value / 1000).toFixed(1)}K`;
    } else {
        return `$${value.toFixed(0)}`;
    }
}

/**
 * 格式化时间
 */
function formatTime(timestamp) {
    const now = Date.now() / 1000;
    const diff = now - timestamp;

    if (diff < 60) {
        return '刚刚';
    } else if (diff < 3600) {
        return `${Math.floor(diff / 60)}分钟前`;
    } else if (diff < 86400) {
        return `${Math.floor(diff / 3600)}小时前`;
    } else {
        return `${Math.floor(diff / 86400)}天前`;
    }
}

/**
 * 请求通知权限
 */
function requestNotification() {
    if (!('Notification' in window)) {
        alert('此浏览器不支持通知');
        return;
    }

    Notification.requestPermission().then(permission => {
        if (permission === 'granted') {
            new Notification('PolySurge', {
                body: '通知已启用！检测到新异常时会提醒您',
            });
            document.getElementById('notify-btn').textContent = '✅ 已启用';
        }
    });
}

// 启动应用
document.addEventListener('DOMContentLoaded', init);
