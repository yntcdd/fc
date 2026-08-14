"""gemini_ai.py — High-Aggression Independent 5v5 Soccer AI System for Pygame.

Architecture Overview:
----------------------
GeminiAI is an independently designed, multi-agent tactical AI based on a
High-Intensity Predictive Potential Field & Aggressive Action Utility Matrix.

It does NOT use or adapt the decision trees, state machines, or heuristics
from ai.py or custom_ai.py. It only consumes the shared BaseAI interface and
registers four specialized role variants into AI_REGISTRY:

    1. "gemini_gk"   -> GeminiGoalkeeperAI (Cone-bisecting, sweep-and-distribute)
    2. "gemini_def"  -> GeminiDefenderAI   (Aggressive Challenger/Cover pair, direct exits)
    3. "gemini_pm"   -> GeminiPlaymakerAI  (Long-range sniper, progressive dribbler)
    4. "gemini_str"  -> GeminiStrikerAI    (Shoot-on-sight, high press, direct box attacks)

Core Aggression Enhancements:
-----------------------------
- Shoot-on-sight philosophy: Strikers and Playmakers unleash powerful strikes from up to 700px.
- Direct goal-driving: Ball carriers sprint directly toward the box rather than overpassing.
- High-intensity pressing: Aggressive closing down of opponent defenders and goalkeeper.
- Power strikes: Shot power calibrated to 17.0–20.0 for maximum goal conversion.
"""

import math
import random
from ai import BaseAI, AI_REGISTRY

# ── Field & Game Constants ───────────────────────────────────────────────────
WIDTH = 1912
HEIGHT = 1045
GOAL_WIDTH = 40
GOAL_HEIGHT = 250
MAX_KICK_POWER = 20
BALL_RADIUS = 12
PLAYER_RADIUS = 20
BALL_FRICTION = 0.98
KICK_COOLDOWN_TIME = 20

CENTER_X = WIDTH * 0.5
CENTER_Y = HEIGHT * 0.5
BOX_DEPTH = 250
BOX_HALF_H = 200

BASE_SPEED = 5.0
SPRINT_SPEED = 7.0

ROLE_GK = "goalkeeper"
ROLE_DEF = "defender"
ROLE_PM = "playmaker"
ROLE_STR = "striker"


# =============================================================================
# 1. 2D Vector & Geometric Utilities
# =============================================================================

