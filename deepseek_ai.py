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


def _find_safe_clearance(px, py, opponents, attacking_right):
    """Return (fx, fy) — direction with the fewest opponents nearby.
    Scans several angles and picks the one where the closest opponent
    is furthest away.  Biased toward the opponent's goal."""
    goal_dir = 1 if attacking_right else -1
    best_dir = (goal_dir, 0)
    best_score = -999

    # Scan angles, biased toward attacking direction
    angles = []
    for i in range(-4, 5):
        angle = i * 0.35  # ~±80° in steps
        fx = goal_dir * math.cos(angle)
        fy = math.sin(angle)
        angles.append((fx, fy))

    # Also try straight down/up the wings
    angles.extend([(goal_dir * 0.7, 1), (goal_dir * 0.7, -1)])

    for fx, fy in angles:
        d = math.hypot(fx, fy)
        fx, fy = fx / d, fy / d
        # Score: how far the closest opponent is in this direction
        closest = 9999
        for o in opponents:
            # How far is this opponent from the ray?
            to_o_x = o.x - px
            to_o_y = o.y - py
            proj = to_o_x * fx + to_o_y * fy
            if proj < 0:
                continue  # opponent behind us, doesn't block clearance
            # Perpendicular distance from the ray
            perp = abs(-fy * to_o_x + fx * to_o_y)
            if perp < closest:
                closest = perp
            # Also penalize if opponent is close along the ray
            if proj < 300 and perp < 150:
                closest = min(closest, perp * 0.5)

        # Bonus for directions toward opponent goal
        toward_goal = fx * goal_dir
        score = closest + toward_goal * 200
        if score > best_score:
            best_score = score
            best_dir = (fx, fy)

    return best_dir


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
        ahead_bonus = 200 if ahead else -100  # penalize backward passes
        # Striker bonus — prefer passing to strikers
        is_striker = (hasattr(t, 'ai') and t.ai is not None and t.ai.name == 'Deepseek STR')
        striker_bonus = 250 if is_striker else 0
        # Goalkeeper penalty — avoid passing to own GK unless desperate
        is_gk = (hasattr(t, 'ai') and t.ai is not None and t.ai.name == 'Deepseek GK')
        gk_penalty = -600 if is_gk else 0
        # Human bonus — prefer passing to a human-controlled teammate
        is_human = (t.ai is None)
        human_bonus = 300 if is_human else 0
        score = (500 - goal_d) * 0.5 + opp_d * 1.5 - me_d * 0.3 + ahead_bonus + striker_bonus + gk_penalty + human_bonus
        if blocked:
            score -= 400
        if score > best_score:
            best, best_score = t, score
    return best, best_score


def _shot_quality(player, goal_x, goal_y, opponents):
    """Score how good a shot this player could take RIGHT NOW (0-1000+).
    Higher = better scoring chance. Blocked shots score very low."""
    dist_to_goal = _dist(player.x, player.y, goal_x, goal_y)
    shot_blocked = _path_blocked(player.x, player.y, goal_x, goal_y, opponents, 40)
    if shot_blocked:
        return -200  # useless shot
    opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
    # Distance factor: 0 at 2000px, ~600 at 0px
    dist_score = max(0, 600 - dist_to_goal * 0.3)
    # Pressure factor: less pressured = better shot
    pressure_score = min(200, opp_dist * 1.5)
    # Angle: being aligned with goal center helps
    goal_center_y = goal_y
    angle_to_center = abs(player.y - goal_center_y) / max(1, dist_to_goal)
    angle_score = max(0, 100 - angle_to_center * 300)
    return dist_score + pressure_score + angle_score


def _is_one_v_one(player, goal_x, goal_y, opponents):
    """True if the only opponent between player and goal is the goalkeeper."""
    outfield_blockers = 0
    for o in opponents:
        # Check if opponent is between player and goal
        if _point_to_segment(o.x, o.y, player.x, player.y, goal_x, goal_y) < 50 + o.radius:
            is_gk = (hasattr(o, 'ai') and o.ai is not None and o.ai.name == 'Deepseek GK')
            if not is_gk:
                outfield_blockers += 1
    return outfield_blockers == 0


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
#  Deepseek AI: Striker
# ================================================================

