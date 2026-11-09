import unittest
import xml.etree.ElementTree as ET

from animations.build_frames import ROOT, STATES, frame


class AnimationTests(unittest.TestCase):
    def test_fixed_size_frames_and_assets(self):
        self.assertEqual(len(STATES), 6)
        for state in STATES:
            for index in range(4):
                svg = ET.fromstring(frame(state['id'], index))
                self.assertEqual(svg.get('viewBox'), '0 0 320 280')
                self.assertEqual((ROOT / 'frames' / ('%s-%s.svg' % (state['id'], index))).read_text(encoding='utf-8'), frame(state['id'], index))

    def test_still_states_and_visible_changes(self):
        self.assertEqual(frame('cooking', 0), frame('cooking', 3))
        self.assertEqual(frame('error', 0), frame('error', 3))
        self.assertNotEqual(frame('idle', 0), frame('idle', 1))
        self.assertNotEqual(frame('planning', 0), frame('planning', 1))


if __name__ == '__main__':
    unittest.main()
