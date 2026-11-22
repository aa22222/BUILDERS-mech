"""Farm to ten cubes, then hide and take favorable opportunistic fights."""
import math
import time
import mechfight as mf
from avoid_bot import Bot as Navigator


def angle_error(a, b):
    return abs((a - b + math.pi) % math.tau - math.pi)


def intercept(origin, target, velocity, speed):
    """Constant-velocity intercept for a projectile without gravity."""
    delta = [target[i] - origin[i] for i in range(3)]
    a = sum(v * v for v in velocity) - speed * speed
    b = 2 * sum(delta[i] * velocity[i] for i in range(3))
    c = sum(v * v for v in delta)
    roots = []
    if abs(a) < 1e-8:
        if abs(b) > 1e-8:
            roots = [-c / b]
    elif b * b - 4 * a * c >= 0:
        discriminant = math.sqrt(b * b - 4 * a * c)
        roots = [(-b - discriminant) / (2 * a), (-b + discriminant) / (2 * a)]
    flight = min((r for r in roots if r >= 0), default=math.sqrt(c) / max(1, speed))
    return [target[i] + velocity[i] * min(flight, 2.0) for i in range(3)]


class Bot(Navigator):
    name = "cube-hunter"

    def __init__(self, hello: mf.Hello):
        super().__init__(hello)
        self.hide_unlocked = False
        self.recovering = False
        self.mode = "FARM"
        self.mission_goal = None
        self.mission_key = None
        self.nav_key = None
        self.active_target = None
        self.last_victim = None
        self.actor_memory = {}
        self.recent_attackers = {}
        self.loot_interest = None
        self.cube_memory = {}
        self.ignored_until = {}
        self.explore_goal = None
        self.visited = []
        self.watch = None
        self.combat_config = hello["config"]

    def damage_scale(self, cubes):
        rules = self.config["cubes"]
        return 1 + rules.get("damage_per_cube", .04) * min(cubes, rules.get("stat_cap", 10))

    def weapon_dps(self, kind, stats):
        if kind == "gun":
            mag = stats.get("mag", 12)
            return stats["damage"] * mag / max(.1, mag * stats["cooldown"] + stats.get("reload", 2.4))
        if kind == "laser":
            return stats["damage"] / max(.1, stats["cooldown"] + stats.get("charge", .75))
        return (stats["damage"] + (stats.get("splash", 0) if kind == "mortar" else 0)) / max(.1, stats["cooldown"])

    def strength(self, actor, own=False, distance=100):
        if actor.get("kind") == "npc":
            npc = self.config["npc"]
            return actor.get("hp", npc["hp"]) * npc["damage"] / max(.1, npc["cooldown"])
        dps = 0
        for weapon in actor.get("weapons", []):
            if not weapon:
                continue
            kind = weapon["kind"] if own else weapon
            stats = weapon["stats"] if own else self.config["weapons"][kind]
            # A short-range weapon still matters if the target closes the gap.
            effectiveness = .5 if kind == "lightning" and distance > stats.get("range", 45) else 1
            dps += effectiveness * self.weapon_dps(kind, stats)
        if not dps:
            dps = self.weapon_dps("gun", self.config["weapons"]["gun"])
        hp = actor.get("hp", actor.get("max_hp", self.config["mech"]["hp"]))
        armor = actor.get("stats", {}).get("armor", 0) if own else 0
        return hp / max(.3, 1 - armor) * dps * self.damage_scale(actor.get("cubes", 0))

    def weaker(self, me, enemy):
        if "hp" not in enemy or enemy["hp"] <= 0:
            return False
        d = math.dist(me["pos"], enemy["pos"])
        # Reserve a substantial margin for enemy upgrades and imperfect aim.
        return self.strength(me, True, d) >= 1.5 * self.strength(enemy, False, d)

    def safe_objective(self, point, obs):
        me = obs["self"]
        seconds = min(25, math.dist(me["pos"][:2], point[:2]) / max(1, me["stats"].get("walk_speed", 11.7)) + 4)
        center, radius = self.forecast(obs["zone"], obs["t"], seconds)
        return math.dist(point[:2], center) + me["stats"].get("radius", 2.5) + 6 < radius

    def reachable_surface(self, point, me):
        # Ground on a hill is reachable; a different roof level is not part of
        # this ground navigator. Pickup range is checked by the server on arrival.
        return abs(point[2] - me["pos"][2]) <= 4 or abs(point[2] - self.map.height(*point[:2])) <= 1.5

    def support_risk(self, point, obs, exclude=None):
        """Do not mistake one weak member of a nearby group for an easy fight."""
        count = 0
        for enemy in obs["mechs"]:
            if enemy["kind"] != "mech" or enemy["id"] == exclude:
                continue
            d = min(math.dist(point[:2], enemy["pos"][:2]), math.dist(obs["self"]["pos"][:2], enemy["pos"][:2]))
            if d < 110:
                count += 1 if self.weaker(obs["self"], enemy) else 2
        return count

    def plan(self, pos, center, radius, robots, height, now, deadline):
        if self.mission_goal is None:
            if self.nav_key is not None:
                self.route = []
                self.search = self.refuge_search = self.goal = None
                self.last_plan = -100
                self.nav_key = None
            return super().plan(pos, center, radius, robots, height, now, deadline)
        desired = tuple(self.mission_goal)
        changed = self.nav_key != self.mission_key or self.goal is None or math.dist(desired[:2], self.goal[:2]) > 12
        if changed:
            self.nav_key = self.mission_key
            self.goal = desired
            self.route = []
            self.refuge_search = None
            start, target = self.nearest_node(pos), self.nearest_node(desired)
            self.search = ([(0, start)], {start: 0}, {}, target) if start is not None and target is not None and start != target else None
        if self.search:
            # The first branch of Navigator.plan advances A* only, within budget.
            super().plan(pos, center, radius, robots, height, now, deadline)
            if self.goal is None:
                self.ignored_until[self.mission_key] = now + 12

    def target_center(self, target):
        kind = target.get("kind", "crate")
        if kind == "npc":
            height = self.config["npc"].get("height", 3.5)
            radius = self.config["npc"].get("radius", 1.8)
        elif kind == "crate":
            height = self.config["crates"].get("height", 2.4)
            radius = self.config["crates"].get("radius", 1.4)
        else:
            scale = 1 + self.config["cubes"].get("size_per_cube", .05) * target.get("cubes", 0)
            height = self.config["mech"].get("height", 9) * scale
            radius = self.config["mech"].get("radius", 2.5) * scale
        x, y, z = target["pos"]
        return [x, y, z + height * .5], radius

    def muzzle(self, me):
        stats = {**self.config["mech"], **me["stats"]}
        yaw, pitch = me["aim"]
        offset = stats.get("radius", 2.5) + .5
        return [me["pos"][0] + offset * math.cos(pitch) * math.cos(yaw),
                me["pos"][1] + offset * math.cos(pitch) * math.sin(yaw),
                me["pos"][2] + stats.get("muzzle_height", 7) + offset * math.sin(pitch)]

    def firing_action(self, me, target):
        """Aim first; fire only when the actual torso is aligned and sight is clear."""
        origin = self.muzzle(me)
        center, radius = self.target_center(target)
        gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
        speed = gun["stats"]["speed"] if gun else self.config["weapons"]["gun"]["speed"]
        point = intercept(origin, center, target.get("vel", [0, 0, 0]), speed)
        delta = [point[i] - origin[i] for i in range(3)]
        horizontal = math.hypot(*delta[:2])
        distance = math.sqrt(sum(v * v for v in delta))
        yaw = math.atan2(delta[1], delta[0])
        pitch = math.atan2(delta[2], horizontal)
        tolerance = max(.008, min(.10, math.atan2(radius * .8, max(1, distance))))
        aligned = angle_error(me["aim"][0], yaw) < tolerance and abs(me["aim"][1] - pitch) < tolerance
        # Check from body muzzle as well as barrel tip, preventing shots through
        # geometry when the nominal barrel offset would protrude through a wall.
        body_muzzle = [me["pos"][0], me["pos"][1], me["pos"][2] + me["stats"].get("muzzle_height", self.config["mech"].get("muzzle_height", 7))]
        clear = not self.map.ray_blocked(body_muzzle, point) and not self.map.ray_blocked(origin, point)
        fire = [False, False]
        reload = False
        for i, weapon in enumerate(me["weapons"]):
            if not weapon:
                continue
            kind, stats = weapon["kind"], weapon["stats"]
            if kind == "gun":
                reload = weapon.get("ammo", 0) == 0 and weapon.get("reload", 0) <= 0
                fire[i] = bool(clear and aligned and distance <= stats["range"] and weapon.get("ammo", 0) > 0 and weapon.get("reload", 0) <= 0 and weapon.get("cooldown", 0) <= .05)
            elif kind == "lightning":
                # Deliberately narrow alignment prevents wasting shots on a
                # different actor in the lightning cone; no laser/mortar firing.
                fire[i] = bool(clear and aligned and distance <= stats["range"] and me["energy"] >= stats.get("energy", 3) + 15 and weapon.get("cooldown", 0) <= .05)
        return dict(aim=[yaw, pitch], fire=fire, reload=reload), center

    def combat_goal(self, me, target):
        center, _ = self.target_center(target)
        clear = not self.map.ray_blocked(self.muzzle(me), center)
        if not clear:
            return list(target["pos"])
        kind = target.get("kind", "crate")
        ideal = 24 if kind == "crate" else 65 if kind == "npc" else 95
        gun = next((w for w in me["weapons"] if w and w["kind"] == "gun"), None)
        if gun:
            ideal = min(ideal, gun["stats"]["range"] * .75)
        dx, dy = me["pos"][0] - target["pos"][0], me["pos"][1] - target["pos"][1]
        distance = max(.01, math.hypot(dx, dy))
        return [target["pos"][0] + ideal * dx / distance, target["pos"][1] + ideal * dy / distance, me["pos"][2]]

    def exploration_goal(self, obs):
        pos, now = obs["self"]["pos"], obs["t"]
        if self.explore_goal is not None and ("EXPLORE", tuple(self.explore_goal)) not in self.ignored_until and math.dist(pos[:2], self.explore_goal[:2]) > 12 and self.safe_objective(self.explore_goal, obs):
            return self.explore_goal
        self.visited = [(p, t) for p, t in self.visited if now - t < 90]
        self.visited.append((tuple(pos), now))
        options = []
        for k in range(12):
            angle = (k + self.fallback_seed / 2) * math.tau / 12
            node = self.nearest_node((pos[0] + 90 * math.cos(angle), pos[1] + 90 * math.sin(angle)))
            if node is None:
                continue
            p = self.nav[node]
            if not self.safe_objective(p, obs) or ("EXPLORE", tuple(p)) in self.ignored_until:
                continue
            recent = sum(max(0, 55 - math.dist(p[:2], old[:2])) for old, _ in self.visited)
            options.append((recent + self.support_risk(p, obs) * 70, k, p))
        self.explore_goal = min(options)[2] if options else None
        return self.explore_goal

    def choose(self, obs):
        me, now = obs["self"], obs["t"]
        self.hide_unlocked |= me["cubes"] >= 10
        if me["hp"] < me["max_hp"] * .5:
            self.recovering = True
        elif me["hp"] >= me["max_hp"] * .85:
            self.recovering = False
        center, radius = self.forecast(obs["zone"], now, 10)
        if not me["in_zone"] or math.dist(me["pos"][:2], center) + me["stats"].get("radius", 2.5) + 6 >= radius:
            return "ZONE", None, None, None
        if self.recovering:
            return "RECOVER", None, None, None
        self.ignored_until = {k: v for k, v in self.ignored_until.items() if v > now}
        candidates = []
        pickup_radius = self.config["cubes"].get("pickup_radius", 3.5)
        for cube in obs["cubes"]:
            self.cube_memory[cube["id"]] = (dict(cube), now)
        current_ids = {c["id"] for c in obs["cubes"]}
        self.cube_memory = {i: v for i, v in self.cube_memory.items() if now - v[1] < 4 and not (i not in current_ids and math.dist(me["pos"][:2], v[0]["pos"][:2]) <= pickup_radius + 1)}
        for cube, seen in self.cube_memory.values():
            pos = cube["pos"];distance = math.dist(me["pos"], pos)
            if not self.reachable_surface(pos, me) or not self.safe_objective(pos, obs) or self.support_risk(pos, obs) >= 2:
                continue
            if self.hide_unlocked and distance > 110:
                continue
            candidates.append((distance * .7 - 80, "LOOT", cube["id"], pos, None))
        if self.loot_interest is not None:
            pos, until = self.loot_interest
            if now >= until or math.dist(me["pos"], pos) <= pickup_radius:
                self.loot_interest = None
            elif self.safe_objective(pos, obs) and self.support_risk(pos, obs) < 2:
                candidates.append((math.dist(me["pos"], pos) * .7 - 60, "LOOT", "kill-loot", pos, None))
        for enemy in obs["mechs"]:
            if not self.weaker(me, enemy) or not self.safe_objective(enemy["pos"], obs) or self.support_risk(enemy["pos"], obs, enemy["id"]) >= 2:
                continue
            distance = math.dist(me["pos"], enemy["pos"])
            if self.hide_unlocked and distance > (90 if enemy["kind"] == "npc" else 150):
                continue
            if not self.reachable_surface(enemy["pos"], me):
                continue
            value = 40 if enemy["kind"] == "npc" else 15 + min(10, enemy.get("cubes", 0)) * 5
            stickiness = 20 if enemy["id"] == self.active_target else 0
            candidates.append((distance + enemy["hp"] * .035 - value - stickiness, "AMBUSH" if self.hide_unlocked else "HUNT", enemy["id"], list(enemy["pos"]), dict(enemy)))
        if not self.hide_unlocked:
            for crate in obs["crates"]:
                if not self.reachable_surface(crate["pos"], me) or not self.safe_objective(crate["pos"], obs) or self.support_risk(crate["pos"], obs) >= 2:
                    continue
                target = dict(crate, kind="crate")
                candidates.append((math.dist(me["pos"], crate["pos"]) + 5, "FARM", crate["id"], list(crate["pos"]), target))
        candidates = [c for c in candidates if (c[1], c[2]) not in self.ignored_until]
        if candidates:
            _, mode, ident, goal, target = min(candidates, key=lambda c: c[0])
            return mode, (mode, ident), self.combat_goal(me, target) if target else goal, target
        if self.hide_unlocked:
            return "HIDE", None, None, None
        goal = self.exploration_goal(obs)
        return "EXPLORE", ("EXPLORE", tuple(goal)) if goal is not None else None, goal, None

    def act(self, obs: mf.Observation) -> mf.Action:
        now, me = obs["t"], obs["self"]
        if self.last_victim:
            self.actor_memory.setdefault(self.last_victim["id"], (self.last_victim, now))
        kills = {e["target"] for e in obs["events"] if e["type"] == "kill"}
        hits = {}
        for event in obs["events"]:
            if event["type"] == "hit":
                hits[event["target"]] = hits.get(event["target"], 0) + event.get("amount", 0)
        spots = []
        for ident, (victim, seen) in self.actor_memory.items():
            destroyed_crate = victim.get("kind") == "crate" and hits.get(ident, 0) >= victim.get("hp", float("inf"))
            if ident in kills or destroyed_crate:
                spots.append(list(victim["pos"]))
                self.memory.pop(ident, None)
        if spots:
            self.loot_interest = (min(spots, key=lambda p: math.dist(me["pos"], p)), now + 12)
        self.actor_memory = {i: v for i, v in self.actor_memory.items() if now-v[1] < 12 and i not in kills}
        for actor in obs["mechs"] + [dict(c, kind="crate") for c in obs["crates"]]:
            if actor.get("hp", 1) > 0:
                self.actor_memory[actor["id"]] = (dict(actor), now)
        self.recent_attackers = {i: until for i, until in self.recent_attackers.items() if until > now and i not in kills}
        for event in obs["events"]:
            if event["type"] == "damaged" and event.get("by") is not None and event.get("weapon") != "zone":
                self.recent_attackers[event["by"]] = now + 3.0
        mode, key, goal, target = self.choose(obs)
        pursuers = [e for e in obs["mechs"] if e["id"] in self.recent_attackers and e.get("hp", 1) > 0]
        attacker = min(pursuers, key=lambda e: math.dist(me["pos"], e["pos"])) if pursuers else None
        defensive = attacker is not None and (target is None or target["id"] != attacker["id"])
        if defensive:
            # Fight back without treating a stronger pursuer as prey. Keeping it
            # in the navigation observation preserves retreat/cover behavior.
            mode = mode + "/DEFEND" if mode in ("ZONE", "RECOVER") else "DEFEND"
            key, goal, target = None, None, dict(attacker)
        if key is not None and self.watch and self.watch[0] == key:
            _, pos, since, hp = self.watch
            damaging = target is not None and hp is not None and target.get("hp", hp) < hp - 1
            if math.dist(me["pos"], pos) > 3 or damaging:
                self.watch = (key, list(me["pos"]), now, target.get("hp") if target else None)
            elif now - since > 8:
                self.ignored_until[key] = now + 15
                self.explore_goal = None
                mode, key, goal, target = self.choose(obs)
        else:
            self.watch = (key, list(me["pos"]), now, target.get("hp") if target else None) if key else None
        self.mode, self.mission_key, self.mission_goal = mode, key, goal
        self.active_target = target["id"] if target else None
        nav_obs = dict(obs)
        if target and not defensive:
            # Approach our chosen prey; still avoid every other known actor.
            nav_obs["mechs"] = [e for e in obs["mechs"] if e["id"] != target["id"]]
            self.memory.pop(target["id"], None)
        action = super().act(nav_obs)
        if target:
            fight, aim_point = self.firing_action(me, target)
            action.update(fight)
            self.last_victim = dict(target)
            mf.draw.line(self.muzzle(me), aim_point, "#ff7040")
        else:
            self.last_victim = None
            for weapon in me["weapons"]:
                if weapon and weapon["kind"] == "gun" and weapon.get("ammo", 0) < weapon["stats"].get("mag", 12) and weapon.get("reload", 0) <= 0:
                    action["reload"] = True
        # A close lightning pickup is useful without risking mortar cook-off or
        # slowing movement to charge a laser. Keep the starter gun.
        if any(w is None for w in me["weapons"]) and not any(w and w["kind"] == "lightning" for w in me["weapons"]):
            near = [p for p in obs["pickups"] if p["kind"] == "lightning" and math.dist(me["pos"][:2], p["pos"][:2]) <= self.config["loot"]["pickup_radius"] and abs(me["pos"][2] - p["pos"][2]) <= 4]
            if near:
                action["take"] = min(near, key=lambda p: math.dist(me["pos"], p["pos"]))["id"]
        if obs.get("offer"):
            priority = (["armor", "nanites", "plating", "servos", "reactor", "gun_damage", "gun_rate", "gun_mag", "capacitor", "sensors", "jets", "gyros"] if self.hide_unlocked else ["gun_damage", "gun_rate", "gun_mag", "armor", "plating", "nanites", "servos", "reactor", "capacitor", "sensors", "jets", "gyros"])
            action["pick"] = min(range(len(obs["offer"]["choices"])), key=lambda i: priority.index(obs["offer"]["choices"][i]["id"]) if obs["offer"]["choices"][i]["id"] in priority else 99)
        mf.draw.label(f"{mode} cubes={me['cubes']}/10 hp={me['hp']:.0f} target={self.active_target}")
        if goal is not None:
            mf.draw.point(list(goal), "#40c0ff", 5)
            mf.draw.line(list(me["pos"]), list(goal), "#40c0ff")
        return action


if __name__ == "__main__":
    mf.run(Bot)
