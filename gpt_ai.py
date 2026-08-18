"""kimi_ai.py -- Independent Kimi AI for the 5v5 Pygame soccer game.

Kimi is deliberately implemented as a separate decision system.  It does not
reuse the decision helpers, state machines, heuristics, or role implementations
from deepseek_ai.py or claude_ai.py.  It only consumes the BaseAI interface and registers
four Kimi role variants so they can be mixed with the existing AIs.

Kimi's philosophy is SPACE + THREAT + OPTIONS:
    1. Build a compact world model from ball velocity, possession, space and
       opponent pressure.
    2. Generate several candidate actions for the player's assigned role.
    3. Score those actions with a utility model.
    4. Choose the best action, with small hysteresis so the player does not
       oscillate between targets every frame.

Roles: goalkeeper, two defenders, playmaker, striker.
"""

import math

from deepseek_ai import BaseAI, AI_REGISTRY

WIDTH = 1912
HEIGHT = 1045
GOAL_WIDTH = 40
GOAL_HEIGHT = 250
MAX_KICK_POWER = 20
BALL_RADIUS = 12

CENTER_X = WIDTH * 0.5
CENTER_Y = HEIGHT * 0.5
BOX_DEPTH = 250
BOX_HALF_H = 200

ROLE_GOALKEEPER = "goalkeeper"
ROLE_DEFENDER = "defender"
ROLE_PLAYMAKER = "playmaker"
ROLE_STRIKER = "striker"

ACTIONS = (
    "move",
    "chase_ball",
    "support",
    "pass",
    "shoot",
    "dribble",
    "press",
    "mark",
    "intercept",
    "clear",
    "hold_position",
)


def _distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _unit(dx, dy):
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return 1.0, 0.0
    return dx / d, dy / d


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _move_keys(px, py, tx, ty):
    dx, dy = tx - px, ty - py
    if abs(dx) < 3 and abs(dy) < 3:
        return False, False, False, False
    # Kimi intentionally quantizes the continuous target into the game's
    # digital movement API rather than borrowing deepseek_ai.py's movement helper.
    if abs(dx) >= abs(dy):
        return dy < -12, dy > 12, dx < 0, dx > 0
    return dy < 0, dy > 0, dx < -12, dx > 12


def _team_has_ball(player, teammates, opponents):
    if player.holding_ball:
        return True, player
    for p in teammates:
        if p.holding_ball:
            return True, p
    for p in opponents:
        if p.holding_ball:
            return False, p
    return None, None


def _goal(attacking_right):
    return (WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH, CENTER_Y)


def _own_goal(attacking_right):
    return (GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH, CENTER_Y)


def _forward_sign(attacking_right):
    return 1 if attacking_right else -1


def _in_own_box(x, y, attacking_right):
    if attacking_right:
        return x <= BOX_DEPTH and CENTER_Y - BOX_HALF_H <= y <= CENTER_Y + BOX_HALF_H
    return x >= WIDTH - BOX_DEPTH and CENTER_Y - BOX_HALF_H <= y <= CENTER_Y + BOX_HALF_H


def _forward_progress(x, attacking_right):
    return x if attacking_right else WIDTH - x


def _nearest(point, players):
    best = None
    best_d = float("inf")
    for p in players:
        d = _distance(point, (p.x, p.y))
        if d < best_d:
            best, best_d = p, d
    return best, best_d


def _open_space(point, teammates, opponents, radius=180):
    """Estimate how free a point is. Higher means safer/more useful space."""
    score = 1.0
    for p in opponents:
        d = _distance(point, (p.x, p.y))
        score += min(2.0, d / radius)
    for p in teammates:
        if d := _distance(point, (p.x, p.y)):
            if d < radius:
                score -= (radius - d) / radius * 0.8
    return score


def _lane_clear(a, b, opponents, clearance=55):
    ax, ay = a
    bx, by = b
    abx, aby = bx - ax, by - ay
    denom = abx * abx + aby * aby
    if denom < 1e-6:
        return True
    for o in opponents:
        t = ((o.x - ax) * abx + (o.y - ay) * aby) / denom
        t = _clamp(t, 0.0, 1.0)
        qx, qy = ax + abx * t, ay + aby * t
        if math.hypot(o.x - qx, o.y - qy) < clearance + getattr(o, "radius", 20):
            return False
    return True


