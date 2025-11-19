#!/usr/bin/env python3
"""
Polymarket 异常检测回测 v2

改进策略：
1. 不只看新钱包涌入，还检测成交量飙升
2. 使用更合理的阈值
3. 分析信号预测价值

排除：sports 市场和超短期（15m/日内）市场
"""

import requests
import time
import json
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List
import statistics

API_BASE = "https://data-api.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


class BacktesterV2:
    def __init__(self):
        self.session = requests.Session()

    def get_markets(self, limit=50):
        """获取符合条件的市场"""
        print("=== 获取市场列表 ===")

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
        all_markets = resp.json()

        # 过滤条件
        sports = ['nba', 'nfl', 'mlb', 'soccer', 'football', 'basketball',
                  'match', 'game', 'vs.', 'vs ', 'euro', 'win on']
        short = ['15m', '30m', '1h', 'hour', 'minute', 'daily', 'today']

        markets = []
        for m in all_markets:
            q = m.get('question', '').lower()
            s = m.get('slug', '').lower()
            cid = m.get('conditionId', '')

            if not cid:
                continue
            if any(k in q or k in s for k in sports):
                continue
            if any(k in q or k in s for k in short):
                continue

            markets.append({
                'condition_id': cid,
                'question': m.get('question', ''),
                'volume_24h': m.get('volume24hrClob', 0) or 0
            })

            if len(markets) >= limit:
                break

        print(f"找到 {len(markets)} 个非体育非短期市场")
        return markets

    def get_trades(self, condition_id, limit=1000):
        """获取交易数据"""
        resp = self.session.get(
            f"{API_BASE}/trades",
            params={"market": condition_id, "limit": limit},
            timeout=30
        )
        return resp.json()

    def detect_anomalies(self, trades, window_min=5):
        """
        多维度异常检测：
        1. 成交量飙升（相对于历史平均）
        2. 新钱包涌入
        3. 净买入/卖出方向
        """
        if len(trades) < 20:
            return []

        # 按时间排序
        trades = sorted(trades, key=lambda x: x.get('timestamp', 0))

        window_sec = window_min * 60
        events = []
        seen_wallets = set()

        # 计算各窗口的成交量，用于确定基准
        all_volumes = []
        for i, t in enumerate(trades):
            current_time = t['timestamp']
            window = [x for x in trades[:i+1]
                     if current_time - window_sec <= x['timestamp'] <= current_time]
            vol = sum(x.get('size', 0) * x.get('price', 0) for x in window)
            if len(window) >= 3:
                all_volumes.append(vol)

        if not all_volumes:
            return []

        # 计算基准（中位数，避免异常值影响）
        median_vol = statistics.median(all_volumes)

        for i, t in enumerate(trades):
            current_time = t['timestamp']

            # 获取当前窗口的交易
            window = [x for x in trades[:i+1]
                     if current_time - window_sec <= x['timestamp'] <= current_time]

            if len(window) < 3:
                seen_wallets.add(t.get('proxyWallet', ''))
                continue

            # 计算指标
            wallets = set(x.get('proxyWallet', '') for x in window)
            new_wallets = wallets - seen_wallets

            buy_vol = sum(x.get('size', 0) * x.get('price', 0)
                         for x in window if x.get('side') == 'BUY')
            sell_vol = sum(x.get('size', 0) * x.get('price', 0)
                          for x in window if x.get('side') == 'SELL')
            total_vol = buy_vol + sell_vol
            net_vol = buy_vol - sell_vol

            # 多条件检测 - 提高阈值减少噪音
            vol_spike = total_vol > median_vol * 5 if median_vol > 0 else False  # 5x 而非 2x
            wallet_surge = len(new_wallets) >= 4  # 4个而非3个

            # 触发异常事件 - 更严格的条件
            is_anomaly = vol_spike or (wallet_surge and total_vol > median_vol * 3)

            if is_anomaly:
                events.append({
                    'timestamp': current_time,
                    'datetime': datetime.fromtimestamp(current_time).isoformat(),
                    'new_wallets': len(new_wallets),
                    'unique_wallets': len(wallets),
                    'total_volume': total_vol,
                    'net_volume': net_vol,
                    'volume_ratio': total_vol / median_vol if median_vol > 0 else 0,
                    'is_buy': net_vol > 0,
                    'trade_count': len(window),
                    'trigger': 'volume_spike' if vol_spike else 'wallet_surge'
                })

            seen_wallets.add(t.get('proxyWallet', ''))

        return events

    def check_price_after(self, event, trades, forward_min=30):
        """检查事件后的价格变化"""
        event_time = event['timestamp']
        forward_sec = forward_min * 60

        # 事件前的价格
        before = [t for t in trades if t['timestamp'] <= event_time]
        if not before:
            return None
        before_prices = [t.get('price', 0) for t in before[-10:]]
        event_price = statistics.mean(before_prices) if before_prices else 0

        # 事件后的交易
        after = [t for t in trades
                if event_time < t['timestamp'] <= event_time + forward_sec]
        if not after:
            return None

        after_prices = [t.get('price', 0) for t in after]
        final_price = statistics.mean(after_prices[-5:]) if len(after_prices) >= 5 else after_prices[-1]

        change = final_price - event_price
        change_pct = (change / event_price * 100) if event_price > 0 else 0

        # 信号是否正确（买入涌入应对应价格上涨）
        correct = (event['is_buy'] and change > 0) or (not event['is_buy'] and change < 0)

        return {
            'price_change': change,
            'price_change_pct': change_pct,
            'signal_correct': correct
        }

    def run(self):
        """运行回测"""
        print("=" * 60)
        print("Polymarket 异常检测回测 v2")
        print("=" * 60)
        print("\n策略：成交量飙升 + 钱包涌入复合检测")
        print("阈值：成交量 > 2x中位数 或 (新钱包>=3 且 成交量>1.5x中位数)")

        markets = self.get_markets(limit=30)

        total_events = 0
        all_events = []
        signal_results = []

        print(f"\n=== 分析 {len(markets)} 个市场 ===\n")

        for i, m in enumerate(markets):
            cid = m['condition_id']
            q = m['question'][:45]

            print(f"[{i+1}/{len(markets)}] {q}...", end=" ")

            trades = self.get_trades(cid, limit=1000)
            if not trades:
                print("无数据")
                continue

            events = self.detect_anomalies(trades)

            if events:
                total_events += len(events)
                print(f"{len(trades)}笔交易, {len(events)}个异常")

                for e in events:
                    e['market'] = q
                    e['condition_id'] = cid

                    result = self.check_price_after(e, trades)
                    if result:
                        e.update(result)
                        signal_results.append(result['signal_correct'])

                    all_events.append(e)
            else:
                print(f"{len(trades)}笔交易, 无异常")

            time.sleep(0.3)

        # 输出结果
        self.print_results(markets, total_events, all_events, signal_results)

        return all_events

    def print_results(self, markets, total_events, all_events, signal_results):
        """打印结果"""
        print("\n" + "=" * 60)
        print("回测结果")
        print("=" * 60)

        print("\n基本统计:")
        print(f"  分析市场数: {len(markets)}")
        print(f"  检测到异常事件: {total_events}")

        if len(markets) > 0:
            print(f"  平均每市场事件数: {total_events/len(markets):.2f}")

        if total_events > 0:
            # 事件类型分布
            vol_spikes = sum(1 for e in all_events if e.get('trigger') == 'volume_spike')
            wallet_surges = total_events - vol_spikes
            print(f"\n事件类型:")
            print(f"  成交量飙升: {vol_spikes} ({vol_spikes/total_events*100:.0f}%)")
            print(f"  钱包涌入: {wallet_surges} ({wallet_surges/total_events*100:.0f}%)")

            # 成交量统计
            volumes = [e['total_volume'] for e in all_events]
            ratios = [e['volume_ratio'] for e in all_events]
            print(f"\n事件特征:")
            print(f"  平均成交量: ${statistics.mean(volumes):.0f}")
            print(f"  平均成交量倍数: {statistics.mean(ratios):.1f}x")

        # 信号有效性
        print("\n信号有效性:")
        if signal_results:
            correct = sum(signal_results)
            total = len(signal_results)
            accuracy = correct / total * 100
            print(f"  可分析事件: {total}")
            print(f"  信号正确: {correct}")
            print(f"  准确率: {accuracy:.1f}%")

            if accuracy >= 55:
                print(f"  评估: 有预测价值 (>{50}%)")
            else:
                print(f"  评估: 接近随机")
        else:
            print("  数据不足")

        # 价格影响
        if all_events:
            changes = [e.get('price_change_pct', 0) for e in all_events if e.get('price_change_pct')]
            if changes:
                print(f"\n价格影响:")
                print(f"  30分钟后平均变动: {statistics.mean(changes):.2f}%")
                print(f"  最大上涨: {max(changes):.2f}%")
                print(f"  最大下跌: {min(changes):.2f}%")

        # 核心结论
        print("\n" + "=" * 60)
        print("核心结论")
        print("=" * 60)

        if total_events == 0:
            print("\n问题1 - 事件频率太低:")
            print("  在非体育、非短期市场中，异常事件极其稀少")
            print("  这些市场交易分散，500条交易跨越数小时甚至数天")
            print("")
            print("问题2 - 产品价值受限:")
            print("  如果排除短期市场，用户几乎看不到异常提示")
            print("  产品缺乏持续的使用价值")
            print("")
            print("建议:")
            print("  1. 重新考虑是否纳入短期市场（那里信号多）")
            print("  2. 或转向其他指标（如大额单笔交易、鲸鱼追踪）")
            print("  3. 或定位为低频高价值提醒（类似地震预警）")
        else:
            events_per_market = total_events / len(markets) if markets else 0
            if events_per_market < 0.5:
                print("\n警告: 事件频率偏低")
                print(f"  平均每市场只有 {events_per_market:.2f} 个事件")
                print("  用户体验可能较差")

            if signal_results and sum(signal_results)/len(signal_results) > 0.55:
                print("\n积极信号: 检测到有效的预测信号")
            else:
                print("\n注意: 信号预测价值有限，建议定位为信息工具而非预测工具")

        # 示例事件
        if all_events:
            print("\n示例事件（最近5个）:")
            recent = sorted(all_events, key=lambda x: x['timestamp'], reverse=True)[:5]
            for i, e in enumerate(recent):
                print(f"\n  {i+1}. {e['market']}")
                print(f"     时间: {e['datetime']}")
                print(f"     类型: {e['trigger']}")
                print(f"     成交量: ${e['total_volume']:.0f} ({e['volume_ratio']:.1f}x)")
                if e.get('price_change_pct'):
                    direction = "+" if e['price_change_pct'] > 0 else ""
                    correct = " correct" if e.get('signal_correct') else " wrong"
                    print(f"     30分钟后: {direction}{e['price_change_pct']:.2f}%{correct}")


def main():
    print("\n" + "=" * 60)
    print("  Polymarket 异常检测回测工具 v2")
    print("=" * 60 + "\n")

    tester = BacktesterV2()
    events = tester.run()

    if events:
        with open("/Users/huan/Desktop/prediction market/PolySurge/backtest_v2_events.json", 'w') as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        print("\n事件数据已保存")


if __name__ == "__main__":
    main()
