import io

import pytest
from PIL import Image

from arena_team_report import render_team_plans


DEFENSES = [{'ids': list(range(start, start + 5))} for start in (1001, 1006, 1011)]


def attack(start, color):
    payload = io.BytesIO()
    Image.new('RGB', (270, 62), color).save(payload, format='PNG')
    return {'ids': list(range(start, start + 5)), 'image': payload.getvalue(),
            'metadata': '网页作业 #1\n赞 20 / 踩 1\n2026-10-21 12:00'}


@pytest.mark.parametrize('plan_count', [0, 1, 5, 10])
def test_long_report_keeps_all_complete_plans(tmp_path, plan_count):
    plan = (attack(1100, '#dc2444'), attack(1200, '#16a470'), attack(1300, '#2768df'))
    path = render_team_plans(DEFENSES, [plan] * plan_count, tmp_path/'report.png', candidate_counts=[10,10,10])
    with Image.open(path) as image:
        assert image.width == 1000
        assert image.height > plan_count * 3 * 190
        if plan_count:
            for index, color in enumerate(((220,36,68), (22,164,112), (39,104,223))):
                for number in range(plan_count):
                    assert image.getpixel((100, 280 + number * 661 + index * 195)) == color


@pytest.mark.parametrize('plan', [
    (attack(1100, 'red'), attack(1104, 'green'), attack(1300, 'blue')),
    (attack(1100, 'red'), attack(1200, 'green')),
])
def test_renderer_rejects_repeated_or_missing_teams(tmp_path, plan):
    path = tmp_path/'invalid.png'
    with pytest.raises(ValueError):
        render_team_plans(DEFENSES, [plan], path)
    assert not path.exists()