def _predicted_ball(ball_x, ball_y, ball_vx, ball_vy, frames=7):
    # Include a little braking because the game applies friction each frame.
    decay = sum(0.98 ** i for i in range(frames))
    return ball_x + ball_vx * decay, ball_y + ball_vy * decay


def _danger_score(point, attacking_right, opponents):
    goal = _own_goal(attacking_right)
    dist_goal = _distance(point, goal)
    nearest, nearest_d = _nearest(point, opponents)
    threat = max(0.0, 1.0 - dist_goal / 900.0)
    pressure = max(0.0, 1.0 - nearest_d / 260.0)
    return threat * 0.65 + pressure * 0.35


def _opponent_with_ball(opponents):
    for p in opponents:
        if p.holding_ball:
            return p
    return None


class KimiAI(BaseAI):
    """Independent utility-based AI with four soccer roles."""

    def __init__(self, role):
        self.role = role
        self.name = {
            ROLE_GOALKEEPER: "Kimi GK",
            ROLE_DEFENDER: "Kimi DEF",
            ROLE_PLAYMAKER: "Kimi PM",
            ROLE_STRIKER: "Kimi STR",
        }[role]
        self._last_action = None
        self._target = None
        self._target_age = 0
        self._kick_target = 0

    def reset(self):
        self._last_action = None
        self._target = None
        self._target_age = 0
        self._kick_target = 0

    def _team_shape(self, player, teammates, attacking_right):
        """Return a moving team reference point, independent of player role."""
        outfield = [p for p in teammates if p is not player]
        if not outfield:
            return CENTER_X, CENTER_Y
        mean_x = sum(p.x for p in outfield) / len(outfield)
        mean_y = sum(p.y for p in outfield) / len(outfield)
        # The shape follows the ball, but less than one-to-one, keeping a spine.
        return (
            mean_x * 0.65 + CENTER_X * 0.20 + (CENTER_X + (WIDTH * 0.18) * _forward_sign(attacking_right)) * 0.15,
            mean_y * 0.55 + CENTER_Y * 0.45,
        )

    def _candidate_targets(self, player, ball, holder, teammates, opponents, attacking_right):
        bx, by, bvx, bvy = ball
        fx = _forward_sign(attacking_right)
        goal = _goal(attacking_right)
        own_goal = _own_goal(attacking_right)
        pred = _predicted_ball(bx, by, bvx, bvy, 8)
        shape_x, shape_y = self._team_shape(player, teammates, attacking_right)

        targets = {}
        targets["move"] = (shape_x + fx * 100, shape_y)
        targets["chase_ball"] = pred
        targets["support"] = (bx + fx * 150, by + (player.y - by) * 0.25)
        targets["press"] = (pred[0] - fx * 10, pred[1])
        targets["intercept"] = (pred[0], pred[1])
        targets["hold_position"] = (shape_x, shape_y)
        targets["mark"] = (shape_x - fx * 70, shape_y)
        targets["dribble"] = (player.x + fx * 180, player.y + (CENTER_Y - player.y) * 0.15)
        targets["clear"] = (CENTER_X + fx * 250, CENTER_Y + (by - CENTER_Y) * 0.5)

        if holder is not None and holder in teammates:
            # Occupy a different lane from the current carrier.
            side = -1 if player.y > holder.y else 1
            targets["support"] = (
                _clamp(holder.x + fx * 150, 100, WIDTH - 100),
                _clamp(holder.y + side * 170, 70, HEIGHT - 70),
            )

        if holder is not None and holder in opponents:
            targets["press"] = (
                holder.x - fx * 45,
                holder.y,
            )

        # Role-specific geometry.
        if self.role == ROLE_GOALKEEPER:
            # A keeper moves on a predicted threat ray, not toward the ball itself.
            gx, gy = own_goal
            vx, vy = pred[0] - gx, pred[1] - gy
            nx, ny = _unit(vx, vy)
            reach = _clamp(math.hypot(vx, vy) * 0.22, 18, 105)
            targets["hold_position"] = (
                gx + nx * reach,
                _clamp(gy + ny * reach, CENTER_Y - BOX_HALF_H + 25, CENTER_Y + BOX_HALF_H - 25),
            )
            targets["intercept"] = (
                _clamp(pred[0], 20, BOX_DEPTH - 15) if attacking_right else _clamp(pred[0], WIDTH - BOX_DEPTH + 15, WIDTH - 20),
                _clamp(pred[1], CENTER_Y - BOX_HALF_H + 20, CENTER_Y + BOX_HALF_H - 20),
            )
            targets["clear"] = (gx + fx * 190, CENTER_Y + (by - CENTER_Y) * 0.7)

        elif self.role == ROLE_DEFENDER:
            # Defenders live between the ball and goal.  The two defenders get
            # different lateral cover points from their current vertical ordering.
            mates_def = [t for t in teammates if getattr(t.ai, "role", None) == ROLE_DEFENDER]
            rank = 0
            for d in sorted(mates_def, key=lambda q: q.y):
                if d is player:
                    rank = len(mates_def) - 1
                    break
                if d.y < player.y:
                    rank += 1
            lateral = -95 if rank == 0 else 95
            line_x = own_goal[0] + fx * 250
            targets["hold_position"] = (_clamp(line_x, 120, WIDTH - 120), CENTER_Y + lateral)
            targets["mark"] = (shape_x - fx * 120, shape_y + lateral * 0.45)
            targets["intercept"] = (pred[0] * 0.55 + own_goal[0] * 0.45, pred[1] * 0.65 + own_goal[1] * 0.35)

        elif self.role == ROLE_PLAYMAKER:
            # The playmaker seeks a free vertex of a triangle rather than the ball.
            side = -1 if player.y < CENTER_Y else 1
            targets["move"] = (
                _clamp(bx + fx * 180, 120, WIDTH - 120),
                _clamp(by + side * 190, 80, HEIGHT - 80),
            )
            targets["support"] = (
                _clamp(bx + fx * 130, 100, WIDTH - 100),
                _clamp(by - side * 140, 70, HEIGHT - 70),
            )

        elif self.role == ROLE_STRIKER:
            # The striker attacks a corridor behind the nearest defender.
            defenders = sorted(opponents, key=lambda o: _forward_progress(o.x, attacking_right))
            lead = defenders[-1] if defenders else None
            run_y = by + (player.y - by) * 0.35
            run_x = bx + fx * 240
            if lead is not None:
                run_x = lead.x + fx * 115
                run_y = lead.y + (CENTER_Y - lead.y) * 0.15
            targets["move"] = (_clamp(run_x, 80, WIDTH - 80), _clamp(run_y, 60, HEIGHT - 60))
            targets["support"] = (_clamp(bx + fx * 120, 80, WIDTH - 80), _clamp(by + (CENTER_Y - by) * 0.5, 60, HEIGHT - 60))

        return targets, goal, own_goal, pred

    def _utility(self, action, player, ball, holder, teammates, opponents, attacking_right, targets, goal, own_goal, pred):
        bx, by, bvx, bvy = ball
        fx = _forward_sign(attacking_right)
        pos = (player.x, player.y)
        target = targets.get(action, pos)
        dist_target = _distance(pos, target)
        nearest_opp, opp_dist = _nearest(pos, opponents)
        nearest_mate, mate_dist = _nearest(pos, [t for t in teammates if t is not player])
        space = _open_space(target, teammates, opponents)
        danger = _danger_score(pos, attacking_right, opponents)
        carrying = player.holding_ball
        teammate_has = holder is not None and holder in teammates
        opponent_has = holder is not None and holder in opponents
        forward = _forward_progress(player.x, attacking_right) / WIDTH
        goal_dist = _distance(pos, goal)
        goal_angle = 1.0 - min(1.0, abs(player.y - goal[1]) / 500.0)
        pred_dist = _distance(pos, pred)
        half_attacking = _forward_progress(player.x, attacking_right) > WIDTH * 0.5
        score = 0.0

        if action == "hold_position":
            score = 90 + space * 12 - min(70, dist_target * 0.12)
        elif action == "move":
            score = 45 + space * 15 - dist_target * 0.10 + forward * 25
        elif action == "chase_ball":
            score = 55 + (1 if not teammate_has and not opponent_has else 0) * 35 - pred_dist * 0.20
            if self.role == ROLE_GOALKEEPER and not _in_own_box(target[0], target[1], attacking_right):
                score -= 250
        elif action == "support":
            score = 70 + space * 22 - dist_target * 0.11
            if teammate_has:
                score += 80
        elif action == "press":
            score = 40 + (180 - min(180, opp_dist)) * 0.7
            if opponent_has:
                score += 150
            if self.role == ROLE_DEFENDER and _forward_progress(player.x, attacking_right) < WIDTH * 0.28:
                score -= 40
        elif action == "mark":
            score = 65 + danger * 110 + space * 8 - dist_target * 0.08
            if self.role == ROLE_DEFENDER:
                score += 60
        elif action == "intercept":
            score = 55 + max(0, 180 - pred_dist) * 0.8 + danger * 100
            if self.role == ROLE_GOALKEEPER and _in_own_box(pred[0], pred[1], attacking_right):
                score += 180
            if self.role == ROLE_DEFENDER:
                score += 90
        elif action == "dribble":
            score = 40 + forward * 85 + space * 20 - max(0, 130 - opp_dist) * 0.6
            if not carrying:
                score -= 250
        elif action == "pass":
            if not carrying:
                return -9999.0
            options = []
            for t in teammates:
                if t is player or t.holding_ball:
                    continue
                td = _distance(pos, (t.x, t.y))
                if td > 700:
                    continue
                lane = _lane_clear(pos, (t.x, t.y), opponents)
                tspace = _open_space((t.x, t.y), teammates, opponents)
                progress = (_forward_progress(t.x, attacking_right) - _forward_progress(player.x, attacking_right)) / WIDTH
                quality = 35 + tspace * 35 + progress * 120 - td * 0.10
                if lane:
                    quality += 70
                else:
                    quality -= 130
                options.append(quality)
            score = max(options, default=-500) + 70
            if self.role == ROLE_PLAYMAKER:
                score += 55
            if self.role == ROLE_GOALKEEPER:
                score += 30
        elif action == "shoot":
            if not carrying:
                return -9999.0
            clear = _lane_clear(pos, goal, opponents, clearance=45)
            score = 25 + (1.0 - min(1.0, goal_dist / 1300.0)) * 240 + goal_angle * 100
            score += min(120, opp_dist * 0.6)
            if clear:
                score += 100
            else:
                score -= 170
            if half_attacking:
                score += 120
            if self.role == ROLE_STRIKER:
                score += 90
            if self.role == ROLE_PLAYMAKER:
                score += 25
        elif action == "clear":
            if not carrying:
                return -9999.0
            score = 20 + danger * 260
            if self.role == ROLE_GOALKEEPER:
                score += 180
            if self.role == ROLE_DEFENDER:
                score += 80
            if opponent_has:
                score += 100
        return score

    def _choose(self, player, ball, holder, teammates, opponents, attacking_right, targets, goal, own_goal, pred):
        scores = {}
        for action in ACTIONS:
            scores[action] = self._utility(
                action, player, ball, holder, teammates, opponents,
                attacking_right, targets, goal, own_goal, pred,
            )

        # Hysteresis is part of Kimi's decision philosophy: changing plans has
        # a small cost, but a genuinely better action can still replace it.
        if self._last_action in scores:
            scores[self._last_action] += 18

        # Explicit role constraints keep the utility system sensible.
        if self.role == ROLE_GOALKEEPER:
            for a in ("dribble", "chase_ball", "press"):
                scores[a] -= 160
            scores["hold_position"] += 80
        elif self.role == ROLE_DEFENDER:
            scores["mark"] += 50
            scores["intercept"] += 45
            scores["shoot"] -= 40
        elif self.role == ROLE_PLAYMAKER:
            scores["support"] += 35
            scores["pass"] += 35
        elif self.role == ROLE_STRIKER:
            scores["move"] += 45
            scores["shoot"] += 45
            scores["press"] += 25

        action = max(scores, key=scores.get)
        self._last_action = action
        return action, scores

    def _kick_plan(self, player, action, teammates, opponents, goal, attacking_right):
        """Select a target for pass/shot/clear. Returns (face, power)."""
        px, py = player.x, player.y
        if action == "shoot":
            # Pick the safer of two goal lanes rather than always the centre.
            candidates = [
                (goal[0], goal[1] - GOAL_HEIGHT * 0.30),
                (goal[0], goal[1] + GOAL_HEIGHT * 0.30),
                goal,
            ]
            candidates.sort(key=lambda q: 0 if _lane_clear((px, py), q, opponents, 40) else 1)
            target = candidates[0]
            return _unit(target[0] - px, target[1] - py), MAX_KICK_POWER

        if action == "pass":
            best = None
            best_score = -1e9
            for t in teammates:
                if t is player or t.holding_ball:
                    continue
                lane = _lane_clear((px, py), (t.x, t.y), opponents)
                progress = _forward_progress(t.x, attacking_right) - _forward_progress(px, attacking_right)
                space = _open_space((t.x, t.y), teammates, opponents)
                score = space * 30 + progress * 0.35 - _distance((px, py), (t.x, t.y)) * 0.08
                score += 90 if lane else -160
                if score > best_score:
                    best_score, best = score, t
            if best is not None:
                power = _clamp(_distance((px, py), (best.x, best.y)) / 25, 7, MAX_KICK_POWER - 2)
                return _unit(best.x - px, best.y - py), power

        if action == "clear":
            fx = _forward_sign(attacking_right)
            # Prefer the less crowded side of the pitch.
            upper = sum(1 for o in opponents if o.y < CENTER_Y)
            lower = len(opponents) - upper
            side = 1 if upper < lower else -1
            target = (px + fx * 500, _clamp(py + side * 300, 50, HEIGHT - 50))
            return _unit(target[0] - px, target[1] - py), MAX_KICK_POWER

        return None, 0

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        ball = (ball_x, ball_y, ball_vx, ball_vy)
        state, holder = _team_has_ball(player, teammates, opponents)
        targets, goal, own_goal, pred = self._candidate_targets(
            player, ball, holder, teammates, opponents, attacking_right,
        )

        action, _scores = self._choose(
            player, ball, holder, teammates, opponents,
            attacking_right, targets, goal, own_goal, pred,
        )

        target = targets.get(action, (player.x, player.y))
        self._target = target
        self._target_age += 1
        if self._target_age > 18:
            self._target_age = 0

        # If the selected action is a kick, facing and power are set directly.
        # The game loop then performs its normal charge/release mechanics.
        kick = False
        face = _unit(target[0] - player.x, target[1] - player.y)
        if action in ("pass", "shoot", "clear") and player.holding_ball and player.kick_cooldown == 0:
            planned_face, power = self._kick_plan(
                player, action, teammates, opponents, goal, attacking_right,
            )
            if planned_face is not None:
                face = planned_face
                player.kick_power = power

        # Face the ball while defending; face the goal while making an attacking run.
        if action in ("press", "mark", "intercept", "chase_ball"):
            face = _unit(ball_x - player.x, ball_y - player.y)
        elif action == "shoot":
            face = face

        up, down, left, right = _move_keys(player.x, player.y, target[0], target[1])
        sprint = action not in ("hold_position", "mark") or self.role == ROLE_STRIKER

        # Goalkeeper never deliberately leaves its box unless intercepting a ball
        # that is already inside it.
        if self.role == ROLE_GOALKEEPER and action != "intercept":
            tx, ty = target
            if not _in_own_box(tx, ty, attacking_right):
                tx = _clamp(tx, 25, BOX_DEPTH - 15) if attacking_right else _clamp(tx, WIDTH - BOX_DEPTH + 15, WIDTH - 25)
                ty = _clamp(ty, CENTER_Y - BOX_HALF_H + 20, CENTER_Y + BOX_HALF_H - 20)
                up, down, left, right = _move_keys(player.x, player.y, tx, ty)

        return {
            "up": up,
            "down": down,
            "left": left,
            "right": right,
            "sprint": sprint,
            "kick": kick,
            "face": face,
        }


class KimiGoalkeeperAI(KimiAI):
    def __init__(self):
        super().__init__(ROLE_GOALKEEPER)


class KimiDefenderAI(KimiAI):
    def __init__(self):
        super().__init__(ROLE_DEFENDER)


class KimiPlaymakerAI(KimiAI):
    def __init__(self):
        super().__init__(ROLE_PLAYMAKER)


class KimiStrikerAI(KimiAI):
    def __init__(self):
        super().__init__(ROLE_STRIKER)


# Independent registry entries.  Each player receives its own KimiAI object.
# Concrete classes keep create_ai()/cycle_ai() compatible with deepseek_ai.py.
AI_REGISTRY["kimi_gk"] = KimiGoalkeeperAI
AI_REGISTRY["kimi_def"] = KimiDefenderAI
AI_REGISTRY["kimi_pm"] = KimiPlaymakerAI
AI_REGISTRY["kimi_str"] = KimiStrikerAI
