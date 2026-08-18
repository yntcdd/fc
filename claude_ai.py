"""claude_ai.py — Coordinated 4-role AI for the 4v4 Pygame soccer game.

Add `import claude_ai` in main.py (after `from deepseek_ai import ...`) to register:
    "claude_gk"   -> ClaudeGoalkeeperAI  (1 per team)
    "claude_pm"   -> ClaudePlaymakerAI   (2 per team, flank-aware)
    "claude_def"  -> ClaudeDefenderAI    (1 per team)
    "claude_str"  -> ClaudeStrikerAI     (1 per team, high-press scorer)

Players can be freely mixed between old AIs and these new AIs at any time
via create_ai() / the 1-8 key toggles in main.py.

Role summary
------------
Claude GK  : Box-bound keeper.  Angle-cuts on the goal-to-ball line, rushes
             loose balls inside the box, distributes smartly (best pass or
             wing clear at max power).

Claude PM  : Midfield engine.  Two playmakers self-assign complementary flanks
             (upper / lower) on their first frame. Positions in open space
             ahead of the ball, executes 1-2 combos, shoots medium-range when
             open, uses wall bounces under pressure.

Claude DEF : Disciplined last defender.  Stays in own third, slides onto the
             ball-to-goal line to block shot lanes, aggressively presses
             opponents in the defensive half, passes forward immediately on
             possession.

Claude STR : High-pressing scorer.  Chases ball carriers anywhere on the
             pitch, makes forward runs behind the defence when a teammate
             carries, and shoots decisively from inside the attacking box.
"""

import math
import random

from deepseek_ai import (
    BaseAI, AI_REGISTRY,
    WIDTH, HEIGHT, GOAL_WIDTH, GOAL_HEIGHT, MAX_KICK_POWER, BALL_RADIUS,
    KICK_CHARGE_RATE,
    _dist, _norm, _move_toward, _wall_push, _in_corner, _near_any_wall,
    _closest_opponent, _path_blocked, _find_safe_clearance,
    _wall_bounce_aim, _best_pass, _shot_quality, _is_one_v_one,
    _blend, _escape_corner,
)


# ── Penalty-box constants (must mirror draw_field in main.py) ─────────────────
_BOX_DEPTH  = 250
_BOX_HALF_H = 200
_GOAL_HALF  = GOAL_HEIGHT // 2


