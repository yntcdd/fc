"""z_ai.py — Utility-based spatial AI for 5v5 Pygame soccer.

Architecture: Every frame each role evaluates candidate actions using utility
scores derived from spatial analysis, ball prediction, and team context.
The highest-scoring action is executed — no hardcoded state machines.

Key design principles:
  - Utility scoring replaces if/elif decision chains
  - Defenders self-coordinate via distance comparison (no shared state)
  - Ball trajectory prediction drives positioning and interception
  - Spatial openness scoring prevents bunching
  - Multi-candidate position evaluation for smarter movement

Registers: z_gk, z_def, z_pm, z_str into AI_REGISTRY when imported.
"""

import math
import random

from ai import (
    BaseAI, AI_REGISTRY,
    WIDTH, HEIGHT, GOAL_WIDTH, GOAL_HEIGHT, MAX_KICK_POWER, BALL_RADIUS,
    _dist, _norm, _move_toward, _wall_push, _path_blocked,
    _closest_opponent, _blend,
)


# ────────────────────────────────────────────────────────────────
# Constants
# ────────────────────────────────────────────────────────────────
_FRICTION = 0.98
_BOX_D = 250
_BOX_HH = 200
_GHH = GOAL_HEIGHT // 2
_PR = 20


# ────────────────────────────────────────────────────────────────
# Geometry helpers
# ────────────────────────────────────────────────────────────────

def _box(ar):
    """Own penalty box: (left, right, top, bottom)."""
    if ar:
        return 0, _BOX_D, HEIGHT // 2 - _BOX_HH, HEIGHT // 2 + _BOX_HH
    return WIDTH - _BOX_D, WIDTH, HEIGHT // 2 - _BOX_HH, HEIGHT // 2 + _BOX_HH


def _in_box(x, y, ar):
    l, r, t, b = _box(ar)
    return l <= x <= r and t <= y <= b


def _clamp_box(x, y, ar, m=10):
    l, r, t, b = _box(ar)
    return max(l + m, min(r - m, x)), max(t + m, min(b - m, y))


def _own_gx(ar):
    return GOAL_WIDTH if ar else WIDTH - GOAL_WIDTH


def _opp_gx(ar):
    return WIDTH - GOAL_WIDTH if ar else GOAL_WIDTH


def _gd(ar):
    """Goal direction: +1 attacking right, -1 attacking left."""
    return 1 if ar else -1


# ────────────────────────────────────────────────────────────────
# Ball prediction
# ────────────────────────────────────────────────────────────────

def _predict(bx, by, vx, vy, n):
    """Predict ball position after n frames with friction and wall bounces."""
    for _ in range(n):
        bx += vx
        by += vy
        vx *= _FRICTION
        vy *= _FRICTION
        if by < BALL_RADIUS:
            by = BALL_RADIUS
            vy = abs(vy)
        elif by > HEIGHT - BALL_RADIUS:
            by = HEIGHT - BALL_RADIUS
            vy = -abs(vy)
    return bx, by


def _ball_speed(vx, vy):
    return math.hypot(vx, vy)


# ────────────────────────────────────────────────────────────────
# Teammate / opponent queries
# ────────────────────────────────────────────────────────────────

def _near_mate(px, py, mates, exclude=None):
    """Return (nearest_teammate, distance) excluding *exclude*."""
    best, bd = None, 1e9
    for t in mates:
        if t is exclude:
            continue
        d = _dist(px, py, t.x, t.y)
        if d < bd:
            best, bd = t, d
    return best, bd


def _is_gk(p):
    return p.ai is not None and ('GK' in p.ai.name or 'Goalkeeper' in p.ai.name)


def _find_holder(players):
    """Return the player currently holding the ball, or None."""
    for p in players:
        if p.holding_ball:
            return p
    return None


# ────────────────────────────────────────────────────────────────
# Spatial analysis
# ────────────────────────────────────────────────────────────────

def _openness(x, y, friends, foes, r=140):
    """How open is position (x, y)? Higher = fewer nearby players."""
    s = 0.0
    for o in foes:
        d = _dist(x, y, o.x, o.y)
        if d < r:
            s += (r - d) / r
    for f in friends:
        d = _dist(x, y, f.x, f.y)
        if d < 60:
            s += (60 - d) / 60 * 0.3
    return -s


def _opp_density(x, y, foes, r=180):
    """Sum of opponent closeness. Higher = more crowded by opponents."""
    s = 0.0
    for o in foes:
        d = _dist(x, y, o.x, o.y)
        if d < r:
            s += (r - d) / r
    return s


def _lane_ok(x1, y1, x2, y2, opps, clr=40):
    """Is the direct lane between two points clear of opponents?"""
    return not _path_blocked(x1, y1, x2, y2, opps, clr)


