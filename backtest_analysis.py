#!/usr/bin/env python3
"""
Polymarket 异常资金涌入回测分析脚本

分析目标：
1. 验证 API 数据完整性
2. 统计异常涌入事件的发生频率
3. 分析事件与价格变动的相关性（信号有效性）
4. 验证产品价值

排除：sports 市场和超短期（15m/日内）市场
"""

import requests
import time
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any
import statistics

# 配置
API_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

# 异常检测阈值 - 降低阈值以检测更多事件
WINDOW_MINUTES = 5  # 滑动窗口大小
NEW_WALLET_THRESHOLD = 3  # 新钱包数量阈值（降低）
NEW_WALLET_RATIO_THRESHOLD = 0.3  # 新钱包占比阈值（降低到30%）
VOLUME_SPIKE_MULTIPLIER = 2  # 成交量是平均值的倍数


class PolymarketBacktester:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'PolymarketAnalyzer/1.0'
        })

    def get_active_markets(self, limit=100) -> List[Dict]:
        """获取活跃市场，排除 sports 和短期市场"""
        print("\n=== 获取活跃市场列表 ===")

        # 从 Gamma API 获取市场
        markets = []
        try:
            # 获取高流动性的活跃市场
            resp = self.session.get(
                f"{GAMMA_BASE}/markets",
                params={
                    "limit": 200,
                    "active": "true",
                    "closed": "false",
                    "order": "volume24hr",
                    "ascending": "false"
                },
                timeout=30
            )
            resp.raise_for_status()
            all_markets = resp.json()

            # 过滤条件
            sports_keywords = ['nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football', 'basketball',
                             'baseball', 'hockey', 'tennis', 'cricket', 'rugby', 'match',
                             'game', 'vs.', 'vs ', 'euro', 'copa', 'league', 'championship',
                             'tournament', 'win on', 'beat']
            short_term_keywords = ['15m', '30m', '1h', 'hour', 'minute', 'daily', 'today']

            for market in all_markets:
                question = market.get('question', '').lower()
                slug = market.get('slug', '').lower()
                condition_id = market.get('conditionId', '')

                # 跳过没有 conditionId 的市场
                if not condition_id:
                    continue

                # 检查是否是体育市场
                is_sports = any(kw in question or kw in slug for kw in sports_keywords)

                # 检查是否是短期市场
                is_short_term = any(kw in question or kw in slug for kw in short_term_keywords)

                # 检查是否有 sports 标签
                events = market.get('events', [])
                for event in events:
                    if 'sport' in str(event.get('tags', [])).lower():
                        is_sports = True
                        break

                if not is_sports and not is_short_term:
                    markets.append({
                        'condition_id': condition_id,
                        'question': market.get('question', ''),
                        'slug': market.get('slug', ''),
                        'volume_24h': market.get('volume24hrClob', 0) or market.get('volume24hr', 0),
                        'end_date': market.get('endDate', '')
                    })

                if len(markets) >= limit:
                    break

            print(f"找到 {len(markets)} 个符合条件的市场（非体育、非短期）")

            # 按成交量排序，取前 N 个
            markets.sort(key=lambda x: x.get('volume_24h', 0), reverse=True)
            markets = markets[:limit]

            if markets:
                print(f"\nTop 5 市场:")
                for i, m in enumerate(markets[:5]):
                    print(f"  {i+1}. {m['question'][:60]}... (24h vol: ${m['volume_24h']:.0f})")

        except Exception as e:
            print(f"获取市场列表失败: {e}")

        return markets

    def get_market_trades(self, condition_id: str, limit=2000) -> List[Dict]:
        """获取市场的成交记录 - 增加到2000条"""
        try:
            resp = self.session.get(
                f"{API_BASE}/trades",
                params={
                    "market": condition_id,
                    "limit": limit
                },
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"获取成交记录失败 ({condition_id[:20]}...): {e}")
            return []

    def get_price_history(self, condition_id: str) -> List[Dict]:
        """获取价格历史"""
        try:
            resp = self.session.get(
                f"{API_BASE}/prices-history",
                params={
                    "market": condition_id,
                    "interval": "1h",  # 1小时间隔
                    "fidelity": 60  # 60分钟
                },
                timeout=30
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            # 价格历史可能不可用
            return []

    def analyze_wallet_surge(self, trades: List[Dict], window_minutes: int = 5) -> List[Dict]:
        """
        分析钱包涌入事件

        返回所有检测到的异常事件列表
        """
        if not trades:
            return []

        # 按时间排序（从旧到新）
        trades_sorted = sorted(trades, key=lambda x: x.get('timestamp', 0))

        # 记录每个市场历史上见过的钱包
        seen_wallets = set()

        # 存储检测到的事件
        events = []

        # 计算窗口大小（秒）
        window_seconds = window_minutes * 60

        # 使用滑动窗口分析
        for i, trade in enumerate(trades_sorted):
            current_time = trade.get('timestamp', 0)

            # 找出窗口内的所有交易
            window_trades = []
            for j in range(i, -1, -1):
                t = trades_sorted[j]
                if current_time - t.get('timestamp', 0) <= window_seconds:
                    window_trades.append(t)
                else:
                    break

            if len(window_trades) < 3:  # 至少需要3笔交易
                seen_wallets.add(trade.get('proxyWallet', ''))
                continue

            # 统计窗口内的指标
            wallets_in_window = set(t.get('proxyWallet', '') for t in window_trades)
            new_wallets = wallets_in_window - seen_wallets

            unique_count = len(wallets_in_window)
            new_count = len(new_wallets)
            new_ratio = new_count / unique_count if unique_count > 0 else 0

            # 计算成交量
            buy_volume = sum(t.get('size', 0) * t.get('price', 0)
                           for t in window_trades if t.get('side') == 'BUY')
            sell_volume = sum(t.get('size', 0) * t.get('price', 0)
                            for t in window_trades if t.get('side') == 'SELL')
            net_volume = buy_volume - sell_volume
            total_volume = buy_volume + sell_volume

            # 检查是否触发异常
            is_anomaly = (
                new_count >= NEW_WALLET_THRESHOLD and
                new_ratio >= NEW_WALLET_RATIO_THRESHOLD
            )

            if is_anomaly:
                # 计算平均价格
                prices = [t.get('price', 0) for t in window_trades]
                avg_price = statistics.mean(prices) if prices else 0

                events.append({
                    'timestamp': current_time,
                    'datetime': datetime.fromtimestamp(current_time).isoformat(),
                    'unique_wallets': unique_count,
                    'new_wallets': new_count,
                    'new_ratio': new_ratio,
                    'buy_volume': buy_volume,
                    'sell_volume': sell_volume,
                    'net_volume': net_volume,
                    'total_volume': total_volume,
                    'avg_price': avg_price,
                    'trade_count': len(window_trades),
                    'is_buy_surge': net_volume > 0
                })

            # 更新已见钱包
            seen_wallets.add(trade.get('proxyWallet', ''))

        return events

    def analyze_price_after_event(self, event: Dict, trades: List[Dict],
                                   forward_minutes: int = 30) -> Dict:
        """
        分析事件后的价格变动

        检查事件后 forward_minutes 内的价格变化
        """
        event_time = event['timestamp']
        forward_seconds = forward_minutes * 60

        # 找出事件后的交易
        future_trades = [
            t for t in trades
            if event_time < t.get('timestamp', 0) <= event_time + forward_seconds
        ]

        if not future_trades:
            return {
                'price_change': None,
                'price_change_pct': None,
                'signal_correct': None
            }

        # 计算价格变化
        event_price = event['avg_price']
        future_prices = [t.get('price', 0) for t in future_trades]
        final_price = statistics.mean(future_prices[-5:]) if len(future_prices) >= 5 else future_prices[-1]

        price_change = final_price - event_price
        price_change_pct = (price_change / event_price * 100) if event_price > 0 else 0

        # 判断信号是否正确
        # 如果是买入涌入（net_volume > 0），价格应该上涨
        # 如果是卖出涌入（net_volume < 0），价格应该下跌
        if event['is_buy_surge']:
            signal_correct = price_change > 0
        else:
            signal_correct = price_change < 0

        return {
            'price_change': price_change,
            'price_change_pct': price_change_pct,
            'signal_correct': signal_correct,
            'future_trade_count': len(future_trades)
        }

    def run_backtest(self, num_markets: int = 30):
        """运行完整的回测分析"""
        print("=" * 60)
        print("Polymarket 异常资金涌入回测分析")
        print("=" * 60)
        print(f"\n分析参数:")
        print(f"  - 滑动窗口: {WINDOW_MINUTES} 分钟")
        print(f"  - 新钱包数量阈值: >= {NEW_WALLET_THRESHOLD}")
        print(f"  - 新钱包占比阈值: >= {NEW_WALLET_RATIO_THRESHOLD * 100}%")
        print(f"  - 排除: sports 市场、超短期（15m/日内）市场")

        # 获取市场列表
        markets = self.get_active_markets(limit=num_markets)

        if not markets:
            print("\n错误: 未获取到任何市场")
            return

        # 统计结果
        total_events = 0
        total_trades = 0
        markets_with_events = 0
        all_events = []
        signal_results = []

        print(f"\n=== 分析 {len(markets)} 个市场的成交数据 ===\n")

        for i, market in enumerate(markets):
            condition_id = market['condition_id']
            question = market['question'][:50]

            print(f"[{i+1}/{len(markets)}] 分析: {question}...")

            # 获取成交记录
            trades = self.get_market_trades(condition_id, limit=2000)

            if not trades:
                print(f"  - 无成交数据")
                continue

            total_trades += len(trades)

            # 分析钱包涌入事件
            events = self.analyze_wallet_surge(trades, WINDOW_MINUTES)

            if events:
                markets_with_events += 1
                total_events += len(events)

                print(f"  - 成交笔数: {len(trades)}, 检测到 {len(events)} 个异常事件")

                # 分析每个事件的后续价格变动
                for event in events:
                    event['market'] = question
                    event['condition_id'] = condition_id

                    price_result = self.analyze_price_after_event(event, trades, 30)
                    event.update(price_result)
                    all_events.append(event)

                    if price_result['signal_correct'] is not None:
                        signal_results.append(price_result['signal_correct'])
            else:
                print(f"  - 成交笔数: {len(trades)}, 无异常事件")

            # 避免请求过快
            time.sleep(0.3)

        # 输出分析结果
        self.print_results(markets, total_trades, total_events,
                          markets_with_events, all_events, signal_results)

        return all_events

    def print_results(self, markets, total_trades, total_events,
                      markets_with_events, all_events, signal_results):
        """打印分析结果"""
        print("\n" + "=" * 60)
        print("回测分析结果")
        print("=" * 60)

        # 基本统计
        print("\n📊 基本统计:")
        print(f"  - 分析市场数: {len(markets)}")
        print(f"  - 总成交笔数: {total_trades:,}")
        print(f"  - 检测到异常事件数: {total_events}")
        print(f"  - 有异常事件的市场数: {markets_with_events}")

        if len(markets) > 0:
            event_rate = total_events / len(markets)
            market_rate = markets_with_events / len(markets) * 100
            print(f"  - 平均每市场事件数: {event_rate:.2f}")
            print(f"  - 有事件的市场占比: {market_rate:.1f}%")

        if total_trades > 0:
            event_per_1000_trades = total_events / total_trades * 1000
            print(f"  - 每1000笔交易的事件数: {event_per_1000_trades:.2f}")

        # 事件频率分析
        print("\n⏱️ 事件频率分析:")
        if total_events == 0:
            print("  - 未检测到任何异常事件")
            print("  - 可能原因: 阈值设置过高，或数据量不足")
        else:
            # 计算事件间隔
            if len(all_events) > 1:
                timestamps = sorted([e['timestamp'] for e in all_events])
                intervals = [(timestamps[i+1] - timestamps[i]) / 3600
                            for i in range(len(timestamps)-1)]
                avg_interval = statistics.mean(intervals) if intervals else 0
                print(f"  - 平均事件间隔: {avg_interval:.1f} 小时")

            # 事件特征统计
            if all_events:
                new_wallet_counts = [e['new_wallets'] for e in all_events]
                volumes = [e['total_volume'] for e in all_events]

                print(f"  - 平均新钱包数: {statistics.mean(new_wallet_counts):.1f}")
                print(f"  - 最大新钱包数: {max(new_wallet_counts)}")
                print(f"  - 平均事件成交量: ${statistics.mean(volumes):.0f}")

        # 信号有效性分析
        print("\n🎯 信号有效性分析:")
        if not signal_results:
            print("  - 无法计算信号准确率（无有效数据）")
        else:
            correct_count = sum(signal_results)
            accuracy = correct_count / len(signal_results) * 100
            print(f"  - 可分析事件数: {len(signal_results)}")
            print(f"  - 信号正确次数: {correct_count}")
            print(f"  - 信号准确率: {accuracy:.1f}%")

            if accuracy > 55:
                print("  - 结论: 信号有一定预测价值 ✅")
            elif accuracy > 45:
                print("  - 结论: 信号接近随机，预测价值不明显 ⚠️")
            else:
                print("  - 结论: 信号可能是反向指标 ⚠️")

        # 价格变动分析
        print("\n💰 价格变动分析:")
        price_changes = [e['price_change_pct'] for e in all_events
                        if e.get('price_change_pct') is not None]
        if price_changes:
            print(f"  - 事件后30分钟平均价格变动: {statistics.mean(price_changes):.2f}%")
            print(f"  - 最大上涨: {max(price_changes):.2f}%")
            print(f"  - 最大下跌: {min(price_changes):.2f}%")

        # 产品价值评估
        print("\n" + "=" * 60)
        print("📋 产品价值评估")
        print("=" * 60)

        print("\n1️⃣ 事件频率评估:")
        if total_events == 0:
            print("   ❌ 未检测到事件，需要调整阈值或扩大监控范围")
            frequency_score = 0
        elif event_per_1000_trades < 1:
            print("   ⚠️ 事件非常稀少，可能缺乏持续吸引力")
            frequency_score = 1
        elif event_per_1000_trades < 5:
            print("   ✅ 事件频率适中，有监控价值")
            frequency_score = 2
        else:
            print("   ✅ 事件频率较高，产品活跃度有保障")
            frequency_score = 3

        print("\n2️⃣ 信号有效性评估:")
        if not signal_results:
            print("   ⚠️ 数据不足，无法评估信号质量")
            signal_score = 0
        elif accuracy >= 55:
            print("   ✅ 信号有预测价值，用户可据此做决策参考")
            signal_score = 2
        elif accuracy >= 45:
            print("   ⚠️ 信号接近随机，仅作为信息参考")
            signal_score = 1
        else:
            print("   ❌ 信号可能误导用户")
            signal_score = 0

        print("\n3️⃣ 综合建议:")
        total_score = frequency_score + signal_score
        if total_score >= 4:
            print("   ✅ 产品有较好的价值基础，值得开发")
        elif total_score >= 2:
            print("   ⚠️ 产品有一定价值，但需调整定位")
            print("   建议: 定位为'异动雷达'而非'预测工具'")
        else:
            print("   ❌ 产品价值存疑，建议重新评估或调整策略")

        # 打印一些具体事件示例
        if all_events:
            print("\n📝 异常事件示例（最近5个）:")
            recent_events = sorted(all_events, key=lambda x: x['timestamp'], reverse=True)[:5]
            for i, event in enumerate(recent_events):
                print(f"\n  事件 {i+1}:")
                print(f"    市场: {event['market']}")
                print(f"    时间: {event['datetime']}")
                print(f"    新钱包: {event['new_wallets']} ({event['new_ratio']*100:.0f}%)")
                print(f"    净买入: ${event['net_volume']:.0f}")
                if event.get('price_change_pct') is not None:
                    direction = "↑" if event['price_change_pct'] > 0 else "↓"
                    correct = "✅" if event.get('signal_correct') else "❌"
                    print(f"    30分钟后: {direction}{abs(event['price_change_pct']):.2f}% {correct}")


def main():
    """主函数"""
    print("\n" + "🔍" * 20)
    print("  Polymarket 异常资金涌入回测工具")
    print("🔍" * 20 + "\n")

    backtester = PolymarketBacktester()

    # 运行回测（分析 30 个市场）
    events = backtester.run_backtest(num_markets=30)

    print("\n" + "=" * 60)
    print("回测完成")
    print("=" * 60)

    # 保存事件数据
    if events:
        output_file = "/Users/huan/Desktop/prediction market/PolySurge/backtest_events.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        print(f"\n事件数据已保存到: {output_file}")


if __name__ == "__main__":
    main()
