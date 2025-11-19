#!/usr/bin/env python3
"""
Polymarket 全面异常检测回测 v3

改进：
1. 不只看新钱包，任何钱包涌入都算
2. 多种异常类型：涌入、大额、失衡、价格异动
3. 覆盖所有市场（包括 sports 和短期）
"""

import requests
import time
import json
from datetime import datetime
from collections import defaultdict
from typing import Dict, List
import statistics

API_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


class FullBacktester:
    def __init__(self):
        self.session = requests.Session()

    def get_all_markets(self, limit=100):
        """获取所有活跃市场，不过滤"""
        print("=== 获取所有活跃市场 ===")

        resp = self.session.get(
            f"{GAMMA_BASE}/markets",
            params={
                "limit": 300,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false"
            },
            timeout=30
        )
        all_markets = resp.json()

        markets = []
        for m in all_markets:
            cid = m.get('conditionId', '')
            if not cid:
                continue

            question = m.get('question', '')
            slug = m.get('slug', '').lower()

            # 判断市场类型
            market_type = 'general'
            if any(k in slug for k in ['15m', '30m', '1h', 'hour', 'minute']):
                market_type = 'short_term'
            elif any(k in slug for k in ['nba', 'nfl', 'mlb', 'nhl', 'soccer', 'match', 'game', 'vs', 'win-on']):
                market_type = 'sports'

            markets.append({
                'condition_id': cid,
                'question': question,
                'slug': slug,
                'type': market_type,
                'volume_24h': m.get('volume24hrClob', 0) or m.get('volume24hr', 0) or 0
            })

            if len(markets) >= limit:
                break

        # 统计市场类型
        types = defaultdict(int)
        for m in markets:
            types[m['type']] += 1

        print(f"共 {len(markets)} 个市场:")
        for t, c in types.items():
            print(f"  - {t}: {c}")

        return markets

    def get_trades(self, condition_id, limit=1000):
        """获取交易数据"""
        try:
            resp = self.session.get(
                f"{API_BASE}/trades",
                params={"market": condition_id, "limit": limit},
                timeout=30
            )
            return resp.json()
        except:
            return []

    def detect_all_anomalies(self, trades, window_min=5):
        """
        多维度异常检测：
        1. wallet_surge: 多钱包同时涌入（不管新旧）
        2. volume_spike: 成交量飙升
        3. whale_trade: 单笔大额交易
        4. imbalance: 买卖严重失衡
        5. price_move: 价格快速变动
        """
        if len(trades) < 10:
            return []

        trades = sorted(trades, key=lambda x: x.get('timestamp', 0))
        window_sec = window_min * 60
        events = []

        # 预计算基准值
        all_window_stats = []
        for i, t in enumerate(trades):
            current_time = t['timestamp']
            window = [x for x in trades[:i+1]
                     if current_time - window_sec <= x['timestamp'] <= current_time]
            if len(window) >= 3:
                wallets = len(set(x.get('proxyWallet', '') for x in window))
                volume = sum(x.get('size', 0) * x.get('price', 0) for x in window)
                all_window_stats.append({'wallets': wallets, 'volume': volume})

        if not all_window_stats:
            return []

        median_wallets = statistics.median([s['wallets'] for s in all_window_stats])
        median_volume = statistics.median([s['volume'] for s in all_window_stats])

        # 检测单笔大额的基准
        all_trade_sizes = [t.get('size', 0) * t.get('price', 0) for t in trades]
        median_trade_size = statistics.median(all_trade_sizes) if all_trade_sizes else 0

        for i, t in enumerate(trades):
            current_time = t['timestamp']

            # 当前窗口
            window = [x for x in trades[:i+1]
                     if current_time - window_sec <= x['timestamp'] <= current_time]

            if len(window) < 3:
                continue

            # 计算各种指标
            wallets = set(x.get('proxyWallet', '') for x in window)
            wallet_count = len(wallets)

            buy_vol = sum(x.get('size', 0) * x.get('price', 0)
                         for x in window if x.get('side') == 'BUY')
            sell_vol = sum(x.get('size', 0) * x.get('price', 0)
                          for x in window if x.get('side') == 'SELL')
            total_vol = buy_vol + sell_vol
            net_vol = buy_vol - sell_vol

            # 价格变化
            prices = [x.get('price', 0) for x in window]
            price_range = max(prices) - min(prices) if prices else 0
            avg_price = statistics.mean(prices) if prices else 0

            # 当前交易大小
            current_size = t.get('size', 0) * t.get('price', 0)

            # 异常检测
            anomalies = []

            # 1. 钱包涌入：多个钱包同时交易
            if wallet_count >= max(5, median_wallets * 2):
                anomalies.append('wallet_surge')

            # 2. 成交量飙升
            if median_volume > 0 and total_vol > median_volume * 5:
                anomalies.append('volume_spike')

            # 3. 单笔大额（前5%）
            if median_trade_size > 0 and current_size > median_trade_size * 20:
                anomalies.append('whale_trade')

            # 4. 买卖失衡
            if total_vol > 0:
                imbalance = abs(net_vol) / total_vol
                if imbalance > 0.8:  # 80% 以上单边
                    anomalies.append('imbalance')

            # 5. 价格快速变动
            if avg_price > 0 and price_range / avg_price > 0.1:  # 10% 价格波动
                anomalies.append('price_move')

            if anomalies:
                events.append({
                    'timestamp': current_time,
                    'datetime': datetime.fromtimestamp(current_time).isoformat(),
                    'anomaly_types': anomalies,
                    'wallet_count': wallet_count,
                    'total_volume': total_vol,
                    'net_volume': net_vol,
                    'volume_ratio': total_vol / median_volume if median_volume > 0 else 0,
                    'trade_size': current_size,
                    'price_range_pct': (price_range / avg_price * 100) if avg_price > 0 else 0,
                    'is_buy': net_vol > 0,
                    'trade_count': len(window)
                })

        # 去重：同一秒内多个事件只保留一个（合并异常类型）
        deduped = {}
        for e in events:
            ts = e['timestamp']
            if ts not in deduped:
                deduped[ts] = e
            else:
                deduped[ts]['anomaly_types'] = list(set(
                    deduped[ts]['anomaly_types'] + e['anomaly_types']
                ))

        return list(deduped.values())

    def check_price_after(self, event, trades, forward_min=30):
        """检查事件后的价格变化"""
        event_time = event['timestamp']
        forward_sec = forward_min * 60

        # 事件时的价格
        at_event = [t for t in trades if t['timestamp'] <= event_time]
        if not at_event:
            return None
        event_prices = [t.get('price', 0) for t in at_event[-5:]]
        event_price = statistics.mean(event_prices) if event_prices else 0

        if event_price == 0:
            return None

        # 事件后的交易
        after = [t for t in trades
                if event_time < t['timestamp'] <= event_time + forward_sec]
        if len(after) < 2:
            return None

        after_prices = [t.get('price', 0) for t in after]
        final_price = statistics.mean(after_prices[-3:]) if len(after_prices) >= 3 else after_prices[-1]

        change = final_price - event_price
        change_pct = (change / event_price * 100)

        # 信号正确性
        correct = (event['is_buy'] and change > 0.001) or (not event['is_buy'] and change < -0.001)

        return {
            'price_change': change,
            'price_change_pct': change_pct,
            'signal_correct': correct,
            'event_price': event_price,
            'final_price': final_price
        }

    def run(self):
        """运行回测"""
        print("=" * 60)
        print("Polymarket 全面异常检测回测")
        print("=" * 60)
        print("\n检测类型:")
        print("  - wallet_surge: 多钱包同时涌入")
        print("  - volume_spike: 成交量飙升 (>5x)")
        print("  - whale_trade: 单笔大额 (>20x)")
        print("  - imbalance: 买卖失衡 (>80%)")
        print("  - price_move: 价格快速变动 (>10%)")

        markets = self.get_all_markets(limit=50)

        # 按类型分组统计
        stats_by_type = defaultdict(lambda: {
            'markets': 0, 'trades': 0, 'events': 0,
            'signals': [], 'anomaly_counts': defaultdict(int)
        })

        all_events = []

        print(f"\n=== 分析 {len(markets)} 个市场 ===\n")

        for i, m in enumerate(markets):
            cid = m['condition_id']
            q = m['question'][:40]
            mtype = m['type']

            print(f"[{i+1}/{len(markets)}] [{mtype}] {q}...", end=" ")

            trades = self.get_trades(cid, limit=1000)
            if not trades:
                print("无数据")
                continue

            stats_by_type[mtype]['markets'] += 1
            stats_by_type[mtype]['trades'] += len(trades)

            events = self.detect_all_anomalies(trades)

            if events:
                stats_by_type[mtype]['events'] += len(events)

                # 统计异常类型
                for e in events:
                    for atype in e['anomaly_types']:
                        stats_by_type[mtype]['anomaly_counts'][atype] += 1

                print(f"{len(trades)}笔, {len(events)}异常")

                for e in events:
                    e['market'] = q
                    e['market_type'] = mtype
                    e['condition_id'] = cid

                    result = self.check_price_after(e, trades)
                    if result:
                        e.update(result)
                        stats_by_type[mtype]['signals'].append(result['signal_correct'])

                    all_events.append(e)
            else:
                print(f"{len(trades)}笔, 无异常")

            time.sleep(0.2)

        # 输出结果
        self.print_results(stats_by_type, all_events)

        return all_events

    def print_results(self, stats_by_type, all_events):
        """打印详细结果"""
        print("\n" + "=" * 60)
        print("回测结果")
        print("=" * 60)

        # 总体统计
        total_markets = sum(s['markets'] for s in stats_by_type.values())
        total_trades = sum(s['trades'] for s in stats_by_type.values())
        total_events = sum(s['events'] for s in stats_by_type.values())
        all_signals = []
        for s in stats_by_type.values():
            all_signals.extend(s['signals'])

        print(f"\n总体统计:")
        print(f"  市场数: {total_markets}")
        print(f"  交易数: {total_trades:,}")
        print(f"  异常事件: {total_events}")
        if total_markets > 0:
            print(f"  每市场平均事件: {total_events/total_markets:.1f}")

        # 按市场类型统计
        print("\n按市场类型:")
        for mtype in ['short_term', 'sports', 'general']:
            s = stats_by_type.get(mtype)
            if not s or s['markets'] == 0:
                continue

            events_per_market = s['events'] / s['markets']
            accuracy = sum(s['signals']) / len(s['signals']) * 100 if s['signals'] else 0

            print(f"\n  [{mtype}]")
            print(f"    市场: {s['markets']}, 事件: {s['events']}")
            print(f"    每市场事件: {events_per_market:.1f}")
            print(f"    信号准确率: {accuracy:.1f}% ({len(s['signals'])}样本)")

            # 异常类型分布
            if s['anomaly_counts']:
                top_types = sorted(s['anomaly_counts'].items(), key=lambda x: -x[1])[:3]
                types_str = ", ".join([f"{t}:{c}" for t, c in top_types])
                print(f"    主要类型: {types_str}")

        # 异常类型总体分布
        print("\n异常类型分布:")
        type_totals = defaultdict(int)
        for s in stats_by_type.values():
            for t, c in s['anomaly_counts'].items():
                type_totals[t] += c

        for atype, count in sorted(type_totals.items(), key=lambda x: -x[1]):
            pct = count / total_events * 100 if total_events > 0 else 0
            print(f"  {atype}: {count} ({pct:.0f}%)")

        # 信号有效性
        print("\n信号有效性分析:")
        if all_signals:
            overall_accuracy = sum(all_signals) / len(all_signals) * 100
            print(f"  总样本: {len(all_signals)}")
            print(f"  准确率: {overall_accuracy:.1f}%")

            if overall_accuracy >= 55:
                print(f"  评估: 有预测价值")
            elif overall_accuracy >= 52:
                print(f"  评估: 略有价值，但不显著")
            else:
                print(f"  评估: 接近随机")
        else:
            print("  数据不足")

        # 价格影响
        changes = [e.get('price_change_pct', 0) for e in all_events
                  if e.get('price_change_pct') is not None]
        if changes:
            # 过滤极端值
            filtered = [c for c in changes if -50 < c < 50]
            if filtered:
                print(f"\n价格影响 (过滤极端值后):")
                print(f"  样本数: {len(filtered)}")
                print(f"  平均变动: {statistics.mean(filtered):.2f}%")
                print(f"  中位变动: {statistics.median(filtered):.2f}%")

        # 产品价值评估
        print("\n" + "=" * 60)
        print("产品价值评估")
        print("=" * 60)

        # 评分
        scores = {}

        # 1. 事件频率
        if total_markets > 0:
            events_per_market = total_events / total_markets
            if events_per_market >= 20:
                scores['frequency'] = ('高', 3, '用户有持续内容看')
            elif events_per_market >= 5:
                scores['frequency'] = ('中', 2, '事件适中')
            else:
                scores['frequency'] = ('低', 1, '事件稀少')

        # 2. 信号质量
        if all_signals:
            acc = sum(all_signals) / len(all_signals) * 100
            if acc >= 55:
                scores['signal'] = ('好', 3, f'{acc:.0f}%准确率')
            elif acc >= 52:
                scores['signal'] = ('一般', 2, f'{acc:.0f}%略高于随机')
            else:
                scores['signal'] = ('差', 1, f'{acc:.0f}%接近随机')
        else:
            scores['signal'] = ('未知', 0, '数据不足')

        # 3. 覆盖度
        type_coverage = len([t for t in stats_by_type.values() if t['events'] > 0])
        if type_coverage >= 3:
            scores['coverage'] = ('好', 3, '全类型覆盖')
        elif type_coverage >= 2:
            scores['coverage'] = ('中', 2, '部分覆盖')
        else:
            scores['coverage'] = ('差', 1, '覆盖不足')

        print("\n评分:")
        total_score = 0
        for dim, (level, score, reason) in scores.items():
            print(f"  {dim}: {level} ({score}/3) - {reason}")
            total_score += score

        print(f"\n综合得分: {total_score}/9")

        if total_score >= 7:
            print("\n结论: 产品有较好价值，值得开发")
            print("建议: 优先实现，可作为核心功能")
        elif total_score >= 5:
            print("\n结论: 产品有一定价值，但需谨慎")
            print("建议: 可作为辅助功能，需降低用户预期")
        else:
            print("\n结论: 产品价值有限")
            print("建议: 需要重新考虑产品定位或寻找其他切入点")

        # 具体建议
        print("\n具体建议:")

        # 根据数据给出建议
        short_term = stats_by_type.get('short_term', {})
        if short_term.get('events', 0) > 0:
            st_per_market = short_term['events'] / short_term['markets'] if short_term['markets'] > 0 else 0
            if st_per_market > 10:
                print("  1. 短期市场事件密集，是产品核心价值来源")

        sports = stats_by_type.get('sports', {})
        if sports.get('events', 0) > 0:
            print("  2. 体育市场有异常信号，可纳入监控")

        if all_signals and sum(all_signals)/len(all_signals) < 0.53:
            print("  3. 信号预测性弱，建议定位为'信息雷达'而非'预测工具'")

        # 示例事件
        if all_events:
            print("\n最新异常事件示例:")
            recent = sorted(all_events, key=lambda x: x['timestamp'], reverse=True)[:5]
            for i, e in enumerate(recent):
                types = ", ".join(e['anomaly_types'])
                print(f"\n  {i+1}. [{e['market_type']}] {e['market']}")
                print(f"     时间: {e['datetime']}")
                print(f"     类型: {types}")
                print(f"     钱包: {e['wallet_count']}, 成交量: ${e['total_volume']:.0f}")
                if e.get('price_change_pct') is not None:
                    direction = "+" if e['price_change_pct'] > 0 else ""
                    correct = "correct" if e.get('signal_correct') else "wrong"
                    print(f"     30分钟后: {direction}{e['price_change_pct']:.2f}% ({correct})")


def main():
    print("\n" + "=" * 60)
    print("  Polymarket 全面异常检测回测")
    print("=" * 60 + "\n")

    tester = FullBacktester()
    events = tester.run()

    if events:
        with open("/Users/huan/Desktop/prediction market/PolySurge/backtest_full_events.json", 'w') as f:
            json.dump(events, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n\n事件数据已保存: backtest_full_events.json")
        print(f"共 {len(events)} 个事件")


if __name__ == "__main__":
    main()
