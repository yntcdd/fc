import math
import random

# ——— Game constants (mirrored from main.py) ———
WIDTH = 1920
HEIGHT = 1080
GOAL_WIDTH = 40
GOAL_HEIGHT = 250
MAX_KICK_POWER = 25
KICK_CHARGE_RATE = 0.5
BALL_RADIUS = 12


class BaseAI:
    """Every AI subclasses this and implements ``decide()``.

    Decision dict::

        { "up", "down", "left", "right": bool,
          "sprint": bool,
          "kick":   bool | "release",
          "face":   (fx, fy) | None }
    """

    name = "Base"

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        raise NotImplementedError

    def reset(self):
        pass


# ================================================================
#  Shared helpers
# ================================================================

def _dist(ax, ay, bx, by):
    return math.hypot(ax - bx, by - ay)


def _norm(dx, dy):
    d = math.hypot(dx, dy)
    if d < 0.001:
        return 1.0, 0.0
    return dx / d, dy / d


def _move_toward(px, py, tx, ty):
    """(up, down, left, right) — always produces at least one True."""
    dx, dy = tx - px, ty - py
    d = math.hypot(dx, dy)
    if d < 1:
        return False, False, False, False
    dx, dy = dx / d, dy / d
    adx, ady = abs(dx), abs(dy)
    if adx > ady:
        return dy < -0.15, dy > 0.15, dx < 0, dx > 0
    else:
        return dy < 0, dy > 0, dx < -0.15, dx > 0.15


def _wall_push(px, py, margin=80):
    """Push away from nearby walls — strength ramps up closer you get."""
    u = d = l = r = False
    if py < margin:
        d = True
    elif py > HEIGHT - margin:
        u = True
    if px < margin:
        r = True
    elif px > WIDTH - margin:
        l = True
    return u, d, l, r


def _in_corner(px, py, threshold=150):
    """True if the point is within *threshold* of two walls (a corner)."""
    near_top = py < threshold
    near_bot = py > HEIGHT - threshold
    near_lef = px < threshold
    near_rig = px > WIDTH - threshold
    return (near_top or near_bot) and (near_lef or near_rig)


def _near_any_wall(px, py, threshold=100):
    return (py < threshold or py > HEIGHT - threshold or
            px < threshold or px > WIDTH - threshold)


def _closest_opponent(px, py, opponents):
    best, best_d = None, float("inf")
    for o in opponents:
        d = _dist(px, py, o.x, o.y)
        if d < best_d:
            best, best_d = o, d
    return best, best_d