class DeepseekStrikerAI(BaseAI):
    """Aggressive scorer — jukes, long shots, wall bounces, passes
    under pressure.  Makes forward runs after passing (give-and-go)."""

    name = "Deepseek STR"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0
        self._juke_phase = random.random() * 6.28
        self._run_timer = 0          # frames left on forward run after passing
        self._dribble_timer = 0      # frames spent in opponent half without shooting

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
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            past_half = ((attacking_right and player.x > WIDTH // 2) or
                         (not attacking_right and player.x < WIDTH // 2))

            # Corner targets
            corner_top = (goal_x, goal_y - GOAL_HEIGHT // 2 + 20)
            corner_bot = (goal_x, goal_y + GOAL_HEIGHT // 2 - 20)
            if player.y < goal_y:
                aim_x, aim_y = corner_top
            else:
                aim_x, aim_y = corner_bot
            face = _norm(aim_x - player.x, aim_y - player.y)

            # Always move forward toward goal
            forward = _move_toward(player.x, player.y, goal_x, HEIGHT // 2)
            wall = _wall_push(player.x, player.y, 60)
            up, down, left, right = _blend(forward, wall, 0.5)

            # ——— Corner/wall escape ————————————————————————————
            if _in_corner(player.x, player.y, 120) or _near_any_wall(player.x, player.y, 70):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                kick = False

            # ——— Past halfway — SHOOT IMMEDIATELY —————————————
            elif past_half:
                # Try closer corner, if blocked try other, shoot anyway
                other_x = corner_bot[0] if (aim_y < goal_y) else corner_top[0]
                other_y = corner_bot[1] if (aim_y < goal_y) else corner_top[1]
                if _path_blocked(player.x, player.y, aim_x, aim_y, opponents, 35):
                    if not _path_blocked(player.x, player.y, other_x, other_y, opponents, 35):
                        aim_x, aim_y = other_x, other_y
                        face = _norm(aim_x - player.x, aim_y - player.y)
                player.kick_power = MAX_KICK_POWER
                kick = False

            # ——— Before halfway — pass forward or sprint ———————
            elif player.kick_cooldown == 0:
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                pass_blocked = mate is not None and _path_blocked(
                    player.x, player.y, mate.x, mate.y, opponents, 30)
                mate_ahead = mate is not None and (
                    (attacking_right and mate.x > player.x) or
                    (not attacking_right and mate.x < player.x))
                if mate is not None and score > 50 and not pass_blocked and mate_ahead:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 10
                    kick = False
                    if player.kick_cooldown > 0:
                        self._run_timer = 40

        # ——— loose ball ———————————————————————————————————————
        else:
            sprint = True
            pred_x = ball_x + ball_vx * 6
            pred_y = ball_y + ball_vy * 6

            own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH

            # Check who has the ball
            holder = None
            for p in teammates + opponents:
                if p.holding_ball:
                    holder = p
                    break

            # Give-and-go: if we just passed, make a forward run
            if self._run_timer > 0:
                run_x = player.x + dx_goal * 90
                run_y = HEIGHT // 2 + (50 if player.y < HEIGHT // 2 else -50)
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0)

            # Opponent has the ball — CHASE AND STEAL
            elif holder in opponents:
                # Run directly at the ball carrier to tackle
                sprint = True
                chase_x = ball_x + ball_vx * 4
                chase_y = ball_y + ball_vy * 4
                # But don't cross into opponent half too far
                if attacking_right:
                    chase_x = min(chase_x, WIDTH // 2 + 60)
                else:
                    chase_x = max(chase_x, WIDTH // 2 - 60)
                chase_y = max(50, min(HEIGHT - 50, chase_y))
                up, down, left, right = _move_toward(player.x, player.y, chase_x, chase_y)
                wall = _wall_push(player.x, player.y, 40)
                up, down, left, right = _blend((up, down, left, right), wall, 0.5)
                face = _norm(ball_x - player.x, ball_y - player.y)

            # Teammate has ball — get open ahead of them
            elif holder is not None:
                # Position ahead of holder toward opponent goal
                target_x = holder.x + dx_goal * 120
                target_x = max(60, min(WIDTH - 60, target_x))
                # Spread vertically from holder to create passing lane
                if holder.y < HEIGHT // 2:
                    target_y = holder.y + 130
                else:
                    target_y = holder.y - 130
                target_y = max(70, min(HEIGHT - 70, target_y))

                # If holder is our GK, come back more to receive outlet
                holder_is_gk = (hasattr(holder, 'ai') and holder.ai is not None
                                and holder.ai.name == 'Deepseek GK')
                if holder_is_gk:
                    target_x = holder.x + dx_goal * 180
                    target_y = HEIGHT // 2 + (80 if player.y < HEIGHT // 2 else -80)

                # If lane blocked, shift to other side
                path_open = not _path_blocked(holder.x, holder.y, player.x, player.y, opponents, 40)
                if not path_open:
                    target_y = HEIGHT - target_y

                sprint = _dist(player.x, player.y, target_x, target_y) > 100
                up, down, left, right = _move_toward(player.x, player.y, target_x, target_y)
                wall = _wall_push(player.x, player.y, 50)
                up, down, left, right = _blend((up, down, left, right), wall, 0.5)

            else:
                our_d = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)

                if our_d <= mate_d + 50 or our_d < 130:
                    move = _move_toward(player.x, player.y, pred_x, pred_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.5)
                else:
                    # Stay in midfield, don't rush to opponent net
                    mid_x = WIDTH // 2 + dx_goal * 150
                    sup_y = HEIGHT // 2 + (100 if player.y < HEIGHT // 2 else -100)
                    up, down, left, right = _move_toward(player.x, player.y, mid_x, sup_y)

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
        self._dribble_timer = 0


# ================================================================
#  Deepseek AI: Playmaker
# ================================================================

class DeepseekPlaymakerAI(BaseAI):
    """Pass-first midfielder — creates space, returns 1-2s, shoots
    from range when open, uses wall bounces."""

    name = "Deepseek PM"

    def __init__(self):
        self._was_kicking = False
        self._charge = 0
        self._juke_phase = random.random() * 6.28
        self._run_timer = 0
        self._last_passer = None     # teammate who just passed to us (for 1-2 return)
        self._dribble_timer = 0      # frames spent in opponent half without shooting

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
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            past_half = ((attacking_right and player.x > WIDTH // 2) or
                         (not attacking_right and player.x < WIDTH // 2))

            # Corner targets
            corner_top = (goal_x, goal_y - GOAL_HEIGHT // 2 + 20)
            corner_bot = (goal_x, goal_y + GOAL_HEIGHT // 2 - 20)
            if player.y < goal_y:
                aim_x, aim_y = corner_top
            else:
                aim_x, aim_y = corner_bot
            face = _norm(aim_x - player.x, aim_y - player.y)

            # Always move forward toward goal
            forward = _move_toward(player.x, player.y, goal_x, HEIGHT // 2)
            wall = _wall_push(player.x, player.y, 60)
            up, down, left, right = _blend(forward, wall, 0.5)

            # ——— Corner / wall escape ———————————————————————————
            if _in_corner(player.x, player.y, 130) or _near_any_wall(player.x, player.y, 80):
                up, down, left, right, face = _escape_corner(player, attacking_right)
                kick = False

            # ——— Past halfway — SHOOT IMMEDIATELY —————————————
            elif past_half:
                other_x = corner_bot[0] if (aim_y < goal_y) else corner_top[0]
                other_y = corner_bot[1] if (aim_y < goal_y) else corner_top[1]
                if _path_blocked(player.x, player.y, aim_x, aim_y, opponents, 35):
                    if not _path_blocked(player.x, player.y, other_x, other_y, opponents, 35):
                        aim_x, aim_y = other_x, other_y
                        face = _norm(aim_x - player.x, aim_y - player.y)
                player.kick_power = MAX_KICK_POWER
                kick = False

            # ——— Before halfway — pass forward or sprint ———————
            elif player.kick_cooldown == 0:
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                pass_blocked = mate is not None and _path_blocked(
                    player.x, player.y, mate.x, mate.y, opponents, 30)
                mate_ahead = mate is not None and (
                    (attacking_right and mate.x > player.x) or
                    (not attacking_right and mate.x < player.x))
                if mate is not None and score > 50 and not pass_blocked and mate_ahead:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 10
                    kick = False
                    if player.kick_cooldown > 0:
                        self._run_timer = 30

        # ——— teammate has ball — get open ahead of them ——————————
        elif holder in teammates:
            self._last_passer = None
            # Position ahead of holder toward opponent goal
            sup_x = holder.x + (100 if attacking_right else -100)
            sup_x = max(100, min(WIDTH - 100, sup_x))
            # Spread vertically from holder
            if holder.y < HEIGHT // 2:
                sup_y = holder.y + 130
            else:
                sup_y = holder.y - 130
            sup_y = max(70, min(HEIGHT - 70, sup_y))

            # If holder is GK, come back for outlet
            holder_is_gk = (hasattr(holder, 'ai') and holder.ai is not None
                            and holder.ai.name == 'Deepseek GK')
            if holder_is_gk:
                sup_x = holder.x + (150 if attacking_right else -150)
                sup_y = HEIGHT // 2 + (80 if player.y < HEIGHT // 2 else -80)

            # If lane blocked, shift to other side
            path_open = not _path_blocked(holder.x, holder.y, player.x, player.y, opponents, 40)
            if not path_open:
                sup_y = HEIGHT - sup_y

            sprint = _dist(player.x, player.y, sup_x, sup_y) > 100
            up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)
            wall = _wall_push(player.x, player.y, 50)
            up, down, left, right = _blend((up, down, left, right), wall, 0.5)
            face = _norm(dx_goal, 0)
            self._charge = 0; kick = False

        # ——— opponent has ball — CHASE AND STEAL ——————————————
        elif holder in opponents:
            self._last_passer = None
            sprint = True
            chase_x = ball_x + ball_vx * 4
            chase_y = ball_y + ball_vy * 4
            if attacking_right:
                chase_x = min(chase_x, WIDTH // 2 + 60)
            else:
                chase_x = max(chase_x, WIDTH // 2 - 60)
            chase_y = max(50, min(HEIGHT - 50, chase_y))
            up, down, left, right = _move_toward(player.x, player.y, chase_x, chase_y)
            wall = _wall_push(player.x, player.y, 40)
            up, down, left, right = _blend((up, down, left, right), wall, 0.5)
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
                run_x = player.x + dx_goal * 90
                run_y = HEIGHT // 2 + (50 if player.y < HEIGHT // 2 else -50)
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
                    mid_y = HEIGHT // 2 + juke * 100
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
        self._dribble_timer = 0


# ================================================================
#  Deepseek AI: Goalkeeper
# ================================================================

class DeepseekGoalkeeperAI(BaseAI):
    """Box-bound keeper — never leaves the penalty area, clears to wings
    or to open teammates."""

    name = "Deepseek GK"

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

        # Penalty box boundaries
        if attacking_right:
            box_left, box_right = 0, 250
        else:
            box_left, box_right = WIDTH - 250, WIDTH
        box_top = HEIGHT // 2 - 200
        box_bot = HEIGHT // 2 + 200

        # Home: goal mouth, tracks ball vertically
        home_x = own_goal_x + (25 if attacking_right else -25)
        home_x = max(box_left + 5, min(box_right - 5, home_x))
        angle_y = own_goal_y + (ball_y - own_goal_y) * 0.5
        home_y = max(box_top + 5, min(box_bot - 5, angle_y))

        # ——— carrying ——————————————————————————————————————————
        if player.holding_ball:
            sprint = True
            mate, score = _best_pass(player, teammates, opponents, attacking_right)
            if mate is not None and score > 200:
                face = _norm(mate.x - player.x, mate.y - player.y)
            else:
                wing_y = box_top + 20 if player.y < own_goal_y else box_bot - 20
                wing_x = own_goal_x + (230 if attacking_right else -230)
                face = _norm(wing_x - player.x, wing_y - player.y)
            player.kick_power = MAX_KICK_POWER
            kick = False
            up, down, left, right = _move_toward(player.x, player.y, home_x, home_y)

        # ——— loose / defending ————————————————————————————————
        else:
            sprint = True
            dist_to_ball = _dist(player.x, player.y, ball_x, ball_y)
            ball_danger = (
                abs(ball_x - own_goal_x) < 350 and
                abs(ball_y - own_goal_y) < GOAL_HEIGHT // 2 + 120
            )

            if ball_danger and dist_to_ball < 200:
                ix = max(box_left + 5, min(box_right - 5, ball_x + ball_vx * 4))
                iy = max(box_top + 5, min(box_bot - 5, ball_y + ball_vy * 4))
                up, down, left, right = _move_toward(player.x, player.y, ix, iy)
                face = _norm(ball_x - player.x, ball_y - player.y)
            else:
                up, down, left, right = _move_toward(player.x, player.y, home_x, home_y)
                face = _norm(ball_x - player.x, ball_y - player.y)

            kick = False

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
#  Deepseek AI: Trickster
# ================================================================

class DeepseekTricksterAI(BaseAI):
    """Unpredictable — wall bounces, spin moves, long snipes, feints.
    Rotates trick modes every ~1 second."""

    name = "Deepseek Trickster"

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
            clear = not _path_blocked(player.x, player.y, goal_x, goal_y, opponents, 30)

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

                if random.random() < 0.04 and dist_to_goal < 1000:
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
                run_x = player.x + dx_goal * 90
                run_y = HEIGHT // 2 + (50 if player.y < HEIGHT // 2 else -50)
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
                    sup_y = HEIGHT // 2 + juke * 100
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
#  Deepseek AI: Defender
# ================================================================

class DeepseekDefenderAI(BaseAI):
    """Active defender — tracks ball directly, stays in own half, clears danger."""

    name = "Deepseek DEF"

    def __init__(self):
        self._was_kicking = False

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = True  # always sprint
        kick = False
        face = None

        own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH
        own_goal_y = HEIGHT // 2
        dx_goal = 1 if attacking_right else -1
        half_x = WIDTH // 2

        # Track who has the ball
        holder = None
        for p in teammates + opponents:
            if p.holding_ball:
                holder = p
                break

        # ——— carrying — pass or clear immediately ————————————
        if player.holding_ball:
            mate, score = _best_pass(player, teammates, opponents, attacking_right)
            pass_blocked = mate is not None and _path_blocked(
                player.x, player.y, mate.x, mate.y, opponents, 30)
            mate_ok = (mate is not None and score > 50 and not pass_blocked
                       and not (hasattr(mate, 'ai') and mate.ai is not None
                                and mate.ai.name == 'Deepseek GK'))
            if mate_ok:
                face = _norm(mate.x - player.x, mate.y - player.y)
                player.kick_power = MAX_KICK_POWER
                kick = False
            else:
                wing_y = 80 if player.y < HEIGHT // 2 else HEIGHT - 80
                face = _norm(dx_goal, (wing_y - player.y) / max(1, abs(wing_y - player.y)) * 0.5)
                player.kick_power = MAX_KICK_POWER
                kick = False
            safe_x = own_goal_x + dx_goal * 100
            if attacking_right:
                safe_x = min(safe_x, half_x - 30)
            else:
                safe_x = max(safe_x, half_x + 30)
            up, down, left, right = _move_toward(player.x, player.y, safe_x, own_goal_y)

        # ——— opponent has ball — chase directly —————————————
        elif holder in opponents:
            target_x = ball_x
            target_y = ball_y
            if attacking_right:
                target_x = min(target_x, half_x - 5)
            else:
                target_x = max(target_x, half_x + 5)
            target_y = max(35, min(HEIGHT - 35, target_y))
            up, down, left, right = _move_toward(player.x, player.y, target_x, target_y)
            face = _norm(ball_x - player.x, ball_y - player.y)

        # ——— teammate has ball — track ball —————————————————
        elif holder in teammates:
            target_x = ball_x
            target_y = ball_y
            if attacking_right:
                target_x = min(target_x, half_x - 20)
            else:
                target_x = max(target_x, half_x + 20)
            target_y = max(40, min(HEIGHT - 40, target_y))
            up, down, left, right = _move_toward(player.x, player.y, target_x, target_y)
            face = _norm(ball_x - player.x, ball_y - player.y)

        # ——— loose ball — chase it ———————————————————————————
        else:
            target_x = ball_x
            target_y = ball_y
            if attacking_right:
                target_x = min(target_x, half_x - 5)
            else:
                target_x = max(target_x, half_x + 5)
            target_y = max(35, min(HEIGHT - 35, target_y))
            up, down, left, right = _move_toward(player.x, player.y, target_x, target_y)
            face = _norm(ball_x - player.x, ball_y - player.y)

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


# ================================================================
#  Registry
# ================================================================

AI_REGISTRY = {
    "deepseek_str":    DeepseekStrikerAI,
    "deepseek_pm":    DeepseekPlaymakerAI,
    "deepseek_gk":    DeepseekGoalkeeperAI,
    "deepseek_trickster":  DeepseekTricksterAI,
    "deepseek_def":   DeepseekDefenderAI,
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
    cur_key = None
    for key, cls in AI_REGISTRY.items():
        if isinstance(current_ai, cls):
            cur_key = key
            break
    if cur_key is None:
        return None
    idx = names.index(cur_key)
    nxt = idx + 1
    if nxt >= len(names):
        return None
    return create_ai(names[nxt])
