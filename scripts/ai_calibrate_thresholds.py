import argparse
import json
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


def percentile(values, q):
    if not values:
        return 0.0
    idx = int(round((len(values) - 1) * q))
    idx = max(0, min(len(values) - 1, idx))
    return float(values[idx])


def main() -> int:
    parser = argparse.ArgumentParser(description='Suggest species threshold tuning from labeled manifest rows.')
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()

    rows = load_rows(args.manifest)
    labeled = [r for r in rows if 'true_species_id' in r]
    if not labeled:
        print('No labeled rows. Add true_species_id in manifest rows first.')
        return 1

    correct = []
    wrong = []
    for row in labeled:
        pred = int(row.get('species_id', 0) or 0)
        true = int(row.get('true_species_id', 0) or 0)
        item = {
            'conf': float(row.get('ai_confidence', 0.0) or 0.0),
            'dist': int(row.get('sprite_distance', 999) or 999),
            'margin': int(row.get('sprite_margin', 0) or 0),
        }
        if pred > 0 and pred == true:
            correct.append(item)
        else:
            wrong.append(item)

    if not correct:
        print('No correct labeled rows found; cannot calibrate.')
        return 1

    correct_conf = sorted(x['conf'] for x in correct)
    wrong_conf = sorted(x['conf'] for x in wrong)
    correct_dist = sorted(x['dist'] for x in correct)
    wrong_margin = sorted(x['margin'] for x in wrong)

    rec_min_conf = max(0.20, min(0.95, percentile(correct_conf, 0.20)))
    rec_soft_max_dist = int(max(8, min(80, percentile(correct_dist, 0.80))))
    rec_min_margin = int(max(4, min(40, percentile(wrong_margin, 0.80) if wrong_margin else 12)))

    print('Recommended config overrides:')
    print(f'  video_ai_species_min_confidence={rec_min_conf:.3f}')
    print(f'  video_ai_species_soft_max_distance={rec_soft_max_dist}')
    print(f'  video_ai_species_soft_min_margin={rec_min_margin}')
    print('')
    print(f'Labeled rows: {len(labeled)} | Correct: {len(correct)} | Wrong: {len(wrong)}')
    if wrong_conf:
        print(f'Wrong confidence p90: {percentile(wrong_conf, 0.90):.3f}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