def _point_to_segment(ox, oy, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    if abx == 0 and aby == 0:
        return _dist(ox, oy, ax, ay)
    t = ((ox - ax) * abx + (oy - ay) * aby) / (abx * abx + aby * aby)
    t = max(0.0, min(1.0, t))
    return _dist(ox, oy, ax + t * abx, ay + t * aby)


def _path_blocked(px, py, tx, ty, obstacles, clearance=40):
    for o in obstacles:
        if _point_to_segment(o.x, o.y, px, py, tx, ty) < clearance + o.radius:
            return True
    return False


def _wall_bounce_aim(px, py, goal_x, goal_y):
    """(x, y) on top/bottom wall for a bank shot, or None."""
    best, best_score = None, -999
    for wall_y, mirror in [(BALL_RADIUS, -goal_y),
                           (HEIGHT - BALL_RADIUS, 2 * HEIGHT - goal_y)]:
        dx, dy = goal_x - px, mirror - py
        if abs(dy) < 0.01:
            continue
        t = (wall_y - py) / dy
        if 0.1 < t < 2.0:
            ax = px + dx * t
            if BALL_RADIUS < ax < WIDTH - BALL_RADIUS:
                score = abs(ax - goal_x)
                if score > best_score:
                    best, best_score = (ax, wall_y), score
    return best


def _best_pass(player, teammates, opponents, attacking_right):
    """(teammate, score) for the best passing option."""
    goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
    best, best_score = None, -999
    for t in teammates:
        if t is player or t.holding_ball:
            continue
        opp_d = min((_dist(t.x, t.y, o.x, o.y) for o in opponents), default=999)
        goal_d = _dist(t.x, t.y, goal_x, HEIGHT // 2)
        me_d = _dist(player.x, player.y, t.x, t.y)
        blocked = _path_blocked(player.x, player.y, t.x, t.y, opponents, 35)
        # Bonus for teammates ahead of us (further toward opponent goal)
        ahead = (t.x > player.x) if attacking_right else (t.x < player.x)
        ahead_bonus = 120 if ahead else 0
        score = (500 - goal_d) * 0.5 + opp_d * 1.5 - me_d * 0.3 + ahead_bonus
        if blocked:
            score -= 400
        if score > best_score:
            best, best_score = t, score
    return best, best_score


def _blend(m1, m2, w2=0.5):
    """Blend two (up,down,left,right) tuples."""
    u1, d1, l1, r1 = m1
    u2, d2, l2, r2 = m2
    w1 = 1.0 - w2
    return (
        (u1 * w1 + u2 * w2) > 0.4,
        (d1 * w1 + d2 * w2) > 0.4,
        (l1 * w1 + l2 * w2) > 0.4,
        (r1 * w1 + r2 * w2) > 0.4,
    )


def _escape_corner(player, attacking_right):
    """Movement that gets the player out of a corner / off a wall.
    Returns (up, down, left, right, face_x, face_y)."""
    cx, cy = WIDTH // 2, HEIGHT // 2
    # Bias toward center-field, but leaning toward opponent goal
    goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
    toward_x = (cx + goal_x) / 2
    toward_y = cy
    move = _move_toward(player.x, player.y, toward_x, toward_y)
    wall = _wall_push(player.x, player.y, 120)
    up, down, left, right = _blend(move, wall, 0.7)
    face = _norm(toward_x - player.x, toward_y - player.y)
    return up, down, left, right, face


# ================================================================
#  AI: Striker
# ================================================================

class StrikerAI(BaseAI):
    """Aggressive scorer — jukes, long shots, wall bounces, passes
    under pressure.  Makes forward runs after passing (give-and-go)."""

    name = "Striker"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0
        self._juke_phase = random.random() * 6.28
        self._run_timer = 0          # frames left on forward run after passing

    # ------------------------------------------------------------------
    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = False
        kick = False
        face = None

        goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
        goal_y = HEIGHT // 2
        dx_goal = 1 if attacking_right else -1

        self._juke_phase += 0.14
        juke = math.sin(self._juke_phase)
        if self._run_timer > 0:
            self._run_timer -= 1

        # ——— carrying the ball ————————————————————————————————
        if player.holding_ball:
            sprint = True
            dist_to_goal = _dist(player.x, player.y, goal_x, goal_y)
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            clear = not _path_blocked(player.x, player.y, goal_x, goal_y, opponents, 50)

            # ════════════════════════════════════════════════════
            #  CORNER / WALL ESCAPE — override everything
            # ════════════════════════════════════════════════════
            if _in_corner(player.x, player.y, 150) or _near_any_wall(player.x, player.y, 90):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                self._charge = 0
                kick = False

            # ════════════════════════════════════════════════════
            #  1) Wall bounce when direct path blocked
            # ════════════════════════════════════════════════════
            elif opp_dist < 180 and dist_to_goal > 250 and not clear:
                bounce = _wall_bounce_aim(player.x, player.y, goal_x, goal_y)
                if bounce is not None:
                    face = _norm(bounce[0] - player.x, bounce[1] - player.y)
                    move = _move_toward(player.x, player.y, bounce[0], bounce[1])
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.5:
                        kick = False; self._charge = 0
                else:
                    up, down, left, right, face = _escape_corner(player, attacking_right)
                    self._charge = 0; kick = False

            # ════════════════════════════════════════════════════
            #  2) Shoot when clear
            # ════════════════════════════════════════════════════
            elif clear and dist_to_goal < 800:
                face = _norm(dx_goal, (goal_y - player.y) / max(1, abs(goal_y - player.y)) * 0.25)
                kick = True
                self._charge += 1
                ratio = 0.35 + min(dist_to_goal / 2000, 0.55)
                needed = MAX_KICK_POWER / KICK_CHARGE_RATE * ratio
                if self._charge > needed or (opp_dist < 70 and self._charge > 8):
                    kick = False; self._charge = 0
                move = _move_toward(player.x, player.y, goal_x, goal_y)
                wall = _wall_push(player.x, player.y, 70)
                up, down, left, right = _blend(move, wall, 0.5)

            # ════════════════════════════════════════════════════
            #  3) Pass + start a forward run (give-and-go)
            # ════════════════════════════════════════════════════
            elif opp_dist < 120 and dist_to_goal > 300:
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                if mate is not None and score > 20:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.45:
                        kick = False; self._charge = 0
                        self._run_timer = 35   # start forward run
                    move = _move_toward(player.x, player.y, mate.x, mate.y)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    # Dribble
                    primary = _move_toward(player.x, player.y, goal_x, goal_y)
                    juke_bias = (juke > 0.25, juke < -0.25, False, False)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(primary, juke_bias, 0.35)
                    up, down, left, right = _blend((up, down, left, right), wall, 0.6)
                    face = _norm(dx_goal, juke * 0.5)
                    self._charge = 0; kick = False

            # ════════════════════════════════════════════════════
            #  4) Emergency kick — shoot immediately, keep moving
            # ════════════════════════════════════════════════════
            elif opp_dist < 55 and player.kick_cooldown == 0:
                face = _norm(dx_goal, random.choice([-0.4, -0.15, 0, 0.15, 0.4]))
                # Quick charge + immediate release next frame
                if player.kick_power == 0:
                    kick = True
                    self._charge += 1
                elif self._charge >= 4:
                    kick = False; self._charge = 0
                else:
                    kick = True
                    self._charge += 1
                # Keep moving toward goal while kicking
                move = _move_toward(player.x, player.y, goal_x, goal_y)
                wall = _wall_push(player.x, player.y, 80)
                up, down, left, right = _blend(move, wall, 0.6)

            # ════════════════════════════════════════════════════
            #  5) Normal dribble
            # ════════════════════════════════════════════════════
            else:
                primary = _move_toward(player.x, player.y, goal_x, goal_y)
                juke_bias = (juke > 0.25, juke < -0.25, False, False)
                wall = _wall_push(player.x, player.y, 70)
                up, down, left, right = _blend(primary, juke_bias, 0.35)
                up, down, left, right = _blend((up, down, left, right), wall, 0.6)
                face = _norm(dx_goal, juke * 0.5)
                self._charge = 0; kick = False

        # ——— loose ball ———————————————————————————————————————
        else:
            sprint = True
            pred_x = ball_x + ball_vx * 6
            pred_y = ball_y + ball_vy * 6

            # Give-and-go: if we just passed, make a forward run
            if self._run_timer > 0:
                run_x = player.x + dx_goal * 70
                run_y = HEIGHT // 2 + (30 if player.y < HEIGHT // 2 else -30)
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0)
            else:
                our_d = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)

                if our_d <= mate_d + 50 or our_d < 130:
                    move = _move_toward(player.x, player.y, pred_x, pred_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    sup_x = (ball_x + goal_x) / 2
                    sup_y = HEIGHT // 2 + (50 if player.y < HEIGHT // 2 else -50)
                    up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)

            face = _norm(ball_x - player.x, ball_y - player.y)
            self._charge = 0; kick = False

        decision = {
            "up": up, "down": down, "left": left, "right": right,
            "sprint": sprint, "kick": kick, "face": face,
        }
        if self._was_kicking and not kick and player.kick_power > 0:
            decision["kick"] = "release"
        self._was_kicking = kick
        return decision

    def reset(self):
        self._was_kicking = False
        self._charge = 0
        self._run_timer = 0