def _find_open(px, py, tx, ty, friends, foes, spread=180, samples=10):
    """Search near direction (px,py)->(tx,ty) for the most open position."""
    dx, dy = tx - px, ty - py
    d = math.hypot(dx, dy)
    if d < 1:
        return px, py
    dx, dy = dx / d, dy / d
    best_x, best_y = tx, ty
    best_s = -1e9
    for i in range(samples):
        ang = (i - samples // 2) * 0.22
        c, s = math.cos(ang), math.sin(ang)
        rx, ry = dx * c - dy * s, dx * s + dy * c
        sx = max(30, min(WIDTH - 30, px + rx * spread))
        sy = max(30, min(HEIGHT - 30, py + ry * spread))
        sc = _openness(sx, sy, friends, foes) - _dist(sx, sy, tx, ty) * 0.002
        if sc > best_s:
            best_s = sc
            best_x, best_y = sx, sy
    return best_x, best_y


# ────────────────────────────────────────────────────────────────
# Threat & utility scoring
# ────────────────────────────────────────────────────────────────

def _threat(bx, by, vx, vy, gx, gy):
    """How threatening is the ball to goal (gx, gy)? Returns ~0-1+."""
    gd = _dist(bx, by, gx, gy)
    prox = max(0, 1 - gd / 900)
    tdx, tdy = gx - bx, gy - by
    td = math.hypot(tdx, tdy)
    if td > 1:
        spd = math.hypot(vx, vy)
        heading = (vx * tdx / td + vy * tdy / td) / max(1, spd)
    else:
        heading = 0
    return prox * 0.5 + max(0, heading) * 0.5


def _pass_util(player, mate, opps, ar):
    """Utility score for passing to *mate*. Higher = better pass."""
    gx = _opp_gx(ar)
    mg = _dist(mate.x, mate.y, gx, HEIGHT // 2)
    pg = _dist(player.x, player.y, gx, HEIGHT // 2)
    forward = max(0, pg - mg) / max(1, pg)
    if _path_blocked(player.x, player.y, mate.x, mate.y, opps, 35):
        return -400
    pd = _dist(player.x, player.y, mate.x, mate.y)
    reliability = max(0, 1 - pd / 600)
    space = _openness(mate.x, mate.y, [player], opps, 120)
    gk_pen = -300 if _is_gk(mate) else 0
    human_bonus = 200 if mate.ai is None else 0
    return forward * 250 + reliability * 200 + space * 100 + human_bonus + gk_pen


def _best_pass_target(player, teammates, opps, ar):
    """Return (best_teammate, score) for passing."""
    best, best_s = None, -999
    for t in teammates:
        if t is player or t.holding_ball:
            continue
        s = _pass_util(player, t, opps, ar)
        if s > best_s:
            best, best_s = t, s
    return best, best_s


def _shot_util(player, gx, gy, opps):
    """Utility score for shooting from current position. 0-1000+."""
    d = _dist(player.x, player.y, gx, gy)
    if _path_blocked(player.x, player.y, gx, gy, opps, 40):
        return -100
    dist_sc = max(0, 600 - d * 0.3)
    opp_d = min((_dist(player.x, player.y, o.x, o.y) for o in opps), default=999)
    pressure = min(150, opp_d)
    angle = abs(player.y - gy) / max(1, d)
    angle_sc = max(0, 100 - angle * 300)
    return dist_sc + pressure + angle_sc


# ────────────────────────────────────────────────────────────────
# Movement helpers
# ────────────────────────────────────────────────────────────────

def _move_safe(player, tx, ty, wall_m=50, wall_w=0.4):
    """Move toward target with wall avoidance blended in."""
    mv = _move_toward(player.x, player.y, tx, ty)
    wl = _wall_push(player.x, player.y, wall_m)
    return _blend(mv, wl, wall_w)


# ────────────────────────────────────────────────────────────────
# Shared decision-wrap helper
# ────────────────────────────────────────────────────────────────

def _wrap(wk_attr_name):
    """Return a helper that builds a decision dict with kick-release logic.
    Use as: _wrap('_wk')(self, player, u, d, l, r, sprint, kick, face)"""
    def helper(self, player, u, d, l, r, sprint, kick, face):
        dec = {
            "up": u, "down": d, "left": l, "right": r,
            "sprint": sprint, "kick": kick, "face": face,
        }
        was = getattr(self, wk_attr_name)
        if was and not kick and player.kick_power > 0:
            dec["kick"] = "release"
        setattr(self, wk_attr_name, kick)
        return dec
    return helper


# ═══════════════════════════════════════════════════════════════
#  Z Goalkeeper
# ═══════════════════════════════════════════════════════════════

class ZGoalkeeperAI(BaseAI):
    """Threat-aware keeper with ball prediction and multi-position scoring.

    Instead of a simple goal-to-ball line, generates several candidate
    positions inside the box and picks the one that best covers predicted
    shot trajectories. Rushes only when the ball is slow and safe to collect.
    """

    name = "Z GK"
    _decide = _wrap('_wk')

    def __init__(self):
        self._wk = False

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        og_x = _own_gx(attacking_right)
        og_y = HEIGHT // 2
        gd = _gd(attacking_right)
        bx_l, bx_r, bx_t, bx_b = _box(attacking_right)
        kick = False
        face = None
        sprint = True
        u = d = l = r = False

        # Predicted ball positions
        pred10 = _predict(ball_x, ball_y, ball_vx, ball_vy, 10)
        pred20 = _predict(ball_x, ball_y, ball_vx, ball_vy, 20)
        ball_in_box = _in_box(ball_x, ball_y, attacking_right)
        dist_ball = _dist(player.x, player.y, ball_x, ball_y)
        b_spd = _ball_speed(ball_vx, ball_vy)

        # ── Carrying: distribute or clear ────────────────────
        if player.holding_ball:
            best_m, best_s = None, -999
            for t in teammates:
                if t is player or t.holding_ball or _is_gk(t):
                    continue
                s = _pass_util(player, t, opponents, attacking_right)
                if s > best_s:
                    best_s = s
                    best_m = t

            if best_m is not None and best_s > 80:
                face = _norm(best_m.x - player.x, best_m.y - player.y)
                pwr = min(MAX_KICK_POWER, max(8,
                    _dist(player.x, player.y, best_m.x, best_m.y) * 0.05))
            else:
                up_open = _openness(og_x + gd * 120, bx_t + 40,
                                    teammates, opponents, 100)
                dn_open = _openness(og_x + gd * 120, bx_b - 40,
                                    teammates, opponents, 100)
                if up_open > dn_open:
                    face = _norm(gd, -0.7)
                else:
                    face = _norm(gd, 0.7)
                pwr = MAX_KICK_POWER

            player.kick_power = pwr
            hx = max(bx_l + 15, min(bx_r - 15, og_x + gd * 25))
            u, d, l, r = _move_toward(player.x, player.y, hx, og_y)
            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Not carrying: evaluate candidate positions ─────────
        candidates = []

        # Candidate A: Angle-cut on goal-centre → current ball line
        gtb_d = math.hypot(ball_x - og_x, ball_y - og_y)
        if gtb_d > 1:
            reach = min(60, gtb_d * 0.22)
            ca_x = og_x + (ball_x - og_x) / gtb_d * reach
            ca_y = og_y + (ball_y - og_y) / gtb_d * reach
        else:
            ca_x, ca_y = og_x + gd * 30, og_y
        ca_x, ca_y = _clamp_box(ca_x, ca_y, attacking_right)
        candidates.append((ca_x, ca_y))

        # Candidate B: Angle-cut on goal-centre → predicted ball line
        gtb_pd = math.hypot(pred10[0] - og_x, pred10[1] - og_y)
        if gtb_pd > 1:
            reach = min(60, gtb_pd * 0.22)
            cb_x = og_x + (pred10[0] - og_x) / gtb_pd * reach
            cb_y = og_y + (pred10[1] - og_y) / gtb_pd * reach
        else:
            cb_x, cb_y = og_x + gd * 30, og_y
        cb_x, cb_y = _clamp_box(cb_x, cb_y, attacking_right)
        candidates.append((cb_x, cb_y))

        # Candidate C: Rush to intercept loose ball in box
        if ball_in_box and dist_ball < 200 and b_spd < 10:
            cx, cy = _clamp_box(ball_x, ball_y, attacking_right)
            candidates.append((cx, cy))

        # Candidate D: Centre-safe default
        candidates.append((max(bx_l + 15, min(bx_r - 15, og_x + gd * 25)), og_y))

        # Candidate E: Midway between ball and predicted ball
        mid_x = (ball_x + pred10[0]) / 2
        mid_y = (ball_y + pred10[1]) / 2
        mid_x, mid_y = _clamp_box(mid_x, mid_y, attacking_right)
        candidates.append((mid_x, mid_y))

        # Score each candidate position
        best_pos = candidates[-1]
        best_score = -999

        for cx, cy in candidates:
            score = 0.0

            # Coverage of ball-to-goal line
            btg_num = abs((ball_x - og_x) * (cy - og_y)
                          - (ball_y - og_y) * (cx - og_x))
            btg_den = math.hypot(ball_x - og_x, ball_y - og_y)
            if btg_den > 1:
                cov_ball = 1 - min(1, btg_num / btg_den / 80)
            else:
                cov_ball = 0.5
            score += cov_ball * 350

            # Coverage of predicted ball-to-goal line
            btg_p_num = abs((pred10[0] - og_x) * (cy - og_y)
                            - (pred10[1] - og_y) * (cx - og_x))
            btg_p_den = math.hypot(pred10[0] - og_x, pred10[1] - og_y)
            if btg_p_den > 1:
                cov_pred = 1 - min(1, btg_p_num / btg_p_den / 100)
            else:
                cov_pred = 0.5
            score += cov_pred * 250

            # Bonus for being close to ball when ball is in the box
            if ball_in_box:
                closeness = max(0, 200 - _dist(cx, cy, ball_x, ball_y)) / 200
                score += closeness * 200
            else:
                # Ball far away — prefer staying closer to goal line
                dist_from_gl = abs(cx - og_x)
                if dist_from_gl > 35:
                    score -= (dist_from_gl - 35) * 3

            # Rush bonus: when ball is slow & close, going to ball is great
            if (ball_in_box and dist_ball < 150 and b_spd < 8):
                if _dist(cx, cy, ball_x, ball_y) < 50:
                    score += 300
                elif _dist(cx, cy, ball_x, ball_y) < 100:
                    score += 150

            if score > best_score:
                best_score = score
                best_pos = (cx, cy)

        u, d, l, r = _move_safe(player, best_pos[0], best_pos[1], 35, 0.3)
        face = _norm(ball_x - player.x, ball_y - player.y)
        return self._decide(player, u, d, l, r, sprint, kick, face)

    def reset(self):
        self._wk = False


# ═══════════════════════════════════════════════════════════════
#  Z Defender
# ═══════════════════════════════════════════════════════════════

class ZDefenderAI(BaseAI):
    """Coordinated defender pair using distance-based primary/cover assignment.

    Each frame both defenders independently determine who is closer to the
    ball threat. The closer one becomes the "presser" (challenges the ball),
    the other becomes the "coverer" (shields space, blocks lanes). No shared
    state — coordination emerges from identical distance logic.
    """

    name = "Z DEF"
    _decide = _wrap('_wk')

    def __init__(self):
        self._wk = False

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        og_x = _own_gx(attacking_right)
        og_y = HEIGHT // 2
        gd = _gd(attacking_right)
        half = WIDTH // 2
        kick = False
        face = None
        sprint = True
        u = d = l = r = False

        holder = _find_holder(teammates + opponents)
        pred10 = _predict(ball_x, ball_y, ball_vx, ball_vy, 8)
        ball_in_own_half = ((attacking_right and ball_x < half) or
                            (not attacking_right and ball_x > half))

        # Am I the primary defender (closest to ball threat)?
        is_primary = self._is_primary(player, teammates, ball_x, ball_y,
                                      attacking_right)

        # ── Carrying: evaluate pass vs clear ───────────────────
        if player.holding_ball:
            opp, opp_d = _closest_opponent(player.x, player.y, opponents)
            best_m, best_s = _best_pass_target(player, teammates, opponents,
                                                attacking_right)

            # Utility scores for each action
            pass_score = best_s if (best_m and not _is_gk(best_m)) else -999
            clear_score = 200 if opp_d < 120 else 50

            if pass_score > clear_score and pass_score > -100:
                face = _norm(best_m.x - player.x, best_m.y - player.y)
                pwr = min(MAX_KICK_POWER, max(10,
                    _dist(player.x, player.y, best_m.x, best_m.y) * 0.06))
            else:
                wing_y = 90 if player.y < HEIGHT // 2 else HEIGHT - 90
                face = _norm(gd, (wing_y - player.y) /
                             max(1, abs(wing_y - player.y)) * 0.5)
                pwr = MAX_KICK_POWER

            player.kick_power = pwr
            safe_x = og_x + gd * 120
            if attacking_right:
                safe_x = min(safe_x, half - 30)
            else:
                safe_x = max(safe_x, half + 30)
            u, d, l, r = _move_toward(player.x, player.y, safe_x, og_y)
            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Determine ball threat position ──────────────────────
        if holder in opponents:
            threat_x, threat_y = ball_x, ball_y
        elif holder is None and ball_in_own_half:
            threat_x, threat_y = pred10
        else:
            threat_x, threat_y = ball_x, ball_y

        # ── Primary defender: press the threat ─────────────────
        if is_primary:
            if holder in opponents and ball_in_own_half:
                # Press ball carrier with prediction
                tgt_x = max(BALL_RADIUS, min(WIDTH - BALL_RADIUS, pred10[0]))
                tgt_y = max(40, min(HEIGHT - 40, pred10[1]))
                # Clamp to own half
                if attacking_right:
                    tgt_x = min(tgt_x, half - 5)
                else:
                    tgt_x = max(tgt_x, half + 5)
                u, d, l, r = _move_safe(player, tgt_x, tgt_y, 40, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

            elif holder is None and ball_in_own_half:
                # Chase loose ball in own half
                tgt_x = max(BALL_RADIUS, min(WIDTH - BALL_RADIUS, pred10[0]))
                tgt_y = max(40, min(HEIGHT - 40, pred10[1]))
                if attacking_right:
                    tgt_x = min(tgt_x, half - 5)
                else:
                    tgt_x = max(tgt_x, half + 5)
                u, d, l, r = _move_safe(player, tgt_x, tgt_y, 40, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

            else:
                # Ball in opponent half — hold defensive line
                home_x = og_x + gd * 200
                if attacking_right:
                    home_x = min(home_x, half - 60)
                else:
                    home_x = max(home_x, half + 60)
                home_y = max(80, min(HEIGHT - 80, threat_y))
                u, d, l, r = _move_safe(player, home_x, home_y, 50, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

        # ── Cover defender: protect space ──────────────────────
        else:
            if ball_in_own_half and (holder in opponents or holder is None):
                # Position between the threat and our goal, slightly offset
                cover_x = (threat_x + og_x) / 2
                cover_y = og_y
                # Shift to cover the most dangerous passing lane
                # Check which opponent is in the best position to receive
                for o in opponents:
                    if o is holder:
                        continue
                    od = _dist(o.x, o.y, threat_x, threat_y)
                    if od < 300:
                        # This opponent could receive a pass — shift toward lane
                        lane_x = (threat_x + o.x) / 2
                        lane_y = (threat_y + o.y) / 2
                        lane_d = _dist(lane_x, lane_y, og_x, og_y)
                        if lane_d < _dist(cover_x, cover_y, og_x, og_y):
                            cover_x = lane_x
                            cover_y = lane_y

                if attacking_right:
                    cover_x = max(og_x + 20, min(half - 10, cover_x))
                else:
                    cover_x = max(half + 10, min(og_x - 20, cover_x))
                cover_y = max(80, min(HEIGHT - 80, cover_y))

                u, d, l, r = _move_safe(player, cover_x, cover_y, 50, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

            elif holder in teammates:
                # Teammate has ball — position behind them for support
                sup_x = holder.x - gd * 130
                if attacking_right:
                    sup_x = max(og_x + 30, min(half - 20, sup_x))
                else:
                    sup_x = max(half + 20, min(og_x - 30, sup_x))
                sup_y = max(80, min(HEIGHT - 80, ball_y))
                u, d, l, r = _move_safe(player, sup_x, sup_y, 50, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

            else:
                # Ball in opponent half — compact defensive shape
                home_x = og_x + gd * 220
                if attacking_right:
                    home_x = min(home_x, half - 80)
                else:
                    home_x = max(home_x, half + 80)
                home_y = max(80, min(HEIGHT - 80, ball_y * 0.5 + og_y * 0.5))
                u, d, l, r = _move_safe(player, home_x, home_y, 50, 0.3)
                face = _norm(ball_x - player.x, ball_y - player.y)

        return self._decide(player, u, d, l, r, sprint, kick, face)

    def _is_primary(self, player, teammates, ball_x, ball_y, ar):
        """Am I the closest Z defender to the ball?"""
        my_d = _dist(player.x, player.y, ball_x, ball_y)
        for t in teammates:
            if t is not player and hasattr(t, 'ai') and isinstance(t, ZDefenderAI):
                if _dist(t.x, t.y, ball_x, ball_y) < my_d:
                    return False
        return True

    def reset(self):
        self._wk = False


# ═══════════════════════════════════════════════════════════════
#  Z Playmaker
# ═══════════════════════════════════════════════════════════════

class ZPlaymakerAI(BaseAI):
    """Creative midfielder using utility-scored action selection.

    When carrying: scores PASS, SHOOT, DRIBBLE against each other.
    When moving: evaluates multiple support positions and picks the most open.
    Falls back quickly on turnover, advances when space opens up.
    """

    name = "Z PM"
    _decide = _wrap('_wk')

    def __init__(self):
        self._wk = False
        self._run_timer = 0
        self._phase = random.random() * 6.28

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        og_x = _own_gx(attacking_right)
        gx = _opp_gx(attacking_right)
        gy = HEIGHT // 2
        gd = _gd(attacking_right)
        half = WIDTH // 2
        kick = False
        face = None
        sprint = False
        u = d = l = r = False

        self._phase += 0.1
        if self._run_timer > 0:
            self._run_timer -= 1

        holder = _find_holder(teammates + opponents)
        opp, opp_d = _closest_opponent(player.x, player.y, opponents)
        past_half = ((attacking_right and player.x > half) or
                     (not attacking_right and player.x < half))

        # ── Carrying: utility-score PASS vs SHOOT vs DRIBBLE ──
        if player.holding_ball:
            sprint = True

            best_m, pass_sc = _best_pass_target(player, teammates, opponents,
                                                attacking_right)
            shot_sc = _shot_util(player, gx, gy, opponents)

            # Dribble score: high when lots of open space ahead and far from goal
            space_ahead = _openness(player.x + gd * 100, player.y,
                                     teammates, opponents, 130)
            dribble_sc = space_ahead * 200 - opp_d * 1.5
            if not past_half:
                dribble_sc += 100  # encourage carrying through midfield

            # Corner / wall escape — highest priority override
            if (player.y < 130 and player.x < 130) or \
               (player.y > HEIGHT - 130 and player.x < 130) or \
               (player.y < 130 and player.x > WIDTH - 130) or \
               (player.y > HEIGHT - 130 and player.x > WIDTH - 130):
                esc_x = (gx + player.x) / 2
                esc_y = gy
                u, d, l, r = _move_safe(player, esc_x, esc_y, 70, 0.6)
                face = _norm(esc_x - player.x, esc_y - player.y)
                return self._decide(player, u, d, l, r, sprint, kick, face)

            # Pick best action
            if shot_sc > max(pass_sc, dribble_sc) and shot_sc > 250:
                corner_y = (gy - _GHH + 25 if player.y > gy
                            else gy + _GHH - 25)
                face = _norm(gx - player.x, corner_y - player.y)
                player.kick_power = MAX_KICK_POWER
                u, d, l, r = _move_safe(player, gx, gy, 50, 0.35)

            elif pass_sc > max(shot_sc, dribble_sc) and pass_sc > 50:
                face = _norm(best_m.x - player.x, best_m.y - player.y)
                player.kick_power = min(MAX_KICK_POWER, max(8,
                    _dist(player.x, player.y, best_m.x, best_m.y) * 0.06))
                self._run_timer = 30
                u, d, l, r = _move_safe(player, gx, gy, 55, 0.4)

            else:
                # Dribble forward
                tgt_x, tgt_y = _find_open(player.x, player.y, gx, gy,
                                          teammates, opponents, 160, 12)
                tgt_x = max(40, min(WIDTH - 40, tgt_x))
                tgt_y = max(40, min(HEIGHT - 40, tgt_y))
                u, d, l, r = _move_safe(player, tgt_x, tgt_y, 55, 0.4)
                face = _norm(gx - player.x, gy - player.y)

            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Teammate has ball: find open space ──────────────────
        if holder in teammates:
            if self._run_timer > 0:
                run_x = max(60, min(WIDTH - 60, player.x + gd * 130))
                run_y = max(60, min(HEIGHT - 60, gy + math.sin(self._phase) * 80))
                u, d, l, r = _move_safe(player, run_x, run_y, 50, 0.3)
                face = _norm(gd, 0)
            else:
                # Position ahead of ball carrier in open space
                preferred_x = holder.x + gd * 140
                preferred_y = holder.y + (100 if holder.y < gy else -100)
                preferred_x = max(80, min(WIDTH - 80, preferred_x))
                preferred_y = max(60, min(HEIGHT - 60, preferred_y))

                # Find the most open position near preferred
                open_x, open_y = _find_open(
                    player.x, player.y, preferred_x, preferred_y,
                    teammates, opponents, 140, 10)

                # If lane from holder to us is blocked, try other side
                if not _lane_ok(holder.x, holder.y, open_x, open_y,
                                opponents, 45):
                    open_y = HEIGHT - open_y
                    open_y = max(60, min(HEIGHT - 60, open_y))

                sprint = _dist(player.x, player.y, open_x, open_y) > 80
                u, d, l, r = _move_safe(player, open_x, open_y, 50, 0.3)
                face = _norm(gd, 0)

            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Opponent has ball: moderate press ──────────────────
        if holder in opponents:
            press_x = ball_x + ball_vx * 3
            press_y = ball_y + ball_vy * 3
            # Stay on our side of midfield unless very close
            if attacking_right:
                press_x = min(press_x, half + 80)
            else:
                press_x = max(press_x, half - 80)
            press_x = max(60, min(WIDTH - 60, press_x))
            press_y = max(50, min(HEIGHT - 50, press_y))
            u, d, l, r = _move_safe(player, press_x, press_y, 45, 0.35)
            face = _norm(ball_x - player.x, ball_y - player.y)
            return self._decide(player, u, d, l, r, True, kick, face)

        # ── Loose ball: evaluate chase vs position ──────────────
        pred = _predict(ball_x, ball_y, ball_vx, ball_vy, 6)
        my_d = _dist(player.x, player.y, pred[0], pred[1])
        _, mate_d = _near_mate(pred[0], pred[1], teammates, exclude=player)

        if self._run_timer > 0:
            run_x = max(60, min(WIDTH - 60, player.x + gd * 100))
            run_y = max(60, min(HEIGHT - 60, gy + math.sin(self._phase) * 80))
            u, d, l, r = _move_safe(player, run_x, run_y, 50, 0.3)
            face = _norm(gd, 0)
        elif my_d <= mate_d + 60 or my_d < 140:
            u, d, l, r = _move_safe(player, pred[0], pred[1], 45, 0.35)
            face = _norm(ball_x - player.x, ball_y - player.y)
        else:
            # Position in the space between ball and our goal
            sup_x = (ball_x + og_x) / 2 + gd * 60
            sup_y = max(80, min(HEIGHT - 80,
                       gy + math.sin(self._phase) * 100))
            u, d, l, r = _move_safe(player, sup_x, sup_y, 50, 0.3)
            face = _norm(ball_x - player.x, ball_y - player.y)

        return self._decide(player, u, d, l, r, sprint, kick, face)

    def reset(self):
        self._wk = False
        self._run_timer = 0


# ═══════════════════════════════════════════════════════════════
#  Z Striker
# ═══════════════════════════════════════════════════════════════

class ZStrikerAI(BaseAI):
    """Aggressive scorer with multi-pattern run evaluation.

    When carrying: utility-scores SHOOT vs PASS vs DRIBBLE.
    When moving: evaluates diagonal runs, lateral movement, runs behind
    defenders, and check-backs — picks the most effective pattern.
    Uses ball prediction to chase dangerous loose balls.
    """

    name = "Z STR"
    _decide = _wrap('_wk')

    def __init__(self):
        self._wk = False
        self._run_timer = 0
        self._phase = random.random() * 6.28
        self._pattern_timer = 0
        self._pattern = "direct"

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        og_x = _own_gx(attacking_right)
        gx = _opp_gx(attacking_right)
        gy = HEIGHT // 2
        gd = _gd(attacking_right)
        half = WIDTH // 2
        kick = False
        face = None
        sprint = True
        u = d = l = r = False

        self._phase += 0.13
        if self._run_timer > 0:
            self._run_timer -= 1

        # Rotate attack patterns periodically
        if self._pattern_timer <= 0:
            self._pattern = random.choice(
                ["direct", "diagonal", "lateral", "check"])
            self._pattern_timer = random.randint(40, 80)
        self._pattern_timer -= 1

        holder = _find_holder(teammates + opponents)
        opp, opp_d = _closest_opponent(player.x, player.y, opponents)
        past_half = ((attacking_right and player.x > half) or
                     (not attacking_right and player.x < half))
        dist_goal = _dist(player.x, player.y, gx, gy)

        # ── Carrying: utility-score SHOOT vs PASS vs DRIBBLE ──
        if player.holding_ball:
            shot_sc = _shot_util(player, gx, gy, opponents)
            best_m, pass_sc = _best_pass_target(player, teammates, opponents,
                                                attacking_right)

            # Dribble: good when space ahead and no close pressure
            space_ahead = _openness(player.x + gd * 120, player.y,
                                     teammates, opponents, 130)
            dribble_sc = space_ahead * 250 - opp_d * 2

            # Corner / wall escape
            if (player.y < 130 and player.x < 130) or \
               (player.y > HEIGHT - 130 and player.x < 130) or \
               (player.y < 130 and player.x > WIDTH - 130) or \
               (player.y > HEIGHT - 130 and player.x > WIDTH - 130):
                esc_x = (gx + player.x) / 2
                esc_y = gy
                u, d, l, r = _move_safe(player, esc_x, esc_y, 70, 0.6)
                face = _norm(esc_x - player.x, esc_y - player.y)
                return self._decide(player, u, d, l, r, sprint, kick, face)

            # Inside opponent box → shoot aggressively
            in_opp_box = _in_box(player.x, player.y, not attacking_right)
            if in_opp_box or (past_half and dist_goal < 380):
                corner_y = (gy - _GHH + 25 if player.y > gy
                            else gy + _GHH - 25)
                face = _norm(gx - player.x, corner_y - player.y)
                player.kick_power = MAX_KICK_POWER
                u, d, l, r = _move_safe(player, gx, gy, 45, 0.3)
                return self._decide(player, u, d, l, r, sprint, kick, face)

            # Pick best action from utility scores
            best_action = max(
                ("shoot", shot_sc),
                ("pass", pass_sc if best_m else -999),
                ("dribble", dribble_sc),
                key=lambda x: x[1],
            )

            if best_action[0] == "shoot" and shot_sc > 200:
                corner_y = (gy - _GHH + 30 if player.y > gy
                            else gy + _GHH - 30)
                face = _norm(gx - player.x, corner_y - player.y)
                player.kick_power = MAX_KICK_POWER
                u, d, l, r = _move_safe(player, gx, gy, 50, 0.35)

            elif best_action[0] == "pass" and pass_sc > 80:
                face = _norm(best_m.x - player.x, best_m.y - player.y)
                player.kick_power = min(MAX_KICK_POWER, max(8,
                    _dist(player.x, player.y, best_m.x, best_m.y) * 0.06))
                self._run_timer = 40
                u, d, l, r = _move_safe(player, gx, gy, 50, 0.35)

            else:
                tgt_x, tgt_y = _find_open(player.x, player.y, gx, gy,
                                          teammates, opponents, 170, 12)
                tgt_x = max(40, min(WIDTH - 40, tgt_x))
                tgt_y = max(40, min(HEIGHT - 40, tgt_y))
                u, d, l, r = _move_safe(player, tgt_x, tgt_y, 50, 0.35)
                face = _norm(gx - player.x, gy - player.y)

            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Teammate has ball: evaluate run patterns ───────────
        if holder in teammates:
            run_positions = self._generate_runs(
                player, holder, ball_x, ball_y, teammates, opponents,
                attacking_right)

            # Score each run position
            best_run = run_positions[0]
            best_run_s = -999

            for rx, ry in run_positions:
                s = 0.0
                # Openness
                s += _openness(rx, ry, teammates, opponents, 130) * 200
                # Passing lane from holder to us
                if _lane_ok(holder.x, holder.y, rx, ry, opponents, 45):
                    s += 150
                else:
                    s -= 200
                # Proximity to opponent goal
                goal_dist = _dist(rx, ry, gx, gy)
                s += max(0, 500 - goal_dist) * 0.3
                # Distance from nearby opponents (separation)
                for o in opponents:
                    od = _dist(rx, ry, o.x, o.y)
                    if od < 100:
                        s -= (100 - od) * 1.5
                if s > best_run_s:
                    best_run_s = s
                    best_run = (rx, ry)

            rx, ry = best_run
            sprint = _dist(player.x, player.y, rx, ry) > 80
            u, d, l, r = _move_safe(player, rx, ry, 50, 0.3)
            face = _norm(gd, 0)
            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Opponent has ball: aggressive press ─────────────────
        if holder in opponents:
            press_x = ball_x + ball_vx * 5
            press_y = ball_y + ball_vy * 5
            press_x = max(60, min(WIDTH - 60, press_x))
            press_y = max(50, min(HEIGHT - 50, press_y))
            u, d, l, r = _move_safe(player, press_x, press_y, 40, 0.3)
            face = _norm(ball_x - player.x, ball_y - player.y)
            return self._decide(player, u, d, l, r, sprint, kick, face)

        # ── Loose ball ─────────────────────────────────────────
        pred = _predict(ball_x, ball_y, ball_vx, ball_vy, 8)
        my_d = _dist(player.x, player.y, pred[0], pred[1])
        _, mate_d = _near_mate(pred[0], pred[1], teammates, exclude=player)

        if self._run_timer > 0:
            run_x = max(60, min(WIDTH - 60, player.x + gd * 120))
            run_y = max(60, min(HEIGHT - 60,
                       gy + math.sin(self._phase) * 90))
            u, d, l, r = _move_safe(player, run_x, run_y, 50, 0.3)
            face = _norm(gd, 0)
        elif my_d <= mate_d + 60 or my_d < 130:
            u, d, l, r = _move_safe(player, pred[0], pred[1], 45, 0.35)
            face = _norm(ball_x - player.x, ball_y - player.y)
        else:
            # Float into attacking space
            fwd_x = max(80, min(WIDTH - 80, max(half, ball_x + gd * 100)))
            fwd_y = max(60, min(HEIGHT - 60,
                       gy + math.sin(self._phase) * 80))
            u, d, l, r = _move_safe(player, fwd_x, fwd_y, 50, 0.3)
            face = _norm(ball_x - player.x, ball_y - player.y)

        return self._decide(player, u, d, l, r, sprint, kick, face)

    def _generate_runs(self, player, holder, ball_x, ball_y,
                       teammates, opponents, ar):
        """Generate candidate attacking run positions."""
        gd = _gd(ar)
        gx = _opp_gx(ar)
        gy = HEIGHT // 2
        half = WIDTH // 2

        runs = []

        # Direct run behind the defensive line
        runs.append((gx - gd * 80, gy - 80))
        runs.append((gx - gd * 80, gy + 80))

        # Diagonal run
        diag_off = 130 if self._pattern == "diagonal" else 80
        runs.append((player.x + gd * 160, player.y + diag_off))
        runs.append((player.x + gd * 160, player.y - diag_off))

        # Lateral movement in attacking zone
        lat_y = ball_y + (160 if self._pattern == "lateral" else 100)
        runs.append((max(half, gx - gd * 150), lat_y))
        runs.append((max(half, gx - gd * 150), HEIGHT - lat_y))

        # Check back toward ball
        check_x = ball_x + gd * 70
        check_y = ball_y + (90 if player.y < gy else -90)
        runs.append((check_x, check_y))

        # Run into space ahead of ball
        space_x = ball_x + gd * 180
        space_y = gy + math.sin(self._phase) * 120
        runs.append((space_x, space_y))

        # Clamp all to field bounds
        return [(max(40, min(WIDTH - 40, x)), max(40, min(HEIGHT - 40, y)))
                for x, y in runs]

    def reset(self):
        self._wk = False
        self._run_timer = 0
        self._pattern_timer = 0


# ═══════════════════════════════════════════════════════════════
# Registration — runs when `import z_ai` is executed
# ═══════════════════════════════════════════════════════════════

AI_REGISTRY["z_gk"]  = ZGoalkeeperAI
AI_REGISTRY["z_def"] = ZDefenderAI
AI_REGISTRY["z_pm"]  = ZPlaymakerAI
AI_REGISTRY["z_str"] = ZStrikerAI
