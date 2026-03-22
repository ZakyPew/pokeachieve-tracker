import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_rows(path: Path):
    rows = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description='Evaluate AI species replay manifest.')
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    if not rows:
        print('No rows found.')
        return 1

    by_stage = Counter()
    by_source = Counter()
    species_counter = Counter()
    conf_bins = defaultdict(int)

    for row in rows:
        stage = str(row.get('stage', ''))
        source = str(row.get('species_source', ''))
        sid = int(row.get('species_id', 0) or 0)
        conf = float(row.get('ai_confidence', 0.0) or 0.0)

        by_stage[stage] += 1
        by_source[source] += 1
        if sid > 0:
            species_counter[sid] += 1

        bucket = min(9, max(0, int(conf * 10)))
        conf_bins[f'{bucket/10:.1f}-{(bucket+1)/10:.1f}'] += 1

    print(f'Rows: {len(rows)}')
    print('\nBy stage:')
    for key, value in by_stage.most_common():
        print(f'  {key or "(empty)"}: {value}')

    print('\nBy source:')
    for key, value in by_source.most_common():
        print(f'  {key or "(empty)"}: {value}')

    print('\nTop species IDs:')
    for sid, value in species_counter.most_common(15):
        print(f'  {sid}: {value}')

    print('\nAI confidence bins:')
    for key in sorted(conf_bins.keys()):
        print(f'  {key}: {conf_bins[key]}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