# ================================================================
#  AI: Playmaker
# ================================================================

class PlaymakerAI(BaseAI):
    """Pass-first midfielder — creates space, returns 1-2s, shoots
    from range when open, uses wall bounces."""

    name = "Playmaker"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0
        self._juke_phase = random.random() * 6.28
        self._run_timer = 0
        self._last_passer = None     # teammate who just passed to us (for 1-2 return)

    # ------------------------------------------------------------------
    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = False
        kick = False
        face = None

        goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
        goal_y = HEIGHT // 2
        own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH
        dx_goal = 1 if attacking_right else -1

        self._juke_phase += 0.11
        juke = math.sin(self._juke_phase)
        if self._run_timer > 0:
            self._run_timer -= 1

        # Track who has the ball
        holder = None
        for p in teammates + opponents:
            if p.holding_ball:
                holder = p
                break

        # Detect when a teammate passes to us (we just got the ball)
        # If a teammate was the previous holder and now we have it
        if player.holding_ball and self._last_passer is None and holder is None:
            # We just picked it up — check if a teammate is on a forward run
            for t in teammates:
                if t is not player and hasattr(t, 'ai') and t.ai is not None:
                    if hasattr(t.ai, '_run_timer') and t.ai._run_timer > 0:
                        self._last_passer = t
                        break

        # ——— carrying ——————————————————————————————————————————
        if player.holding_ball:
            sprint = True
            dist_to_goal = _dist(player.x, player.y, goal_x, goal_y)
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            clear = not _path_blocked(player.x, player.y, goal_x, goal_y, opponents, 50)

            # ════════════════════════════════════════════════════
            #  CORNER / WALL ESCAPE
            # ════════════════════════════════════════════════════
            if _in_corner(player.x, player.y, 150) or _near_any_wall(player.x, player.y, 90):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                self._charge = 0; kick = False

            # ════════════════════════════════════════════════════
            #  1) Return pass to a teammate on a forward run (1-2)
            # ════════════════════════════════════════════════════
            elif self._last_passer is not None and _dist(player.x, player.y, self._last_passer.x, self._last_passer.y) < 600:
                mate = self._last_passer
                if not mate.holding_ball and not _path_blocked(player.x, player.y, mate.x, mate.y, opponents, 35):
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    kick = True
                    self._charge += 1
                    dist = _dist(player.x, player.y, mate.x, mate.y)
                    needed = min(dist / MAX_KICK_POWER / 2.5,
                                 MAX_KICK_POWER / KICK_CHARGE_RATE * 0.45)
                    if self._charge > needed:
                        kick = False; self._charge = 0
                        self._run_timer = 30
                        self._last_passer = None
                    move = _move_toward(player.x, player.y, mate.x, mate.y)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    self._last_passer = None

            # ════════════════════════════════════════════════════
            #  2) Pass to any well-positioned teammate
            # ════════════════════════════════════════════════════
            elif True:  # always consider passing
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                if mate is not None and score > 50 and (opp_dist < 160 or score > 150):
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    kick = True
                    self._charge += 1
                    dist_to_mate = _dist(player.x, player.y, mate.x, mate.y)
                    needed = min(dist_to_mate / MAX_KICK_POWER / 2.5,
                                 MAX_KICK_POWER / KICK_CHARGE_RATE * 0.5)
                    if self._charge > needed:
                        kick = False; self._charge = 0
                        self._run_timer = 30
                    move = _move_toward(player.x, player.y, mate.x, mate.y)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)

                # 3) Wall bounce
                elif opp_dist < 160 and dist_to_goal > 300 and not clear:
                    bounce = _wall_bounce_aim(player.x, player.y, goal_x, goal_y)
                    if bounce is not None:
                        face = _norm(bounce[0] - player.x, bounce[1] - player.y)
                        kick = True
                        self._charge += 1
                        if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.45:
                            kick = False; self._charge = 0
                        move = _move_toward(player.x, player.y, bounce[0], bounce[1])
                        wall = _wall_push(player.x, player.y, 70)
                        up, down, left, right = _blend(move, wall, 0.5)
                    else:
                        up, down, left, right, face = _escape_corner(player, attacking_right)
                        self._charge = 0; kick = False

                # 4) Shoot when open
                elif clear and dist_to_goal < 700:
                    face = _norm(dx_goal, (goal_y - player.y) / max(1, abs(goal_y - player.y)) * 0.2)
                    kick = True
                    self._charge += 1
                    ratio = 0.3 + min(dist_to_goal / 2000, 0.5)
                    needed = MAX_KICK_POWER / KICK_CHARGE_RATE * ratio
                    if self._charge > needed or (opp_dist < 60 and self._charge > 6):
                        kick = False; self._charge = 0
                    move = _move_toward(player.x, player.y, goal_x, goal_y)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)

                # 5) Emergency kick
                elif opp_dist < 55 and player.kick_cooldown == 0:
                    face = _norm(dx_goal, 0)
                    if player.kick_power == 0:
                        kick = True; self._charge += 1
                    elif self._charge >= 4:
                        kick = False; self._charge = 0
                    else:
                        kick = True; self._charge += 1
                    move = _move_toward(player.x, player.y, goal_x, goal_y)
                    wall = _wall_push(player.x, player.y, 80)
                    up, down, left, right = _blend(move, wall, 0.6)

                # 6) Dribble
                else:
                    primary = _move_toward(player.x, player.y, goal_x, goal_y)
                    juke_bias = (juke > 0.2, juke < -0.2, False, False)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(primary, juke_bias, 0.3)
                    up, down, left, right = _blend((up, down, left, right), wall, 0.6)
                    face = _norm(dx_goal, juke * 0.4)
                    self._charge = 0; kick = False

        # ——— teammate has ball — get open —————————————————————
        elif holder in teammates:
            self._last_passer = None
            # Position ourselves for a pass: stay close to ball carrier
            sup_x = holder.x + (80 if attacking_right else -80)
            sup_y = holder.y + (60 if holder.y < HEIGHT // 2 else -60)
            sup_y += juke * 50
            sup_y = max(70, min(HEIGHT - 70, sup_y))

            sprint = _dist(player.x, player.y, sup_x, sup_y) > 150
            up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)
            face = _norm(dx_goal, 0)
            self._charge = 0; kick = False

        # ——— opponent has ball — defend ———————————————————————
        elif holder in opponents:
            self._last_passer = None
            def_x = (ball_x + own_goal_x) / 2
            def_y = (ball_y + HEIGHT // 2) / 2 + juke * 60
            def_y = max(60, min(HEIGHT - 60, def_y))

            sprint = _dist(player.x, player.y, def_x, def_y) > 160
            up, down, left, right = _move_toward(player.x, player.y, def_x, def_y)
            face = _norm(ball_x - player.x, ball_y - player.y)
            self._charge = 0; kick = False

        # ——— loose ball ———————————————————————————————————————
        else:
            self._last_passer = None
            sprint = True
            pred_x = ball_x + ball_vx * 5
            pred_y = ball_y + ball_vy * 5

            # Forward run after passing
            if self._run_timer > 0:
                run_x = player.x + dx_goal * 70
                run_y = HEIGHT // 2 + (30 if player.y < HEIGHT // 2 else -30)
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0)
            else:
                our_d = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)

                if our_d <= mate_d + 40 or our_d < 120:
                    move = _move_toward(player.x, player.y, pred_x, pred_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    mid_x = (ball_x + goal_x) / 2
                    mid_y = HEIGHT // 2 + juke * 70
                    mid_y = max(80, min(HEIGHT - 80, mid_y))
                    up, down, left, right = _move_toward(player.x, player.y, mid_x, mid_y)

            face = _norm(ball_x - player.x, ball_y - player.y)
            self._charge = 0; kick = False

        decision = {
            "up": up, "down": down, "left": left, "right": right,
            "sprint": sprint, "kick": kick, "face": face,
        }
        if self._was_kicking and not kick and player.kick_power > 0:
            decision["kick"] = "release"
        self._was_kicking = kick
        return decision

    def reset(self):
        self._was_kicking = False
        self._charge = 0
        self._run_timer = 0
        self._last_passer = None


# ================================================================
#  AI: Goalkeeper
# ================================================================

class GoalkeeperAI(BaseAI):
    """Sweeper-keeper — cuts angles, rushes out, clears to teammates
    or upfield corners.  Stays well away from walls."""

    name = "Goalkeeper"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0

    # ------------------------------------------------------------------
    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = False
        kick = False
        face = None

        own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH
        own_goal_y = HEIGHT // 2
        goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH

        # Home: cut the angle between ball and own goal
        home_x = own_goal_x + (70 if attacking_right else -70)
        angle_y = own_goal_y + (ball_y - own_goal_y) * 0.35
        home_y = max(GOAL_HEIGHT // 2 + 50,
                     min(HEIGHT - GOAL_HEIGHT // 2 - 50, angle_y))
        # Never hug the wall
        home_y = max(80, min(HEIGHT - 80, home_y))

        # ——— carrying ——————————————————————————————————————————
        if player.holding_ball:
            # Wall escape first
            if _in_corner(player.x, player.y, 130) or _near_any_wall(player.x, player.y, 80):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                self._charge = 0; kick = False
            else:
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                if mate is not None and score > -120:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                else:
                    corner_y = own_goal_y + random.choice([-100, 100])
                    face = _norm(
                        1 if attacking_right else -1,
                        (corner_y - player.y) / max(1, abs(corner_y - player.y)) * 0.4)

                kick = True
                self._charge += 1
                if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.75:
                    kick = False; self._charge = 0
                wall = _wall_push(player.x, player.y, 100)
                up, down, left, right = wall

        # ——— loose / defending ————————————————————————————————
        else:
            dist_to_ball = _dist(player.x, player.y, ball_x, ball_y)
            dist_to_home = _dist(player.x, player.y, home_x, home_y)

            ball_danger = (
                abs(ball_x - own_goal_x) < 400 and
                abs(ball_y - own_goal_y) < GOAL_HEIGHT // 2 + 120
            )

            if ball_danger and dist_to_ball < 280:
                sprint = True
                ix = max(30, min(WIDTH - 30, ball_x + ball_vx * 5))
                iy = max(30, min(HEIGHT - 30, ball_y + ball_vy * 5))
                move = _move_toward(player.x, player.y, ix, iy)
                wall = _wall_push(player.x, player.y, 40)
                up, down, left, right = _blend(move, wall, 0.4)
                face = _norm(ball_x - player.x, ball_y - player.y)

            elif dist_to_ball < 200:
                sprint = True
                move = _move_toward(player.x, player.y, ball_x, ball_y)
                wall = _wall_push(player.x, player.y, 50)
                up, down, left, right = _blend(move, wall, 0.5)
                face = _norm(ball_x - player.x, ball_y - player.y)

            elif dist_to_home > 15:
                move = _move_toward(player.x, player.y, home_x, home_y)
                wall = _wall_push(player.x, player.y, 50)
                up, down, left, right = _blend(move, wall, 0.5)
                face = _norm(ball_x - player.x, ball_y - player.y)

            else:
                wall = _wall_push(player.x, player.y, 60)
                up, down, left, right = wall
                face = _norm(ball_x - player.x, ball_y - player.y)

            self._charge = 0; kick = False

        decision = {
            "up": up, "down": down, "left": left, "right": right,
            "sprint": sprint, "kick": kick, "face": face,
        }
        if self._was_kicking and not kick and player.kick_power > 0:
            decision["kick"] = "release"
        self._was_kicking = kick
        return decision

    def reset(self):
        self._was_kicking = False
        self._charge = 0


# ================================================================
#  AI: Trickster
# ================================================================

class TricksterAI(BaseAI):
    """Unpredictable — wall bounces, spin moves, long snipes, feints.
    Rotates trick modes every ~1 second."""

    name = "Trickster"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0
        self._juke_phase = random.random() * 6.28
        self._trick = "dribble"
        self._trick_timer = 0
        self._run_timer = 0

    # ------------------------------------------------------------------
    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = False
        kick = False
        face = None

        goal_x = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
        goal_y = HEIGHT // 2
        dx_goal = 1 if attacking_right else -1

        if self._trick_timer <= 0:
            self._trick = random.choice(["dribble", "wall", "spin", "snipe"])
            self._trick_timer = random.randint(45, 85)
        self._trick_timer -= 1

        self._juke_phase += random.uniform(0.09, 0.24)
        juke = math.sin(self._juke_phase)
        if self._run_timer > 0:
            self._run_timer -= 1

        # ——— carrying ——————————————————————————————————————————
        if player.holding_ball:
            sprint = True
            dist_to_goal = _dist(player.x, player.y, goal_x, goal_y)
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            clear = not _path_blocked(player.x, player.y, goal_x, goal_y, opponents, 45)

            # ════════════════════════════════════════════════════
            #  CORNER / WALL ESCAPE
            # ════════════════════════════════════════════════════
            if _in_corner(player.x, player.y, 150) or _near_any_wall(player.x, player.y, 90):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                self._charge = 0; kick = False

            # ——— wall bounce trick ————————————————————————————
            elif self._trick == "wall":
                bounce = _wall_bounce_aim(player.x, player.y, goal_x, goal_y)
                if bounce is not None:
                    face = _norm(bounce[0] - player.x, bounce[1] - player.y)
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.5:
                        kick = False; self._charge = 0
                    move = _move_toward(player.x, player.y, bounce[0], bounce[1])
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    self._trick = "dribble"

            # ——— spin trick ———————————————————————————————————
            elif self._trick == "spin":
                angle = self._juke_phase * 2.0
                sx, sy = math.cos(angle), math.sin(angle) * 0.7
                up, down, left, right = (
                    sy < -0.15, sy > 0.15, sx < -0.15, sx > 0.15)
                wall = _wall_push(player.x, player.y, 80)
                up, down, left, right = _blend((up, down, left, right), wall, 0.6)
                face = _norm(dx_goal, sy * 0.5)
                self._charge = 0; kick = False
                if clear and random.random() < 0.06:
                    face = _norm(dx_goal, random.choice([-0.4, -0.1, 0, 0.1, 0.4]))
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.4:
                        kick = False; self._charge = 0

            # ——— snipe trick ——————————————————————————————————
            elif self._trick == "snipe":
                if clear and dist_to_goal > 350:
                    corner_y = goal_y + random.choice([-120, -60, 60, 120])
                    face = _norm(dx_goal, (corner_y - player.y) / max(1, abs(corner_y - player.y)) * 0.3)
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.9:
                        kick = False; self._charge = 0
                    move = _move_toward(player.x, player.y, goal_x, goal_y)
                    wall = _wall_push(player.x, player.y, 70)
                    up, down, left, right = _blend(move, wall, 0.7)
                else:
                    self._trick = "dribble"

            # ——— dribble trick (default) ——————————————————————
            elif self._trick == "dribble":
                feint = juke * 1.1
                primary = _move_toward(player.x, player.y, goal_x, goal_y)
                juke_bias = (feint > 0.3, feint < -0.3, False, False)
                wall = _wall_push(player.x, player.y, 70)
                up, down, left, right = _blend(primary, juke_bias, 0.4)
                up, down, left, right = _blend((up, down, left, right), wall, 0.6)
                face = _norm(dx_goal, feint * 0.55)
                self._charge = 0; kick = False

                if random.random() < 0.025 and dist_to_goal < 600:
                    face = _norm(dx_goal, random.choice([-0.5, -0.2, 0.2, 0.5]))
                    kick = True
                    self._charge += 1
                    if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.35:
                        kick = False; self._charge = 0

                if random.random() < 0.02:
                    mate, _ = _best_pass(player, teammates, opponents, attacking_right)
                    if mate is not None:
                        face = _norm(mate.x - player.x, mate.y - player.y)
                        kick = True
                        self._charge += 1
                        if self._charge > MAX_KICK_POWER / KICK_CHARGE_RATE * 0.4:
                            kick = False; self._charge = 0
                            self._run_timer = 30

            # Emergency kick
            if opp_dist < 55 and player.kick_cooldown == 0 and player.kick_power == 0:
                face = _norm(dx_goal, random.uniform(-0.5, 0.5))
                kick = True; self._charge += 1
                move = _move_toward(player.x, player.y, goal_x, goal_y)
                wall = _wall_push(player.x, player.y, 80)
                up, down, left, right = _blend(move, wall, 0.6)

        # ——— loose ball ———————————————————————————————————————
        else:
            sprint = True
            pred_x = ball_x + ball_vx * 5
            pred_y = ball_y + ball_vy * 5

            if self._run_timer > 0:
                run_x = player.x + dx_goal * 70
                run_y = HEIGHT // 2 + (30 if player.y < HEIGHT // 2 else -30)
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0)
            else:
                our_d = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)

                if our_d <= mate_d + 40 or our_d < 120:
                    offset_x, offset_y = juke * 35, juke * 50
                    move = _move_toward(player.x, player.y,
                                        pred_x + offset_x, pred_y + offset_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    sup_x = (ball_x + goal_x) / 2
                    sup_y = HEIGHT // 2 + juke * 70
                    sup_y = max(80, min(HEIGHT - 80, sup_y))
                    up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)

            face = _norm(ball_x - player.x, ball_y - player.y)
            self._charge = 0; kick = False

        decision = {
            "up": up, "down": down, "left": left, "right": right,
            "sprint": sprint, "kick": kick, "face": face,
        }
        if self._was_kicking and not kick and player.kick_power > 0:
            decision["kick"] = "release"
        self._was_kicking = kick
        return decision

    def reset(self):
        self._was_kicking = False
        self._charge = 0
        self._trick_timer = 0
        self._run_timer = 0


# ================================================================
#  Registry
# ================================================================

AI_REGISTRY = {
    "striker":    StrikerAI,
    "playmaker":  PlaymakerAI,
    "goalkeeper": GoalkeeperAI,
    "trickster":  TricksterAI,
}


def create_ai(name):
    cls = AI_REGISTRY.get(name.lower())
    if cls is None:
        raise ValueError(
            f"Unknown AI '{name}'. Available: {list(AI_REGISTRY.keys())}")
    return cls()


def cycle_ai(current_ai):
    names = list(AI_REGISTRY.keys())
    if current_ai is None:
        return create_ai(names[0])
    cur_name = current_ai.name.lower()
    cur_key = None
    for key, cls in AI_REGISTRY.items():
        if cls.name.lower() == cur_name:
            cur_key = key
            break
    if cur_key is None:
        return None
    idx = names.index(cur_key)
    nxt = idx + 1
    if nxt >= len(names):
        return None
    return create_ai(names[nxt])