def _box_bounds(attacking_right):
    """(left, right, top, bottom) of the OWN penalty box."""
    if attacking_right:                         # own goal on the LEFT
        return 0, _BOX_DEPTH, HEIGHT // 2 - _BOX_HALF_H, HEIGHT // 2 + _BOX_HALF_H
    else:                                       # own goal on the RIGHT
        return (WIDTH - _BOX_DEPTH, WIDTH,
                HEIGHT // 2 - _BOX_HALF_H, HEIGHT // 2 + _BOX_HALF_H)


def _in_box(x, y, attacking_right):
    bl, br, bt, bb = _box_bounds(attacking_right)
    return bl <= x <= br and bt <= y <= bb


def _clamp_to_box(x, y, attacking_right, margin=8):
    bl, br, bt, bb = _box_bounds(attacking_right)
    return (max(bl + margin, min(br - margin, x)),
            max(bt + margin, min(bb - margin, y)))


def _is_claude_gk(p):
    return (hasattr(p, "ai") and p.ai is not None and
            p.ai.name in ("Deepseek GK", "Claude GK"))


# ================================================================
#  Claude AI: Goalkeeper
# ================================================================

class ClaudeGoalkeeperAI(BaseAI):
    """Box-bound keeper with angle-cutting positioning and smart distribution."""

    name = "Claude GK"

    def __init__(self):
        self._was_kicking = False

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = True
        kick = False
        face = None

        own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH
        own_goal_y = HEIGHT // 2
        dx_goal    = 1 if attacking_right else -1

        bl, br, bt, bb = _box_bounds(attacking_right)

        # ── Angle-cut target: stand on the goal-centre → ball line, ≤50 px out ──
        gtb_x = ball_x - own_goal_x
        gtb_y = ball_y - own_goal_y
        gtb_d = math.hypot(gtb_x, gtb_y)
        if gtb_d > 0.01:
            gtb_nx, gtb_ny = gtb_x / gtb_d, gtb_y / gtb_d
        else:
            gtb_nx, gtb_ny = dx_goal, 0.0

        reach = min(50.0, gtb_d * 0.25)
        cut_x = own_goal_x + gtb_nx * reach
        cut_y = own_goal_y + gtb_ny * reach
        cut_x, cut_y = _clamp_to_box(cut_x, cut_y, attacking_right)

        # ── Danger flags ─────────────────────────────────────────────────────
        ball_in_box = _in_box(ball_x, ball_y, attacking_right)
        ball_close  = _dist(player.x, player.y, ball_x, ball_y) < 160
        ball_danger = (abs(ball_x - own_goal_x) < 420 and
                       abs(ball_y - own_goal_y) < _GOAL_HALF + 170)

        # ── Carrying — distribute immediately ────────────────────────────────
        if player.holding_ball:
            mate, score = _best_pass(player, teammates, opponents, attacking_right)
            pass_clear = (mate is not None and
                          not _path_blocked(player.x, player.y,
                                            mate.x, mate.y, opponents, 30))

            if mate is not None and score > 150 and pass_clear:
                face = _norm(mate.x - player.x, mate.y - player.y)
                player.kick_power = min(MAX_KICK_POWER, 16)
            else:
                # Clear to the wing on the side with more open space
                wing_y = bt + 30 if player.y > HEIGHT // 2 else bb - 30
                clear_x = own_goal_x + dx_goal * (_BOX_DEPTH - 25)
                clear_x = max(bl + 10, min(br - 10, clear_x))
                face = _norm(clear_x - player.x, wing_y - player.y)
                player.kick_power = MAX_KICK_POWER

            kick = False
            up, down, left, right = _move_toward(player.x, player.y, cut_x, cut_y)

        # ── Ball inside box and close — rush to intercept ─────────────────────
        elif ball_in_box and ball_close:
            ix = max(bl + 8, min(br - 8, ball_x + ball_vx * 4))
            iy = max(bt + 8, min(bb - 8, ball_y + ball_vy * 4))
            up, down, left, right = _move_toward(player.x, player.y, ix, iy)
            face = _norm(ball_x - player.x, ball_y - player.y)

        # ── Ball is a threat — cut the angle ─────────────────────────────────
        elif ball_danger:
            up, down, left, right = _move_toward(player.x, player.y, cut_x, cut_y)
            face = _norm(ball_x - player.x, ball_y - player.y)

        # ── Safe — hold goal-mouth, track ball vertically ─────────────────────
        else:
            home_x = own_goal_x + dx_goal * 25
            home_y = own_goal_y + (ball_y - own_goal_y) * 0.45
            home_x, home_y = _clamp_to_box(home_x, home_y, attacking_right)
            up, down, left, right = _move_toward(player.x, player.y, home_x, home_y)
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
#  Claude AI: Playmaker  (flank-aware)
# ================================================================

class ClaudePlaymakerAI(BaseAI):
    """Midfield engine — complementary flank spacing, 1-2 combos, wall bounces."""

    name = "Claude PM"

    def __init__(self):
        self._was_kicking = False
        self._flank       = None   # "upper" or "lower", self-assigned first frame
        self._run_timer   = 0
        self._juke_phase  = random.random() * 6.28

    # ── Flank assignment ──────────────────────────────────────────────────────
    def _assign_flank(self, player, teammates):
        """Called once: pick the half not occupied by the other Claude PM."""
        if self._flank is not None:
            return
        others = [t for t in teammates
                  if t is not player
                  and hasattr(t, "ai")
                  and isinstance(t.ai, ClaudePlaymakerAI)]
        if others:
            self._flank = "upper" if player.y <= others[0].y else "lower"
        else:
            self._flank = "upper"

    def _flank_y(self):
        return HEIGHT // 4 if self._flank == "upper" else HEIGHT * 3 // 4

    # ── Main decision ─────────────────────────────────────────────────────────
    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = False
        kick = False
        face = None

        self._assign_flank(player, teammates)

        goal_x  = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
        goal_y  = HEIGHT // 2
        dx_goal = 1 if attacking_right else -1
        half_x  = WIDTH // 2

        self._juke_phase += 0.11
        juke = math.sin(self._juke_phase)
        if self._run_timer > 0:
            self._run_timer -= 1

        holder = None
        for p in teammates + opponents:
            if p.holding_ball:
                holder = p
                break

        # ── Carrying ──────────────────────────────────────────────────────────
        if player.holding_ball:
            sprint = True
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            past_half = ((attacking_right  and player.x > half_x) or
                         (not attacking_right and player.x < half_x))

            if _in_corner(player.x, player.y, 130) or _near_any_wall(player.x, player.y, 80):
                up, down, left, right, face = _escape_corner(player, attacking_right)

            elif past_half:
                shot_q = _shot_quality(player, goal_x, goal_y, opponents)
                mate, pass_score = _best_pass(player, teammates, opponents, attacking_right)
                pass_clear = (mate is not None and
                              not _path_blocked(player.x, player.y,
                                                mate.x, mate.y, opponents, 30))

                if shot_q > 300:
                    # Aim at the far corner of the goal
                    corner_y = (goal_y - _GOAL_HALF + 30 if player.y > goal_y
                                else goal_y + _GOAL_HALF - 30)
                    face = _norm(goal_x - player.x, corner_y - player.y)
                    player.kick_power = MAX_KICK_POWER

                elif mate is not None and pass_score > 100 and pass_clear:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 12
                    self._run_timer = 35

                elif opp_dist < 110:
                    # Tight space — try a wall bounce
                    bounce = _wall_bounce_aim(player.x, player.y, goal_x, goal_y)
                    if (bounce is not None and
                            not _path_blocked(player.x, player.y,
                                              bounce[0], bounce[1], opponents, 28)):
                        face = _norm(bounce[0] - player.x, bounce[1] - player.y)
                        player.kick_power = MAX_KICK_POWER
                    else:
                        face = _norm(goal_x - player.x, goal_y - player.y)
                        player.kick_power = MAX_KICK_POWER

                else:
                    face = _norm(goal_x - player.x, goal_y - player.y)
                    player.kick_power = MAX_KICK_POWER

                forward = _move_toward(player.x, player.y, goal_x, self._flank_y())
                wall    = _wall_push(player.x, player.y, 60)
                up, down, left, right = _blend(forward, wall, 0.4)

            elif player.kick_cooldown == 0:
                # Before halfway — pass forward or carry
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                pass_blocked = (mate is not None and
                                _path_blocked(player.x, player.y,
                                              mate.x, mate.y, opponents, 30))
                mate_ahead = (mate is not None and
                              ((attacking_right  and mate.x > player.x) or
                               (not attacking_right and mate.x < player.x)))
                if mate is not None and score > 50 and not pass_blocked and mate_ahead:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 10
                    self._run_timer = 30

                forward = _move_toward(player.x, player.y, goal_x, self._flank_y())
                wall    = _wall_push(player.x, player.y, 60)
                up, down, left, right = _blend(forward, wall, 0.5)

        # ── No one has the ball ───────────────────────────────────────────────
        elif holder is None:
            sprint = True
            pred_x = ball_x + ball_vx * 5
            pred_y = ball_y + ball_vy * 5

            if self._run_timer > 0:
                run_x = max(80, min(WIDTH - 80, player.x + dx_goal * 110))
                run_y = self._flank_y()
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0.0)
            else:
                our_d  = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)
                if our_d <= mate_d + 50 or our_d < 130:
                    move = _move_toward(player.x, player.y, pred_x, pred_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.4)
                else:
                    sup_x = half_x + dx_goal * 100
                    sup_y = max(80, min(HEIGHT - 80, self._flank_y() + juke * 60))
                    up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)

            face = _norm(ball_x - player.x, ball_y - player.y)
            kick = False

        # ── Teammate has ball — get open on our flank ─────────────────────────
        elif holder in teammates:
            sup_x = max(100, min(WIDTH - 100, holder.x + dx_goal * 130))
            sup_y = self._flank_y()

            # If another teammate is already at our flank target, mirror across
            for t in teammates:
                if t is not player and t is not holder:
                    if abs(t.y - sup_y) < 120 and abs(t.x - sup_x) < 150:
                        sup_y = HEIGHT - sup_y
                        break

            # If passing lane to us is blocked, offer on the opposite side
            if _path_blocked(holder.x, holder.y, player.x, player.y, opponents, 40):
                sup_y = HEIGHT - sup_y

            sup_y = max(80, min(HEIGHT - 80, sup_y))
            sprint = _dist(player.x, player.y, sup_x, sup_y) > 100
            up, down, left, right = _move_toward(player.x, player.y, sup_x, sup_y)
            wall = _wall_push(player.x, player.y, 50)
            up, down, left, right = _blend((up, down, left, right), wall, 0.4)
            face = _norm(dx_goal, 0.0)
            kick = False

        # ── Opponent has ball — moderate press ────────────────────────────────
        else:
            sprint = True
            press_x = ball_x + ball_vx * 3
            press_y = ball_y + ball_vy * 3
            # Don't chase too deep into own half
            if attacking_right:
                press_x = min(press_x, half_x + 100)
            else:
                press_x = max(press_x, half_x - 100)
            press_x = max(80, min(WIDTH - 80, press_x))
            press_y = max(50, min(HEIGHT - 50, press_y))
            up, down, left, right = _move_toward(player.x, player.y, press_x, press_y)
            wall = _wall_push(player.x, player.y, 50)
            up, down, left, right = _blend((up, down, left, right), wall, 0.5)
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
        self._flank       = None
        self._run_timer   = 0


