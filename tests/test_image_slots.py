"""Exact avatar slots use injected, deterministic artwork and no network."""

from copy import deepcopy
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

import pcr_image_recognizer as recognition
from pcr_image_recognizer import ImageRecognitionError, PcrImageRecognizer


def portrait(seed):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(30, 220, (80, 80, 3), dtype=np.uint8))


@pytest.fixture(autouse=True)
def forbid_network_and_detection(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('exact-slot recognition must not fetch, open files, or detect contours')

    monkeypatch.setattr(recognition, 'urlopen', forbidden)
    monkeypatch.setattr(recognition, '_fetch_icon', forbidden)
    monkeypatch.setattr(recognition, '_team_rows', forbidden)
    monkeypatch.setattr(recognition, '_icon_boxes', forbidden)
    monkeypatch.setattr(Image, 'open', forbidden)


@pytest.fixture
def templates():
    return {chara_id: portrait(index) for index, chara_id in
            enumerate([1001, 1002, 1500, 1998, 1999])}


@pytest.fixture
def recognizer(templates):
    return PcrImageRecognizer(templates=templates)


@pytest.fixture
def slots(templates):
    return [templates[chara_id].copy() for chara_id in [1999, 1001, 1998, 1002, 1500]]


def mock_matcher(monkeypatch, recognizer, results=None):
    if results is None:
        results = [(1001 + index, 0.95) for index in range(5)]
    matcher = Mock(side_effect=results)
    monkeypatch.setattr(recognizer, '_match_segment', matcher)
    return matcher


@pytest.mark.parametrize('container', [list, tuple])
def test_textured_slots_return_canonical_ids_in_visible_order(recognizer, slots, container):
    assert recognizer.recognize_slots(container(slots)) == [1999, 1001, 1998, 1002, 1500]
    assert recognizer.threshold == 0.72


@pytest.mark.parametrize('count', [0, 1, 4, 6, 10])
@pytest.mark.parametrize('container', [list, tuple])
def test_requires_exactly_five_slots(recognizer, slots, monkeypatch, count, container):
    matcher = mock_matcher(monkeypatch, recognizer)
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(container([slots[0]] * count))
    matcher.assert_not_called()


@pytest.mark.parametrize('images', [None, 'images', b'images', {}, 5, iter(()), object()])
def test_requires_list_or_tuple(recognizer, monkeypatch, images):
    matcher = mock_matcher(monkeypatch, recognizer)
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(images)
    matcher.assert_not_called()


def test_five_element_generator_is_not_consumed(recognizer, slots, monkeypatch):
    matcher = mock_matcher(monkeypatch, recognizer)
    images = iter(slots)
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(images)
    assert next(images) is slots[0]
    matcher.assert_not_called()


@pytest.mark.parametrize('invalid', [None, 'avatar.png', b'not image bytes', 1,
                                  {'size': (80, 80)}, [80, 80], object()])
def test_non_pil_slot_fails_before_matching(recognizer, slots, monkeypatch, invalid):
    matcher = mock_matcher(monkeypatch, recognizer)
    slots[-1] = invalid
    with pytest.raises(ImageRecognitionError, match='5'):
        recognizer.recognize_slots(slots)
    matcher.assert_not_called()


def test_numpy_array_is_not_a_pil_slot(recognizer, slots, monkeypatch):
    matcher = mock_matcher(monkeypatch, recognizer)
    slots[0] = np.zeros((80, 80, 3), dtype=np.uint8)
    with pytest.raises(ImageRecognitionError, match='1'):
        recognizer.recognize_slots(slots)
    matcher.assert_not_called()


@pytest.mark.parametrize('size', [(0, 24), (23, 24), (24, 23), (513, 24), (24, 513), (513, 513)])
def test_invalid_dimensions_fail_before_matching(recognizer, slots, monkeypatch, size):
    matcher = mock_matcher(monkeypatch, recognizer)
    slots[-1] = Image.new('RGB', size)
    with pytest.raises(ImageRecognitionError, match='5'):
        recognizer.recognize_slots(slots)
    matcher.assert_not_called()


@pytest.mark.parametrize('size', [(24, 24), (512, 512), (24, 512), (512, 24)])
def test_dimension_limits_are_inclusive(recognizer, monkeypatch, size):
    matcher = mock_matcher(monkeypatch, recognizer)
    images = [Image.new('RGB', size) for _ in range(5)]
    assert recognizer.recognize_slots(images) == [1001, 1002, 1003, 1004, 1005]
    assert matcher.call_count == 5
    assert all(call.args[0].size == size for call in matcher.call_args_list)


def test_missing_bank_is_not_reloaded_or_downloaded(slots, monkeypatch):
    recognizer = PcrImageRecognizer()
    matcher = mock_matcher(monkeypatch, recognizer)
    forbidden = Mock(side_effect=AssertionError('recognition must not load or warm a bank'))
    for name in ('load_templates', 'load_cached_templates', 'warmup', 'warm_templates'):
        monkeypatch.setattr(recognizer, name, forbidden)

    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(slots)

    matcher.assert_not_called()
    forbidden.assert_not_called()
    assert recognizer._bank == ()


def test_all_slots_use_one_bank_snapshot_taken_under_lock(recognizer, slots, monkeypatch):
    snapshot = recognizer._bank
    recognizer._bank = ()

    class SnapshotLock:
        entered = 0
        held = False

        def __enter__(self):
            self.entered += 1
            self.held = True
            recognizer._bank = snapshot

        def __exit__(self, *args):
            self.held = False
            recognizer._bank = ()

    lock = SnapshotLock()
    monkeypatch.setattr(recognizer, '_lock', lock)
    calls = []

    def match(segment, bank):
        assert not lock.held
        assert bank is snapshot
        assert recognizer._bank == ()
        calls.append(segment)
        return 1000 + len(calls), 0.95

    monkeypatch.setattr(recognizer, '_match_segment', match)

    assert recognizer.recognize_slots(slots) == [1001, 1002, 1003, 1004, 1005]
    assert lock.entered == 1
    assert len(calls) == 5


def test_duplicate_identity_is_not_forced_to_another_candidate(recognizer, slots):
    slots[-1] = slots[0].copy()
    with pytest.raises(ImageRecognitionError, match='1999'):
        recognizer.recognize_slots(slots)


def test_different_rarity_images_of_one_identity_are_duplicates(templates):
    alternate = portrait(80)
    templates[1001] = [templates[1001], alternate]
    recognizer = PcrImageRecognizer(templates=templates)
    images = [templates[chara_id] for chara_id in [1999, 1002, 1500]]
    images += [templates[1001][0], alternate]
    with pytest.raises(ImageRecognitionError, match='1001'):
        recognizer.recognize_slots(images)


def test_identical_templates_for_different_characters_are_ambiguous(templates, slots):
    templates[1200] = templates[1999].copy()
    recognizer = PcrImageRecognizer(templates=templates)
    with pytest.raises(ImageRecognitionError) as caught:
        recognizer.recognize_slots(slots)
    assert isinstance(caught.value.__cause__, ImageRecognitionError)
    assert '1' in str(caught.value)


def test_unrelated_textured_slot_does_not_get_a_low_confidence_identity(recognizer, slots):
    slots[2] = portrait(999)
    with pytest.raises(ImageRecognitionError) as caught:
        recognizer.recognize_slots(slots)
    assert isinstance(caught.value.__cause__, ImageRecognitionError)
    assert '3' in str(caught.value)


def test_textureless_slot_is_rejected(recognizer, slots):
    slots[1] = Image.new('RGB', (80, 80), 'white')
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(slots)


def test_matcher_error_retains_cause_and_failed_slot_index(recognizer, slots, monkeypatch):
    error = ImageRecognitionError('ambiguous or low confidence')
    matcher = mock_matcher(monkeypatch, recognizer, [(1001, 0.95), error])
    with pytest.raises(ImageRecognitionError, match='2') as caught:
        recognizer.recognize_slots(slots)
    assert caught.value.__cause__ is error
    assert matcher.call_count == 2


@pytest.mark.parametrize('chara_id', [1000, 2000, 100161, -1001, True, None, '1001', 1001.0])
def test_noncanonical_matcher_id_is_rejected(recognizer, slots, monkeypatch, chara_id):
    matcher = mock_matcher(monkeypatch, recognizer, [(chara_id, 0.99)])
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(slots)
    assert matcher.call_count == 1


@pytest.mark.parametrize('score', [0.719, 0.0, float('nan'), float('inf'), -float('inf')])
def test_low_or_nonfinite_matcher_score_is_rejected(recognizer, slots, monkeypatch, score):
    mock_matcher(monkeypatch, recognizer, [(1001, score)])
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(slots)
    assert recognizer.threshold == 0.72


def test_configured_threshold_is_not_lowered(templates, slots, monkeypatch):
    recognizer = PcrImageRecognizer(templates=templates, threshold=0.93)
    mock_matcher(monkeypatch, recognizer, [(1001, 0.92)])
    with pytest.raises(ImageRecognitionError):
        recognizer.recognize_slots(slots)
    assert recognizer.threshold == 0.93


def test_score_at_existing_threshold_is_accepted(recognizer, slots, monkeypatch):
    mock_matcher(monkeypatch, recognizer, [(1001 + index, 0.72) for index in range(5)])
    assert recognizer.recognize_slots(slots) == [1001, 1002, 1003, 1004, 1005]


def test_real_matching_preserves_images_modes_metadata_and_order(recognizer, slots):
    images = [image.convert('RGBA') for image in slots]
    for index, image in enumerate(images):
        image.info['slot'] = {'position': index}
    before = [(id(image), image.mode, image.size, image.tobytes(), deepcopy(image.info))
              for image in images]

    assert recognizer.recognize_slots(images) == [1999, 1001, 1998, 1002, 1500]

    after = [(id(image), image.mode, image.size, image.tobytes(), image.info) for image in images]
    assert after == before


def test_matcher_receives_independent_rgb_images(recognizer, slots, monkeypatch):
    originals = [image.tobytes() for image in slots]
    calls = []

    def match(segment, bank):
        index = len(calls)
        assert segment is not slots[index]
        assert segment.mode == 'RGB'
        segment.paste('black', (0, 0, segment.width, segment.height))
        calls.append(segment)
        return 1001 + index, 0.95

    monkeypatch.setattr(recognizer, '_match_segment', match)
    assert recognizer.recognize_slots(slots) == [1001, 1002, 1003, 1004, 1005]
    assert [image.tobytes() for image in slots] == originals


def test_closed_slot_raises_recognition_error(recognizer, slots):
    slots[2].close()
    with pytest.raises(ImageRecognitionError) as caught:
        recognizer.recognize_slots(slots)
    assert isinstance(caught.value.__cause__, ValueError)
    assert '3' in str(caught.value)