def _vec_dist(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def _vec_len(v):
    return math.hypot(v[0], v[1])


def _vec_norm(v):
    d = math.hypot(v[0], v[1])
    if d < 1e-6:
        return 1.0, 0.0
    return v[0] / d, v[1] / d


def _vec_dot(v1, v2):
    return v1[0] * v2[0] + v1[1] * v2[1]


def _vec_sub(p1, p2):
    return p1[0] - p2[0], p1[1] - p2[1]


def _vec_add(p1, p2):
    return p1[0] + p2[0], p1[1] + p2[1]


def _vec_scale(v, s):
    return v[0] * s, v[1] * s


def _clamp(val, low, high):
    return max(low, min(high, val))


def _point_segment_dist(pt, seg_a, seg_b):
    """Compute shortest distance from pt to line segment [seg_a, seg_b]."""
    ab_x = seg_b[0] - seg_a[0]
    ab_y = seg_b[1] - seg_a[1]
    ab_len_sq = ab_x * ab_x + ab_y * ab_y
    if ab_len_sq < 1e-6:
        return _vec_dist(pt, seg_a)
    ap_x = pt[0] - seg_a[0]
    ap_y = pt[1] - seg_a[1]
    t = (ap_x * ab_x + ap_y * ab_y) / ab_len_sq
    t = max(0.0, min(1.0, t))
    closest = (seg_a[0] + t * ab_x, seg_a[1] + t * ab_y)
    return _vec_dist(pt, closest)


def _goal_center(attacking_right):
    return (WIDTH - GOAL_WIDTH, CENTER_Y) if attacking_right else (GOAL_WIDTH, CENTER_Y)


def _own_goal_center(attacking_right):
    return (GOAL_WIDTH, CENTER_Y) if attacking_right else (WIDTH - GOAL_WIDTH, CENTER_Y)


def _own_box_bounds(attacking_right):
    if attacking_right:
        return 0.0, float(BOX_DEPTH), CENTER_Y - BOX_HALF_H, CENTER_Y + BOX_HALF_H
    else:
        return float(WIDTH - BOX_DEPTH), float(WIDTH), CENTER_Y - BOX_HALF_H, CENTER_Y + BOX_HALF_H


def _in_own_box(x, y, attacking_right):
    l, r, t, b = _own_box_bounds(attacking_right)
    return l <= x <= r and t <= y <= b


def _clamp_in_own_box(x, y, attacking_right, margin=20.0):
    l, r, t, b = _own_box_bounds(attacking_right)
    return (_clamp(x, l + margin, r - margin),
            _clamp(y, t + margin, b - margin))


def _quantize_movement(px, py, tx, ty, deadzone=3.0):
    """Convert continuous target (tx, ty) into discrete up/down/left/right signals."""
    dx = tx - px
    dy = ty - py
    dist = math.hypot(dx, dy)
    if dist < deadzone:
        return False, False, False, False

    ux = dx / dist
    uy = dy / dist

    # 8-way directional thresholding
    right = ux > 0.38
    left = ux < -0.38
    down = uy > 0.38
    up = uy < -0.38

    return up, down, left, right


# =============================================================================
# 2. Predictive Physics & Interception Engine
# =============================================================================

def _simulate_ball_trajectory(bx, by, bvx, bvy, max_steps=50):
    """Predict future ball positions taking into account friction and wall bounces."""
    traj = [(bx, by, bvx, bvy)]
    cx, cy = bx, by
    cvx, cvy = bvx, bvy

    for _ in range(max_steps):
        if abs(cvx) < 0.05 and abs(cvy) < 0.05:
            traj.append((cx, cy, 0.0, 0.0))
            continue

        cx += cvx
        cy += cvy
        cvx *= BALL_FRICTION
        cvy *= BALL_FRICTION

        # Boundary checks & bounces
        in_goal_y = abs(cy - CENTER_Y) < GOAL_HEIGHT * 0.5

        if cy <= BALL_RADIUS:
            cy = BALL_RADIUS
            cvy = -cvy
        elif cy >= HEIGHT - BALL_RADIUS:
            cy = HEIGHT - BALL_RADIUS
            cvy = -cvy

        if cx <= BALL_RADIUS and not in_goal_y:
            cx = BALL_RADIUS
            cvx = -cvx
        elif cx >= WIDTH - BALL_RADIUS and not in_goal_y:
            cx = WIDTH - BALL_RADIUS
            cvx = -cvx

        traj.append((cx, cy, cvx, cvy))

    return traj


def _find_interception(player_pos, player_speed, trajectory, min_frame=0):
    """Find the earliest future frame index and position where a player can intercept."""
    px, py = player_pos
    reach_margin = PLAYER_RADIUS + BALL_RADIUS + 4

    for t in range(min_frame, len(trajectory)):
        bx, by, _, _ = trajectory[t]
        d = math.hypot(bx - px, by - py)
        max_reach = player_speed * t + reach_margin
        if d <= max_reach:
            return t, (bx, by)

    # Fallback to the rest position of the ball
    last_bx, last_by, _, _ = trajectory[-1]
    return len(trajectory), (last_bx, last_by)


def _analyze_possession_and_arrival(player, teammates, opponents, trajectory):
    """Analyze who arrives at the ball first across both teams."""
    all_players = [player] + list(teammates) + list(opponents)
    for p in all_players:
        if getattr(p, "holding_ball", False):
            is_our_team = (p is player or p in teammates)
            return {
                "holder": p,
                "team_has_ball": is_our_team,
                "my_arrival_t": 0 if p is player else 999,
                "teammate_arrival_t": 0 if is_our_team and p is not player else 999,
                "opponent_arrival_t": 0 if not is_our_team else 999,
                "closest_arrival_teammate": p if is_our_team else None,
                "closest_arrival_opponent": p if not is_our_team else None,
            }

    my_t, _ = _find_interception((player.x, player.y), SPRINT_SPEED, trajectory)

    best_tm_t = 999
    best_tm = None
    for tm in teammates:
        if getattr(tm, "stunned", 0) > 0:
            continue
        spd = SPRINT_SPEED if not getattr(tm, "holding_ball", False) else SPRINT_SPEED * 0.8
        t, _ = _find_interception((tm.x, tm.y), spd, trajectory)
        if t < best_tm_t:
            best_tm_t = t
            best_tm = tm

    best_opp_t = 999
    best_opp = None
    for opp in opponents:
        if getattr(opp, "stunned", 0) > 0:
            continue
        spd = SPRINT_SPEED if not getattr(opp, "holding_ball", False) else SPRINT_SPEED * 0.8
        t, _ = _find_interception((opp.x, opp.y), spd, trajectory)
        if t < best_opp_t:
            best_opp_t = t
            best_opp = opp

    team_has_ball = (min(my_t, best_tm_t) < best_opp_t - 2)

    return {
        "holder": None,
        "team_has_ball": team_has_ball,
        "my_arrival_t": my_t,
        "teammate_arrival_t": best_tm_t,
        "opponent_arrival_t": best_opp_t,
        "closest_arrival_teammate": best_tm,
        "closest_arrival_opponent": best_opp,
    }


# =============================================================================
# 3. Spatial Potential Fields & Aggressive Shot/Pass Evaluator
# =============================================================================

def _opponent_density_at(x, y, opponents, radius=260.0):
    """Calculate opponent pressure density around coordinate (x, y)."""
    density = 0.0
    for opp in opponents:
        d = math.hypot(x - opp.x, y - opp.y)
        if d < radius:
            density += (1.0 - (d / radius)) ** 2
    return density


def _evaluate_passing_lane(origin, target, opponents, margin=32.0):
    """Return clearance score [0.0 - 1.0] and the most dangerous interceptor."""
    lane_len = _vec_dist(origin, target)
    if lane_len < 10.0:
        return 1.0, None

    worst_clearance = 1.0
    dangerous_opp = None

    for opp in opponents:
        if getattr(opp, "stunned", 0) > 0:
            continue
        d = _point_segment_dist((opp.x, opp.y), origin, target)
        if d < margin:
            clearance = max(0.0, d / margin)
            if clearance < worst_clearance:
                worst_clearance = clearance
                dangerous_opp = opp

    return worst_clearance, dangerous_opp


def _evaluate_shot(shooter_pos, opponents, attacking_right):
    """Aggressive shot evaluation aiming for lethal corner strikes."""
    gx = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
    top_post = (gx, CENTER_Y - 100.0)
    bot_post = (gx, CENTER_Y + 100.0)
    mid_goal = (gx, CENTER_Y)

    targets = [top_post, bot_post, mid_goal]
    best_target = None
    best_score = -1.0

    dist_to_goal = math.hypot(shooter_pos[0] - gx, shooter_pos[1] - CENTER_Y)
    dist_factor = max(0.0, 1.0 - (dist_to_goal / 950.0))

    for tgt in targets:
        clearance, _ = _evaluate_passing_lane(shooter_pos, tgt, opponents, margin=35.0)
        target_bias = 1.2 if tgt != mid_goal else 0.9
        score = clearance * 0.6 + dist_factor * 0.4 * target_bias
        if score > best_score:
            best_score = score
            best_target = tgt

    # Unleash high power strikes
    needed_power = min(MAX_KICK_POWER, max(17.0, dist_to_goal * 0.025 + 14.0))

    return {
        "score": best_score,
        "target": best_target,
        "power": needed_power,
        "dist": dist_to_goal,
    }


def _find_best_pass(player, teammates, opponents, attacking_right, role):
    """Evaluate forward/breakaway passes only."""
    best_score = -1.0
    best_target = None
    best_power = 15.0
    best_teammate = None

    px, py = player.x, player.y
    goal_dir = 1.0 if attacking_right else -1.0

    for tm in teammates:
        is_gk = hasattr(tm, "ai") and tm.ai and getattr(tm.ai, "role", "") == ROLE_GK
        if is_gk:
            continue

        tx, ty = tm.x, tm.y
        dist = math.hypot(tx - px, ty - py)
        if dist < 80.0 or dist > 850.0:
            continue

        forward_progress = (tx - px) * goal_dir
        # Heavily penalize backward/sideways passes to stop overpassing
        if forward_progress < 40.0:
            continue

        progress_score = _clamp(forward_progress / 350.0, 0.0, 1.2)

        # Teammate openness
        tm_opp_dist = min((math.hypot(tx - opp.x, ty - opp.y) for opp in opponents), default=999.0)
        openness_score = _clamp(tm_opp_dist / 140.0, 0.0, 1.0)

        # Lead through-ball evaluation
        lead_x = tx + getattr(tm, "face_x", 0.0) * min(100.0, dist * 0.3)
        lead_y = ty + getattr(tm, "face_y", 0.0) * min(100.0, dist * 0.3)
        lead_clearance, _ = _evaluate_passing_lane((px, py), (lead_x, lead_y), opponents, margin=32.0)

        clearance, _ = _evaluate_passing_lane((px, py), (tx, ty), opponents, margin=32.0)

        if lead_clearance >= clearance:
            target_pt = (lead_x, lead_y)
            chosen_clearance = lead_clearance
        else:
            target_pt = (tx, ty)
            chosen_clearance = clearance

        if chosen_clearance < 0.40:
            continue

        pass_utility = (chosen_clearance * 0.40 +
                        openness_score * 0.25 +
                        progress_score * 0.35)

        if pass_utility > best_score:
            best_score = pass_utility
            best_target = target_pt
            best_teammate = tm
            best_power = min(MAX_KICK_POWER, max(14.0, dist * 0.035 + 9.0))

    return {
        "score": best_score,
        "target": best_target,
        "power": best_power,
        "receiver": best_teammate,
    }


def _find_clearance_target(player, opponents, attacking_right):
    """Find a rapid forward blast toward the opponent's attacking box."""
    px, py = player.x, player.y
    goal_dir = 1.0 if attacking_right else -1.0

    target_x = _clamp(px + goal_dir * 600.0, 80.0, WIDTH - 80.0)
    target_y = CENTER_Y + (random.choice([-1, 1]) * 150.0)

    return (target_x, target_y), MAX_KICK_POWER


# =============================================================================
# 4. Base Gemini AI Class
# =============================================================================

class GeminiAI(BaseAI):
    """Core Gemini High-Aggression Tactical AI."""

    name = "Gemini"

    def __init__(self, role):
        self.role = role
        self._target = None
        self._target_timer = 0
        self._last_action = "hold"
        self._kick_planned = False
        self._planned_power = 0.0
        self._planned_face = None

    def reset(self):
        self._target = None
        self._target_timer = 0
        self._last_action = "hold"
        self._kick_planned = False
        self._planned_power = 0.0
        self._planned_face = None

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        trajectory = _simulate_ball_trajectory(ball_x, ball_y, ball_vx, ball_vy, max_steps=45)
        world = _analyze_possession_and_arrival(player, teammates, opponents, trajectory)

        if player.holding_ball:
            return self._decide_on_ball(player, teammates, opponents, attacking_right, world)
        else:
            return self._decide_off_ball(player, teammates, opponents, attacking_right, trajectory, world)

    def _decide_on_ball(self, player, teammates, opponents, attacking_right, world):
        """Ultra-Aggressive On-Ball Logic: Shoot & Drive First, Pass Only When Necessary."""
        px, py = player.x, player.y
        goal = _goal_center(attacking_right)
        goal_dir = 1.0 if attacking_right else -1.0

        shot_eval = _evaluate_shot((px, py), opponents, attacking_right)
        pass_eval = _find_best_pass(player, teammates, opponents, attacking_right, self.role)

        closest_opp_dist = min((math.hypot(px - opp.x, py - opp.y) for opp in opponents), default=999.0)
        under_heavy_pressure = (closest_opp_dist < 55.0)

        # 1. Goalkeeper Distribution: Direct long ball to striker/playmaker
        if self.role == ROLE_GK:
            if pass_eval["score"] > 0.35 and pass_eval["target"] is not None:
                target = pass_eval["target"]
                power = max(16.0, pass_eval["power"])
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = power
                return self._build_decision(player, px, py, target, sprint=False, kick=False, face=face)
            else:
                target, power = _find_clearance_target(player, opponents, attacking_right)
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = power
                return self._build_decision(player, px, py, target, sprint=False, kick=False, face=face)

        # 2. Striker: Shoot-on-sight from anywhere within 700px!
        if self.role == ROLE_STR:
            if shot_eval["dist"] < 720.0 and (shot_eval["score"] > 0.15 or shot_eval["dist"] < 450.0):
                target = shot_eval["target"]
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = max(18.0, shot_eval["power"])
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            # If outside shooting range: drive full-speed sprint straight at the goal center!
            drive_target = (goal[0], CENTER_Y)
            face = _vec_norm((goal_dir, 0.0))
            return self._build_decision(player, px, py, drive_target, sprint=True, kick=False, face=face)

        # 3. Playmaker: Long range rockets or lethal through-balls
        if self.role == ROLE_PM:
            if shot_eval["dist"] < 650.0 and shot_eval["score"] > 0.25:
                target = shot_eval["target"]
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = max(18.0, shot_eval["power"])
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            # High value through-ball to sprinting striker
            if pass_eval["score"] > 0.55 and pass_eval["target"] is not None:
                target = pass_eval["target"]
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = pass_eval["power"]
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            # Otherwise sprint-dribble directly toward the attacking box to get into shooting range
            drive_target = (goal[0] - goal_dir * 200.0, CENTER_Y)
            face = _vec_norm((goal_dir, 0.0))
            return self._build_decision(player, px, py, drive_target, sprint=True, kick=False, face=face)

        # 4. Defender: Aggressive forward drive or direct long strike
        if self.role == ROLE_DEF:
            # If in opponent's half and open: shoot!
            if shot_eval["dist"] < 600.0 and shot_eval["score"] > 0.30:
                target = shot_eval["target"]
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = MAX_KICK_POWER
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            # Forward long-ball into attacking third
            if pass_eval["score"] > 0.40 and pass_eval["target"] is not None:
                target = pass_eval["target"]
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = max(16.0, pass_eval["power"])
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            if under_heavy_pressure or _in_own_box(px, py, attacking_right):
                target, power = _find_clearance_target(player, opponents, attacking_right)
                face = _vec_norm((target[0] - px, target[1] - py))
                player.kick_power = power
                return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

            # Open lane: drive forward with sprint
            drive_target = (px + goal_dir * 250.0, CENTER_Y)
            face = _vec_norm((goal_dir, 0.0))
            return self._build_decision(player, px, py, drive_target, sprint=True, kick=False, face=face)

        # Default aggressive shot or forward drive
        if shot_eval["score"] > 0.30 or shot_eval["dist"] < 500.0:
            target = shot_eval["target"]
            face = _vec_norm((target[0] - px, target[1] - py))
            player.kick_power = MAX_KICK_POWER
            return self._build_decision(player, px, py, target, sprint=True, kick=False, face=face)

        drive_target = (px + goal_dir * 200.0, py)
        face = _vec_norm((goal_dir, 0.0))
        return self._build_decision(player, px, py, drive_target, sprint=True, kick=False, face=face)

    def _decide_off_ball(self, player, teammates, opponents, attacking_right, trajectory, world):
        """High-Intensity Off-Ball Movement: Aggressive Pressing and Direct Box Runs."""
        px, py = player.x, player.y

        if self.role == ROLE_GK:
            target, sprint, face = self._gk_tactics(player, teammates, opponents, attacking_right, trajectory, world)
        elif self.role == ROLE_DEF:
            target, sprint, face = self._def_tactics(player, teammates, opponents, attacking_right, trajectory, world)
        elif self.role == ROLE_PM:
            target, sprint, face = self._pm_tactics(player, teammates, opponents, attacking_right, trajectory, world)
        elif self.role == ROLE_STR:
            target, sprint, face = self._str_tactics(player, teammates, opponents, attacking_right, trajectory, world)
        else:
            target, sprint, face = (CENTER_X, CENTER_Y), True, (1.0, 0.0)

        # Fast responsive tracking (minimal lag)
        if self._target is None or self._target_timer <= 0:
            self._target = target
            self._target_timer = 2
        else:
            self._target_timer -= 1
            self._target = (self._target[0] * 0.5 + target[0] * 0.5,
                            self._target[1] * 0.5 + target[1] * 0.5)

        return self._build_decision(player, px, py, self._target, sprint=sprint, kick=False, face=face)

    # ── Role-Specific High-Intensity Tactics ─────────────────────────────────

    def _gk_tactics(self, player, teammates, opponents, attacking_right, trajectory, world):
        """Goalkeeper Angle-Bisecting & Rapid Box Interceptions."""
        px, py = player.x, player.y
        bx, by, bvx, bvy = trajectory[0]
        own_goal = _own_goal_center(attacking_right)
        goal_dir = 1.0 if attacking_right else -1.0

        my_t = world["my_arrival_t"]
        opp_t = world["opponent_arrival_t"]
        in_box = _in_own_box(bx, by, attacking_right)

        if (in_box or math.hypot(bx - own_goal[0], by - own_goal[1]) < 280.0) and (my_t <= opp_t + 5):
            _, intercept_pt = _find_interception((px, py), SPRINT_SPEED, trajectory)
            face = _vec_norm((bx - px, by - py))
            return intercept_pt, True, face

        threat_x, threat_y = bx, by
        if world["holder"] and world["holder"] in opponents:
            threat_x, threat_y = world["holder"].x, world["holder"].y

        gx = own_goal[0]
        top_post = (gx, CENTER_Y - 110.0)
        bot_post = (gx, CENTER_Y + 110.0)

        v_top = _vec_norm((top_post[0] - threat_x, top_post[1] - threat_y))
        v_bot = _vec_norm((bot_post[0] - threat_x, bot_post[1] - threat_y))
        bisect_dir = _vec_norm((v_top[0] + v_bot[0], v_top[1] + v_bot[1]))

        dist_to_threat = math.hypot(threat_x - gx, threat_y - CENTER_Y)
        standoff = _clamp(dist_to_threat * 0.25, 30.0, 120.0)

        target_x = gx + bisect_dir[0] * standoff * (-goal_dir)
        target_y = CENTER_Y + bisect_dir[1] * standoff
        target_x, target_y = _clamp_in_own_box(target_x, target_y, attacking_right, margin=15.0)

        face = _vec_norm((threat_x - px, threat_y - py))
        return (target_x, target_y), True, face

    def _def_tactics(self, player, teammates, opponents, attacking_right, trajectory, world):
        """Aggressive Defender Pair: Relentless Challenger Press & Staggered Cover."""
        px, py = player.x, player.y
        bx, by, bvx, bvy = trajectory[0]
        own_goal = _own_goal_center(attacking_right)
        goal_dir = 1.0 if attacking_right else -1.0

        other_def = None
        for tm in teammates:
            if hasattr(tm, "ai") and tm.ai and getattr(tm.ai, "role", "") == ROLE_DEF:
                other_def = tm
                break

        threat_pos = (bx, by)
        if world["holder"] and world["holder"] in opponents:
            threat_pos = (world["holder"].x, world["holder"].y)

        my_dist_threat = _vec_dist((px, py), threat_pos)
        other_dist_threat = _vec_dist((other_def.x, other_def.y), threat_pos) if other_def else 999.0
        i_am_challenger = (my_dist_threat <= other_dist_threat)

        # Loose ball intercept up to 500px away!
        if world["my_arrival_t"] <= world["opponent_arrival_t"] + 1 and my_dist_threat < 520.0:
            _, intercept_pt = _find_interception((px, py), SPRINT_SPEED, trajectory)
            face = _vec_norm((bx - px, by - py))
            return intercept_pt, True, face

        if i_am_challenger:
            # Sprint directly to tackle the opponent ball carrier!
            if world["team_has_ball"]:
                base_x = own_goal[0] + goal_dir * 450.0
                base_y = CENTER_Y + (py - CENTER_Y) * 0.5
                face = _vec_norm((goal_dir, 0.0))
                return (base_x, base_y), True, face
            else:
                # Direct aggressive press on carrier
                face = _vec_norm((threat_pos[0] - px, threat_pos[1] - py))
                return threat_pos, True, face
        else:
            # Cover defender provides close depth support
            if world["team_has_ball"]:
                base_x = own_goal[0] + goal_dir * 320.0
                base_y = CENTER_Y - 100.0 if py < CENTER_Y else CENTER_Y + 100.0
                face = _vec_norm((goal_dir, 0.0))
                return (base_x, base_y), True, face
            else:
                cover_x = own_goal[0] + goal_dir * 220.0
                cover_y = CENTER_Y + (threat_pos[1] - CENTER_Y) * 0.55
                face = _vec_norm((threat_pos[0] - px, threat_pos[1] - py))
                return (cover_x, cover_y), True, face

    def _pm_tactics(self, player, teammates, opponents, attacking_right, trajectory, world):
        """Playmaker: Attack shooting pockets in front of the box and press fiercely."""
        px, py = player.x, player.y
        bx, by, _, _ = trajectory[0]
        goal = _goal_center(attacking_right)
        goal_dir = 1.0 if attacking_right else -1.0

        # Aggressively chase any reachable loose ball
        if world["my_arrival_t"] <= world["opponent_arrival_t"] + 1 and math.hypot(bx - px, by - py) < 480.0:
            _, intercept_pt = _find_interception((px, py), SPRINT_SPEED, trajectory)
            face = _vec_norm((bx - px, by - py))
            return intercept_pt, True, face

        if world["team_has_ball"]:
            # Advance right up to the edge of the opponent penalty box to shoot!
            attack_x = goal[0] - goal_dir * 340.0
            attack_y = CENTER_Y + (random.choice([-1, 1]) * 80.0)
            attack_x = _clamp(attack_x, 100.0, WIDTH - 100.0)
            face = _vec_norm((goal[0] - px, goal[1] - py))
            return (attack_x, attack_y), True, face
        else:
            # Press opposing carrier fiercely
            if world["holder"] and world["holder"] in opponents:
                press_pt = (world["holder"].x, world["holder"].y)
                face = _vec_norm((press_pt[0] - px, press_pt[1] - py))
                return press_pt, True, face
            else:
                hunt_x = CENTER_X + goal_dir * 50.0
                hunt_y = by
                face = _vec_norm((bx - px, by - py))
                return (hunt_x, hunt_y), True, face

    def _str_tactics(self, player, teammates, opponents, attacking_right, trajectory, world):
        """Striker: Relentless Box Crasher & High Press Terror."""
        px, py = player.x, player.y
        bx, by, _, _ = trajectory[0]
        goal = _goal_center(attacking_right)
        goal_dir = 1.0 if attacking_right else -1.0

        # Loose ball intercept in opponent half
        if world["my_arrival_t"] <= world["opponent_arrival_t"] + 3:
            _, intercept_pt = _find_interception((px, py), SPRINT_SPEED, trajectory)
            face = _vec_norm((bx - px, by - py))
            return intercept_pt, True, face

        if world["team_has_ball"]:
            # Crash the goal mouth directly for tap-ins / rebounds!
            crash_depth = goal[0] - goal_dir * 90.0
            crash_y = CENTER_Y + (random.choice([-1, 1]) * 60.0)
            crash_depth = _clamp(crash_depth, 60.0, WIDTH - 60.0)
            face = _vec_norm((goal[0] - px, goal[1] - py))
            return (crash_depth, crash_y), True, face
        else:
            # Full-speed press on the opposing ball carrier or GK!
            if world["holder"] and world["holder"] in opponents:
                press_pt = (world["holder"].x, world["holder"].y)
                face = _vec_norm((press_pt[0] - px, press_pt[1] - py))
                return press_pt, True, face
            else:
                hunt_target = (goal[0] - goal_dir * 250.0, by)
                face = _vec_norm((bx - px, by - py))
                return hunt_target, True, face

    def _build_decision(self, player, px, py, target, sprint=True, kick=False, face=None):
        """Construct standard decision dictionary required by game engine."""
        up, down, left, right = _quantize_movement(px, py, target[0], target[1])
        return {
            "up": up,
            "down": down,
            "left": left,
            "right": right,
            "sprint": sprint,
            "kick": kick,
            "face": face,
        }


# =============================================================================
# 5. Specialized Concrete Role Classes & Registry
# =============================================================================

class GeminiGoalkeeperAI(GeminiAI):
    name = "Gemini GK"

    def __init__(self):
        super().__init__(ROLE_GK)


class GeminiDefenderAI(GeminiAI):
    name = "Gemini DEF"

    def __init__(self):
        super().__init__(ROLE_DEF)


class GeminiPlaymakerAI(GeminiAI):
    name = "Gemini PM"

    def __init__(self):
        super().__init__(ROLE_PM)


class GeminiStrikerAI(GeminiAI):
    name = "Gemini STR"

    def __init__(self):
        super().__init__(ROLE_STR)


AI_REGISTRY["gemini_gk"]  = GeminiGoalkeeperAI
AI_REGISTRY["gemini_def"] = GeminiDefenderAI
AI_REGISTRY["gemini_pm"]  = GeminiPlaymakerAI
AI_REGISTRY["gemini_str"] = GeminiStrikerAI
AI_REGISTRY["gemini"]     = GeminiAI
AI_REGISTRY["gemini_ai"]  = GeminiAI