# ================================================================
#  Claude AI: Defender
# ================================================================

class ClaudeDefenderAI(BaseAI):
    """Disciplined last defender — blocks shot lanes, instant forward release."""

    name = "Claude DEF"

    def __init__(self):
        self._was_kicking = False

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = True
        kick = False
        face = None

        own_goal_x = GOAL_WIDTH if attacking_right else WIDTH - GOAL_WIDTH
        own_goal_y = HEIGHT // 2
        dx_goal    = 1 if attacking_right else -1
        half_x     = WIDTH // 2

        # Home line = own defensive third
        home_line_x = (WIDTH * 0.33 if attacking_right else WIDTH * 0.67)

        holder = None
        for p in teammates + opponents:
            if p.holding_ball:
                holder = p
                break

        # ── Carrying — pass forward immediately ──────────────────────────────
        if player.holding_ball:
            mate, score = _best_pass(player, teammates, opponents, attacking_right)
            pass_clear = (mate is not None and
                          not _path_blocked(player.x, player.y,
                                            mate.x, mate.y, opponents, 30))
            mate_ok = (mate is not None and score > 30 and pass_clear and
                       not _is_claude_gk(mate))

            if mate_ok:
                face = _norm(mate.x - player.x, mate.y - player.y)
                player.kick_power = MAX_KICK_POWER
            else:
                wing_y = 90 if player.y < HEIGHT // 2 else HEIGHT - 90
                norm   = max(1, abs(wing_y - player.y))
                face   = _norm(dx_goal, (wing_y - player.y) / norm * 0.5)
                player.kick_power = MAX_KICK_POWER

            kick = False
            safe_x = own_goal_x + dx_goal * 120
            if attacking_right:
                safe_x = min(safe_x, half_x - 40)
            else:
                safe_x = max(safe_x, half_x + 40)
            up, down, left, right = _move_toward(player.x, player.y, safe_x, own_goal_y)

        # ── Opponent has ball ─────────────────────────────────────────────────
        elif holder in opponents:
            ball_in_own_half = ((attacking_right  and ball_x < half_x) or
                                (not attacking_right and ball_x > half_x))

            if ball_in_own_half:
                # Slide onto the ball-to-goal line to block the shot lane
                btg_x = own_goal_x - ball_x
                btg_y = own_goal_y - ball_y
                btg_d = math.hypot(btg_x, btg_y)
                if btg_d > 0.01:
                    btg_nx = btg_x / btg_d
                    btg_ny = btg_y / btg_d
                    step   = min(btg_d * 0.4, 130.0)
                    block_x = own_goal_x - btg_nx * step
                    block_y = own_goal_y - btg_ny * step
                else:
                    block_x = own_goal_x + dx_goal * 80
                    block_y = own_goal_y

                # Clamp block position to our side of the field
                if attacking_right:
                    block_x = max(own_goal_x + 15, min(half_x - 10, block_x))
                else:
                    block_x = max(half_x + 10, min(own_goal_x - 15, block_x))
                block_y = max(60, min(HEIGHT - 60, block_y))

                up, down, left, right = _move_toward(player.x, player.y, block_x, block_y)
                face = _norm(ball_x - player.x, ball_y - player.y)

            else:
                # Ball far in opponent half — hold defensive line
                hold_x = home_line_x
                if attacking_right:
                    hold_x = min(hold_x, half_x - 60)
                else:
                    hold_x = max(hold_x, half_x + 60)
                hold_y = max(80, min(HEIGHT - 80, ball_y))
                up, down, left, right = _move_toward(player.x, player.y, hold_x, hold_y)
                face = _norm(ball_x - player.x, ball_y - player.y)

        # ── Teammate has ball — sit behind holder, cover space ────────────────
        elif holder in teammates:
            cover_x = holder.x - dx_goal * 110
            if attacking_right:
                cover_x = max(own_goal_x + 30, min(half_x - 30, cover_x))
            else:
                cover_x = max(half_x + 30, min(own_goal_x - 30, cover_x))
            cover_y = max(80, min(HEIGHT - 80, ball_y))
            up, down, left, right = _move_toward(player.x, player.y, cover_x, cover_y)
            face = _norm(ball_x - player.x, ball_y - player.y)
            kick = False

        # ── Loose ball ────────────────────────────────────────────────────────
        else:
            pred_x = ball_x + ball_vx * 5
            pred_y = ball_y + ball_vy * 5
            ball_in_own_half = ((attacking_right  and pred_x < half_x + 60) or
                                (not attacking_right and pred_x > half_x - 60))

            if ball_in_own_half:
                tgt_x = max(BALL_RADIUS, min(WIDTH - BALL_RADIUS, pred_x))
                tgt_y = max(35, min(HEIGHT - 35, pred_y))
                up, down, left, right = _move_toward(player.x, player.y, tgt_x, tgt_y)
                face = _norm(ball_x - player.x, ball_y - player.y)
            else:
                hold_x = home_line_x
                if attacking_right:
                    hold_x = min(hold_x, half_x - 60)
                else:
                    hold_x = max(hold_x, half_x + 60)
                hold_y = max(80, min(HEIGHT - 80, ball_y))
                up, down, left, right = _move_toward(player.x, player.y, hold_x, hold_y)
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


