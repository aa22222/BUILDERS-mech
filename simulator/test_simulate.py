"""Focused checks for simulator mechanics, independent of bot decisions."""
import unittest
from simulate import Arena, ROOT, CURRENT_BOT

class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.arena = Arena(1, 1, 'rooftop', CURRENT_BOT)

    def test_roof_support(self):
        a = self.arena.actors[0]
        before = list(a['pos'])
        self.arena.move(a, {'move':[0,0]}, .1, 0)
        self.assertEqual(before, a['pos'])
        self.assertGreater(a['pos'][2]-self.arena.geo.height(*a['pos'][:2]), 10)

    def test_zone_interpolation(self):
        z = self.arena.zone(0)
        self.assertEqual(z['radius'], 560)
        self.assertAlmostEqual(self.arena.zone(85)['radius'], 470)
        self.assertAlmostEqual(self.arena.zone(110)['radius'], 380)
        self.assertEqual(self.arena.zone(480)['radius'], 0)

    def test_damage_attribution(self):
        a = self.arena.actors[0]
        hp = a['hp']
        self.arena.hurt(a, 20, 'zone', 1)
        self.assertEqual(a['hp'], hp-20)
        self.assertEqual(self.arena.damage['zone'], 20)
        self.assertIsNone(self.arena.events[-1]['bearing'])

    def test_map_edge_blocks(self):
        b = self.arena.geo.world['bounds']
        self.assertFalse(self.arena.valid(b['maxX']+1, 0, 0))

if __name__ == '__main__':
    unittest.main()
