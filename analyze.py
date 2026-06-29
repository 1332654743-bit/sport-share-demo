#!/usr/bin/env python3
"""
运动分享调研数据分析脚本

用法:
  python analyze.py --url https://your-app.vercel.app/api/results
  python analyze.py --dir ./data_files/
  python analyze.py --file tracker-xxx.json tracker-yyy.json

输出: 终端表格 + report.md 文件
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from statistics import median, mean

# ========== 数据加载 ==========

def load_from_url(url):
    import urllib.request
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
    return data['submissions']

def load_from_dir(dirpath):
    submissions = []
    for fname in sorted(os.listdir(dirpath)):
        if not fname.endswith('.json'):
            continue
        fpath = os.path.join(dirpath, fname)
        with open(fpath, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        # 支持两种格式: 直接 {events, summary} 或包装后的 {userId, data: {events, summary}}
        if 'data' in raw and 'events' in raw['data']:
            submissions.append(raw)
        elif 'events' in raw:
            submissions.append({'userId': fname, 'data': raw, 'submittedAt': ''})
    return submissions

def load_from_files(filepaths):
    submissions = []
    for fpath in filepaths:
        with open(fpath, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if 'data' in raw and 'events' in raw['data']:
            submissions.append(raw)
        elif 'events' in raw:
            submissions.append({'userId': os.path.basename(fpath), 'data': raw, 'submittedAt': ''})
    return submissions

# ========== 分析核心 ==========

SCENARIO_NAMES = {'daily': '日常打卡', 'pb': '成绩突破', 'marathon': '马拉松完赛'}
STYLE_NAMES = {'watermark': '水印海报', 'video': '轨迹视频', 'report': '运动报告'}
WEIGHTS = {'daily': 0.60, 'pb': 0.25, 'marathon': 0.15}

def analyze_q1(submissions):
    """Q1: 各场景下用户更倾向哪类分享样式"""
    matrix = {s: Counter() for s in ['daily', 'pb', 'marathon']}

    for sub in submissions:
        summary = sub.get('data', {}).get('summary', {})
        for scenario, info in summary.items():
            if scenario in matrix:
                style = info.get('styleChoice', 'unknown')
                matrix[scenario][style] += 1

    return matrix

def analyze_q2(submissions):
    """Q2: 用户是否愿意编辑 + 花多久"""
    durations = defaultdict(list)
    feature_counts = defaultdict(list)
    abandon_count = defaultdict(int)
    total_per_scenario = defaultdict(int)

    for sub in submissions:
        summary = sub.get('data', {}).get('summary', {})
        for scenario, info in summary.items():
            if scenario not in SCENARIO_NAMES:
                continue
            total_per_scenario[scenario] += 1
            durations[scenario].append(info.get('totalDuration', 0))
            feature_counts[scenario].append(info.get('featureCount', 0))
            if info.get('abandoned'):
                abandon_count[scenario] += 1

    result = {}
    for s in ['daily', 'pb', 'marathon']:
        arr = sorted(durations[s]) if durations[s] else [0]
        fc = feature_counts[s] if feature_counts[s] else [0]
        total = total_per_scenario[s] or 1
        zero_edit = sum(1 for c in fc if c <= 1)  # 只选了样式没做其他操作
        result[s] = {
            'median_ms': median(arr),
            'mean_ms': mean(arr),
            'p25_ms': arr[len(arr)//4] if len(arr) >= 4 else arr[0],
            'p75_ms': arr[3*len(arr)//4] if len(arr) >= 4 else arr[-1],
            'zero_edit_rate': zero_edit / total,
            'abandon_rate': abandon_count[s] / total,
            'n': total
        }
    return result

def analyze_q3(submissions):
    """Q3: 用户真实优先使用哪些功能"""
    feature_users = Counter()  # 多少人用了该功能
    feature_order = defaultdict(list)  # 该功能在各人操作序列中的排位

    total_users = len(submissions)

    for sub in submissions:
        summary = sub.get('data', {}).get('summary', {})
        seen = set()
        for scenario in ['daily', 'pb', 'marathon']:
            info = summary.get(scenario, {})
            features = info.get('featuresUsed', [])
            for i, feat in enumerate(features):
                if feat.startswith('style-'):
                    continue  # 排除样式选择本身
                if feat not in seen:
                    feature_users[feat] += 1
                    seen.add(feat)
                feature_order[feat].append(i)

    result = []
    for feat, count in feature_users.most_common(20):
        orders = feature_order[feat]
        result.append({
            'feature': feat,
            'users': count,
            'usage_rate': count / total_users if total_users else 0,
            'avg_order': mean(orders) if orders else 99,
        })
    return result

def weighted_style(q1_matrix):
    """加权合并样式选择"""
    styles = ['watermark', 'video', 'report']
    weighted = Counter()
    total_weight = 0
    for scenario, counter in q1_matrix.items():
        w = WEIGHTS.get(scenario, 0)
        scenario_total = sum(counter.values()) or 1
        for style in styles:
            weighted[style] += w * (counter.get(style, 0) / scenario_total)
        total_weight += w
    # Normalize
    result = {}
    for style in styles:
        result[style] = weighted[style] / total_weight if total_weight else 0
    return result

# ========== 报表输出 ==========

def fmt_dur(ms):
    s = round(ms / 1000)
    if s < 60:
        return f"{s}秒"
    return f"{s//60}分{s%60}秒"

def fmt_pct(rate):
    return f"{rate*100:.0f}%"

def generate_report(submissions):
    n = len(submissions)
    lines = []
    lines.append(f"# 运动分享调研分析报告\n")
    lines.append(f"**样本量：{n} 人**\n")
    lines.append(f"---\n")

    # Q1
    q1 = analyze_q1(submissions)
    lines.append("## Q1: 各场景下用户更倾向哪类分享样式\n")
    lines.append("| 场景 | 水印海报 | 轨迹视频 | 运动报告 |")
    lines.append("|------|---------|---------|---------|")
    for s in ['daily', 'pb', 'marathon']:
        total = sum(q1[s].values()) or 1
        row = [SCENARIO_NAMES[s]]
        for style in ['watermark', 'video', 'report']:
            count = q1[s].get(style, 0)
            row.append(f"{count}/{total} ({fmt_pct(count/total)})")
        lines.append(f"| {' | '.join(row)} |")

    ws = weighted_style(q1)
    lines.append(f"\n**加权汇总**（日常60%/PB25%/马拉松15%）：海报 {fmt_pct(ws['watermark'])} / 视频 {fmt_pct(ws['video'])} / 报告 {fmt_pct(ws['report'])}\n")
    lines.append("---\n")

    # Q2
    q2 = analyze_q2(submissions)
    lines.append("## Q2: 用户编辑意愿与时长\n")
    lines.append("| 场景 | 中位时长 | 平均时长 | P25 | P75 | 不编辑比例 | 放弃率 |")
    lines.append("|------|---------|---------|-----|-----|-----------|-------|")
    for s in ['daily', 'pb', 'marathon']:
        info = q2[s]
        lines.append(f"| {SCENARIO_NAMES[s]} | {fmt_dur(info['median_ms'])} | {fmt_dur(info['mean_ms'])} | {fmt_dur(info['p25_ms'])} | {fmt_dur(info['p75_ms'])} | {fmt_pct(info['zero_edit_rate'])} | {fmt_pct(info['abandon_rate'])} |")
    lines.append("")
    lines.append("---\n")

    # Q3
    q3 = analyze_q3(submissions)
    lines.append("## Q3: 功能优先级排序\n")
    lines.append("| 排名 | 功能 | 使用率 | 平均操作顺序 | 使用人数 |")
    lines.append("|------|------|--------|------------|---------|")
    for i, item in enumerate(q3[:15], 1):
        lines.append(f"| {i} | {item['feature']} | {fmt_pct(item['usage_rate'])} | {item['avg_order']:.1f} | {item['users']}/{n} |")
    lines.append("")
    lines.append("---\n")

    # Summary
    lines.append("## 结论摘要\n")
    top_style = max(ws, key=ws.get)
    lines.append(f"- **最受偏好的样式：** {STYLE_NAMES.get(top_style, top_style)}（加权 {fmt_pct(ws[top_style])}）")
    daily_zero = q2['daily']['zero_edit_rate']
    lines.append(f"- **日常场景不编辑比例：** {fmt_pct(daily_zero)}")
    marathon_dur = q2['marathon']['median_ms']
    lines.append(f"- **马拉松场景中位编辑时长：** {fmt_dur(marathon_dur)}")
    if q3:
        lines.append(f"- **最高使用率功能：** {q3[0]['feature']}（{fmt_pct(q3[0]['usage_rate'])}）")
    lines.append("")

    return '\n'.join(lines)

# ========== 主函数 ==========

def main():
    parser = argparse.ArgumentParser(description='运动分享调研数据分析')
    parser.add_argument('--url', help='从线上 /api/results 接口拉取数据')
    parser.add_argument('--dir', help='从本地文件夹读取 JSON 文件')
    parser.add_argument('--file', nargs='+', help='指定一个或多个 JSON 文件')
    parser.add_argument('--output', default='report.md', help='输出报告文件名 (默认 report.md)')
    args = parser.parse_args()

    if args.url:
        print(f"从 {args.url} 拉取数据...")
        submissions = load_from_url(args.url)
    elif args.dir:
        print(f"从 {args.dir} 读取文件...")
        submissions = load_from_dir(args.dir)
    elif args.file:
        print(f"读取 {len(args.file)} 个文件...")
        submissions = load_from_files(args.file)
    else:
        print("请指定数据来源: --url / --dir / --file")
        print("示例: python analyze.py --file tracker-xxx.json")
        sys.exit(1)

    if not submissions:
        print("❌ 未找到有效数据")
        sys.exit(1)

    print(f"✅ 加载 {len(submissions)} 份数据\n")

    report = generate_report(submissions)
    print(report)

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n📄 报告已保存到: {args.output}")

if __name__ == '__main__':
    main()