# ================================================================
#  Claude AI: Striker
# ================================================================

class ClaudeStrikerAI(BaseAI):
    """High-pressing scorer — forward runs, decisive box finishing, quick combos."""

    name = "Claude STR"

    def __init__(self):
        self._was_kicking = False
        self._run_timer   = 0
        self._juke_phase  = random.random() * 6.28

    def decide(self, player, ball_x, ball_y, ball_vx, ball_vy,
               teammates, opponents, attacking_right):
        up = down = left = right = False
        sprint = True
        kick = False
        face = None

        goal_x  = WIDTH - GOAL_WIDTH if attacking_right else GOAL_WIDTH
        goal_y  = HEIGHT // 2
        dx_goal = 1 if attacking_right else -1
        half_x  = WIDTH // 2

        self._juke_phase += 0.13
        juke = math.sin(self._juke_phase)
        if self._run_timer > 0:
            self._run_timer -= 1

        holder = None
        for p in teammates + opponents:
            if p.holding_ball:
                holder = p
                break

        # ── Carrying ──────────────────────────────────────────────────────────
        if player.holding_ball:
            opp, opp_dist = _closest_opponent(player.x, player.y, opponents)
            past_half = ((attacking_right  and player.x > half_x) or
                         (not attacking_right and player.x < half_x))
            dist_goal = _dist(player.x, player.y, goal_x, goal_y)
            # Check if inside the opponent's penalty area
            in_opp_box = _in_box(player.x, player.y, not attacking_right)

            # Always escape corners / walls first
            if _in_corner(player.x, player.y, 120) or _near_any_wall(player.x, player.y, 70):
                up, down, left, right, face = _escape_corner(player, attacking_right)

            # Inside opponent box → shoot immediately, no hesitation
            elif in_opp_box or (past_half and dist_goal < 420):
                corner_y = (goal_y - _GOAL_HALF + 25 if player.y > goal_y
                            else goal_y + _GOAL_HALF - 25)
                face = _norm(goal_x - player.x, corner_y - player.y)
                player.kick_power = MAX_KICK_POWER
                forward = _move_toward(player.x, player.y, goal_x, goal_y)
                wall    = _wall_push(player.x, player.y, 50)
                up, down, left, right = _blend(forward, wall, 0.35)

            # Past halfway but not in box — push toward goal or pass
            elif past_half:
                one_v_one = _is_one_v_one(player, goal_x, goal_y, opponents)
                mate, pass_score = _best_pass(player, teammates, opponents, attacking_right)
                pass_clear = (mate is not None and
                              not _path_blocked(player.x, player.y,
                                                mate.x, mate.y, opponents, 28))

                if one_v_one or (opp_dist > 140 and dist_goal < 650):
                    corner_y = (goal_y - _GOAL_HALF + 25 if player.y > goal_y
                                else goal_y + _GOAL_HALF - 25)
                    face = _norm(goal_x - player.x, corner_y - player.y)
                    player.kick_power = MAX_KICK_POWER
                elif (mate is not None and pass_score > 60 and pass_clear and
                      ((attacking_right  and mate.x > player.x) or
                       (not attacking_right and mate.x < player.x))):
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 13
                    self._run_timer = 40
                else:
                    face = _norm(goal_x - player.x, goal_y - player.y)
                    player.kick_power = MAX_KICK_POWER

                forward = _move_toward(player.x, player.y, goal_x, goal_y)
                wall    = _wall_push(player.x, player.y, 55)
                up, down, left, right = _blend(forward, wall, 0.4)

            # Still in own half — pass or carry forward quickly
            elif player.kick_cooldown == 0:
                mate, score = _best_pass(player, teammates, opponents, attacking_right)
                pass_blocked = (mate is not None and
                                _path_blocked(player.x, player.y,
                                              mate.x, mate.y, opponents, 28))
                mate_ahead = (mate is not None and
                              ((attacking_right  and mate.x > player.x) or
                               (not attacking_right and mate.x < player.x)))
                if mate is not None and score > 40 and not pass_blocked and mate_ahead:
                    face = _norm(mate.x - player.x, mate.y - player.y)
                    player.kick_power = 11
                    self._run_timer = 40

                forward = _move_toward(player.x, player.y, goal_x, goal_y)
                wall    = _wall_push(player.x, player.y, 55)
                up, down, left, right = _blend(forward, wall, 0.4)

        # ── No one has the ball ───────────────────────────────────────────────
        elif holder is None:
            pred_x = ball_x + ball_vx * 6
            pred_y = ball_y + ball_vy * 6

            if self._run_timer > 0:
                # Give-and-go forward burst
                run_x = max(80, min(WIDTH - 80, player.x + dx_goal * 120))
                run_y = max(70, min(HEIGHT - 70, HEIGHT // 2 + juke * 90))
                up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
                face = _norm(dx_goal, 0.0)
            else:
                our_d  = _dist(player.x, player.y, pred_x, pred_y)
                mate_d = min((_dist(t.x, t.y, pred_x, pred_y)
                              for t in teammates if t is not player), default=99999)

                if our_d <= mate_d + 60 or our_d < 140:
                    move = _move_toward(player.x, player.y, pred_x, pred_y)
                    wall = _wall_push(player.x, player.y, 50)
                    up, down, left, right = _blend(move, wall, 0.4)
                else:
                    # Float into an advanced attacking position
                    fwd_x = max(80, min(WIDTH - 80, max(half_x, ball_x + dx_goal * 90)))
                    fwd_y = max(70, min(HEIGHT - 70, HEIGHT // 2 + juke * 80))
                    up, down, left, right = _move_toward(player.x, player.y, fwd_x, fwd_y)

            face = _norm(ball_x - player.x, ball_y - player.y)
            kick = False

        # ── Teammate has ball — make a run in behind the defence ─────────────
        elif holder in teammates:
            run_x = max(80, min(WIDTH - 80, holder.x + dx_goal * 170))
            run_y = max(70, min(HEIGHT - 70, HEIGHT // 2 + juke * 120))

            # GK outlet — come deeper to offer a short pass
            if _is_claude_gk(holder):
                run_x = max(80, min(WIDTH - 80, holder.x + dx_goal * 230))

            sprint = _dist(player.x, player.y, run_x, run_y) > 80
            up, down, left, right = _move_toward(player.x, player.y, run_x, run_y)
            wall = _wall_push(player.x, player.y, 50)
            up, down, left, right = _blend((up, down, left, right), wall, 0.4)
            face = _norm(dx_goal, 0.0)
            kick = False

        # ── Opponent has ball — HIGH PRESS everywhere ─────────────────────────
        else:
            press_x = ball_x + ball_vx * 5
            press_y = ball_y + ball_vy * 5
            press_x = max(60, min(WIDTH - 60, press_x))
            press_y = max(50, min(HEIGHT - 50, press_y))
            up, down, left, right = _move_toward(player.x, player.y, press_x, press_y)
            wall = _wall_push(player.x, player.y, 40)
            up, down, left, right = _blend((up, down, left, right), wall, 0.4)
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
        self._run_timer   = 0


# ================================================================
#  Register into the shared AI_REGISTRY from deepseek_ai.py
#  This runs automatically when `import claude_ai` is executed.
# ================================================================

AI_REGISTRY["claude_gk"]  = ClaudeGoalkeeperAI
AI_REGISTRY["claude_pm"]  = ClaudePlaymakerAI
AI_REGISTRY["claude_def"] = ClaudeDefenderAI
AI_REGISTRY["claude_str"] = ClaudeStrikerAI
