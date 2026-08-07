import pygame
import math
import random
from ai import create_ai, cycle_ai, AI_REGISTRY
import custom_ai  # registers "custom_gk", "custom_pm", "custom_def", "custom_str"

pygame.init()

WIDTH, HEIGHT = 1920, 1080
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Soccer Game")

clock = pygame.time.Clock()

# Colors
FIELD_GREEN = (40, 160, 60)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (50, 200, 255)
RED = (255, 80, 80)
ORANGE = (255, 140, 0)

font = pygame.font.SysFont(None, 120)
score_font = pygame.font.SysFont(None, 70)
count_font = pygame.font.SysFont(None, 100)
ai_font = pygame.font.SysFont(None, 24)

# ————————————————————————————————————————————————
#  AI Configuration
# ————————————————————————————————————————————————
#  Set each player to None (keyboard) or an AI instance.
#  Use create_ai("name") to get an instance by name.
#  OLD AIs : "goalkeeper"  "playmaker"  "striker"  "defender"  "trickster"
#  NEW AIs : "custom_gk"   "custom_pm"  "custom_def"  "custom_str"
#  (Press 1-8 during play to toggle AI on/off per player,
#   press 0 to cycle the AI type of every AI-controlled player.)

# ── Blue team (attacking right, HOME) ─────────────────────────────────────────
PLAYER1_AI = create_ai("custom_gk")                    # Blue GK         – WASD
PLAYER3_AI = create_ai("custom_pm")                    # Blue Playmaker1 – IJKL
PLAYER5_AI = create_ai("playmaker")                    # Blue Playmaker2 – TFGH
PLAYER7_AI = create_ai("defender")                   # Blue Defender1  – ZXCV
PLAYER9_AI = create_ai("custom_def")                   # Blue Defender2  – F1-F6

# ── Red team (attacking left) ─────────────────────────────────────────────────
PLAYER2_AI = create_ai("goalkeeper")                    # Red GK          – Arrows
PLAYER4_AI = create_ai("playmaker")                    # Red Playmaker1  – Numpad
PLAYER6_AI = create_ai("playmaker")                    # Red Playmaker2  – Numpad2
PLAYER8_AI = create_ai("custom_def")                   # Red Defender1   – ,./
PLAYER10_AI = create_ai("defender")                  # Red Defender2   – F7-F12

# ── Swap any line to mix old/new AIs, e.g.: ──────────────────────────────────
#   PLAYER3_AI = create_ai("striker")     # old aggressive striker
#   PLAYER7_AI = create_ai("trickster")   # old trickster in place of defender
#   PLAYER1_AI = create_ai("goalkeeper")  # original keeper AI
# ————————————————————————————————————————————————

# Field
GOAL_WIDTH = 40
GOAL_HEIGHT = 250

# Balls
STEAL_COOLDOWN_TIME = 120  # 120 frames = 2 seconds at 60 FPS
steal_cooldown = 0

# Pass interception tracking
last_kicker = None           # player who last kicked the ball
interception_timer = 0       # frames remaining where an interception can happen

ball_radius = 12
ball_x = WIDTH // 2
ball_y = HEIGHT // 2

ball_vx = 0
ball_vy = 0

FRICTION = 0.98

# Kick
MAX_KICK_POWER = 20  # 80% speed
KICK_CHARGE_RATE = 0.5
KICK_COOLDOWN_TIME = 20

# Score
score_left = 0
score_right = 0

# Game timer (120 seconds = 2 minutes at 60 FPS)
GAME_DURATION = 120 * 60
game_timer = GAME_DURATION

timer_font = pygame.font.SysFont(None, 60)


class Player:
    def __init__(self, x, y, color, keys, kick_key, display_name=""):
        self.x = x
        self.y = y
        self.color = color
        self.display_name = display_name

        self.radius = 20

        self.base_speed = 5
        self.sprint_speed = 7

        self.face_x = 1
        self.face_y = 0

        self.keys = keys
        self.kick_key = kick_key

        self.holding_ball = False
        self.steal_shield = 0     # frames of immunity after acquiring the ball
        self.stunned = 0          # frames of immobility after being tackled
        self.slow_timer = 0       # frames of half-speed after intercepting a kick

        self.kick_power = 0
        self.kick_cooldown = 0

    def move(self, pressed):
        dx = 0
        dy = 0

        if pressed[self.keys["up"]]:
            dy -= 1
        if pressed[self.keys["down"]]:
            dy += 1
        if pressed[self.keys["left"]]:
            dx -= 1
        if pressed[self.keys["right"]]:
            dx += 1

        if dx != 0 or dy != 0:
            length = math.hypot(dx, dy)

            dx /= length
            dy /= length

            self.face_x = dx
            self.face_y = dy

        speed = self.base_speed

        if pressed[self.keys["sprint"]]:
            speed = self.sprint_speed

        if self.holding_ball:
            speed *= 0.8

        if self.slow_timer > 0:
            speed *= 0.5

        self.x += dx * speed
        self.y += dy * speed

        self.x = max(
            self.radius,
            min(WIDTH - self.radius, self.x)
        )

        self.y = max(
            self.radius,
            min(HEIGHT - self.radius, self.y)
        )

    def charge_kick(self, pressed):
        if self.kick_cooldown > 0:
            self.kick_cooldown -= 1

        if pressed[self.kick_key] and self.holding_ball and self.kick_cooldown == 0:
            # Only set power if not already set by AI
            if self.kick_power < 0.01:
                self.kick_power = MAX_KICK_POWER

    def release_kick(self, pressed):
        global ball_vx, ball_vy, last_kicker, interception_timer

        if not pressed[self.kick_key] and self.kick_power > 0 and self.holding_ball:
            self.holding_ball = False

            # Shot inaccuracy — higher power = more deviation
            power_ratio = self.kick_power / MAX_KICK_POWER
            angle_error = random.uniform(-0.12, 0.12) * power_ratio  # ±~7° at max power
            cos_err = math.cos(angle_error)
            sin_err = math.sin(angle_error)
            accurate_vx = self.face_x * self.kick_power
            accurate_vy = self.face_y * self.kick_power
            ball_vx = accurate_vx * cos_err - accurate_vy * sin_err
            ball_vy = accurate_vx * sin_err + accurate_vy * cos_err

            self.kick_power = 0
            self.kick_cooldown = KICK_COOLDOWN_TIME

            # Track for interception detection
            last_kicker = self
            interception_timer = 90   # 1.5 sec window

    def pickup_ball(self):
        global ball_vx, ball_vy, last_kicker, interception_timer

        if not self.holding_ball:
            distance = math.hypot(
                ball_x - self.x,
                ball_y - self.y
            )

            if distance < self.radius + ball_radius:
                self.holding_ball = True
                self.steal_shield = 25   # ~0.4 sec immunity

                ball_vx = 0
                ball_vy = 0

                # Interception: opponent picks up the ball right after a kick
                if (last_kicker is not None and
                    interception_timer > 0 and
                    last_kicker is not self and
                    ((self in blue_team) != (last_kicker in blue_team))):
                    # Goalkeeper never gets stunned
                    is_gk = (hasattr(last_kicker, 'ai') and last_kicker.ai is not None
                             and last_kicker.ai.name in ('Goalkeeper', 'Custom GK'))
                    if not is_gk:
                        last_kicker.stunned = 60   # 1 sec stun
                    self.slow_timer = 120      # 2 sec half-speed for interceptor
                last_kicker = None
                interception_timer = 0

    def carry_ball(self):
        global ball_x, ball_y

        if self.holding_ball:
            ball_x = self.x + self.face_x * (self.radius + ball_radius + 5)
            ball_y = self.y + self.face_y * (self.radius + ball_radius + 5)

    def draw(self):
        pygame.draw.circle(
            screen,
            self.color,
            (int(self.x), int(self.y)),
            self.radius
        )


player1 = Player(
    GOAL_WIDTH + 20,
    HEIGHT // 2,
    BLUE,
    {
        "up": pygame.K_w,
        "down": pygame.K_s,
        "left": pygame.K_a,
        "right": pygame.K_d,
        "sprint": pygame.K_LSHIFT
    },
    pygame.K_SPACE,
    "Raya"
)

player2 = Player(
    WIDTH - GOAL_WIDTH - 20,
    HEIGHT // 2,
    RED,
    {
        "up": pygame.K_UP,
        "down": pygame.K_DOWN,
        "left": pygame.K_LEFT,
        "right": pygame.K_RIGHT,
        "sprint": pygame.K_RSHIFT
    },
    pygame.K_0,
    "Courtois"
)

player3 = Player(
    280,
    HEIGHT // 2 - 60,
    BLUE,
    {
        "up": pygame.K_i,
        "down": pygame.K_k,
        "left": pygame.K_j,
        "right": pygame.K_l,
        "sprint": pygame.K_u
    },
    pygame.K_o,
    "Olise"
)

player4 = Player(
    WIDTH - 280,
    HEIGHT // 2 + 60,
    RED,
    {
        "up": pygame.K_KP8,
        "down": pygame.K_KP5,
        "left": pygame.K_KP4,
        "right": pygame.K_KP6,
        "sprint": pygame.K_KP7
    },
    pygame.K_KP9,
    "Kane"
)

player5 = Player(
    280,
    HEIGHT // 2,
    BLUE,
    {
        "up": pygame.K_t,
        "down": pygame.K_g,
        "left": pygame.K_f,
        "right": pygame.K_h,
        "sprint": pygame.K_r
    },
    pygame.K_y,
    "Bellingham"
)

player6 = Player(
    WIDTH - 280,
    HEIGHT // 2,
    RED,
    {
        "up": pygame.K_KP1,
        "down": pygame.K_KP2,
        "left": pygame.K_KP3,
        "right": pygame.K_KP_ENTER,
        "sprint": pygame.K_KP_PLUS
    },
    pygame.K_KP_MINUS,
    "Mbappe"
)

player7 = Player(
    280,
    HEIGHT // 2 + 60,
    BLUE,
    {
        "up": pygame.K_z,
        "down": pygame.K_x,
        "left": pygame.K_c,
        "right": pygame.K_v,
        "sprint": pygame.K_b
    },
    pygame.K_n,
    "Saliba"
)

player8 = Player(
    WIDTH - 280,
    HEIGHT // 2 - 60,
    RED,
    {
        "up": pygame.K_COMMA,
        "down": pygame.K_PERIOD,
        "left": pygame.K_SEMICOLON,
        "right": pygame.K_SLASH,
        "sprint": pygame.K_QUOTE
    },
    pygame.K_LEFTBRACKET,
    "Cubarsi"
)

player9 = Player(
    200,
    HEIGHT // 2 + 90,
    BLUE,
    {
        "up": pygame.K_F1,
        "down": pygame.K_F2,
        "left": pygame.K_F3,
        "right": pygame.K_F4,
        "sprint": pygame.K_F5
    },
    pygame.K_F6,
    "Gabriel"
)

player10 = Player(
    WIDTH - 200,
    HEIGHT // 2 - 90,
    RED,
    {
        "up": pygame.K_F7,
        "down": pygame.K_F8,
        "left": pygame.K_F9,
        "right": pygame.K_F10,
        "sprint": pygame.K_F11
    },
    pygame.K_F12,
    "Araujo"
)

blue_team = [player1, player3, player5, player7, player9]
red_team = [player2, player4, player6, player8, player10]
all_players = [player1, player2, player3, player4, player5, player6, player7, player8, player9, player10]

# ——— Assign AIs to players ———
player1.ai = PLAYER1_AI
player2.ai = PLAYER2_AI
player3.ai = PLAYER3_AI
player4.ai = PLAYER4_AI
player5.ai = PLAYER5_AI
player6.ai = PLAYER6_AI
player7.ai = PLAYER7_AI
player8.ai = PLAYER8_AI
player9.ai = PLAYER9_AI
player10.ai = PLAYER10_AI


def ai_decision_to_keys(decision, player):
    """Convert an AI decision dict into a pressed-keys dict keyed by the
    player's actual pygame keycodes so the existing Player methods work."""
    keys = {}
    for action in ("up", "down", "left", "right", "sprint"):
        keys[player.keys[action]] = decision.get(action, False)

    kick_wanted = decision.get("kick", False)
    keys[player.kick_key] = (kick_wanted is True)  # held
    return keys


def reset_positions(kicking_team=None):
    """Reset all players and the ball.  `kicking_team` is "blue", "red", or None."""
    global ball_x, ball_y
    global ball_vx, ball_vy
    global last_kicker, interception_timer
    global kickoff_timer, kickoff_passer

    player1.x = GOAL_WIDTH + 20
    player1.y = HEIGHT // 2

    player2.x = WIDTH - GOAL_WIDTH - 20
    player2.y = HEIGHT // 2

    if kicking_team is None:
        # ── Normal play positions (no kickoff) ──────────────────────────
        # Blue outfield – spread across the centre-third
        player3.x = 350
        player3.y = HEIGHT // 2 - 60

        player5.x = 350
        player5.y = HEIGHT // 2 + 60

        player7.x = 240
        player7.y = HEIGHT // 2 + 90

        player9.x = 200
        player9.y = HEIGHT // 2 - 50

        # Red outfield – mirror
        player4.x = WIDTH - 350
        player4.y = HEIGHT // 2 + 60

        player6.x = WIDTH - 350
        player6.y = HEIGHT // 2 - 60

        player8.x = WIDTH - 240
        player8.y = HEIGHT // 2 - 90

        player10.x = WIDTH - 200
        player10.y = HEIGHT // 2 + 50

    else:
        # ── Kickoff formation ──────────────────────────────────────────
        # Both teams line up in their own half.
        #  • 2 defenders on a line parallel to halfway (same x, spaced vertically)
        #  • 2 attackers in front, also on a line parallel to the defenders
        #  • The kickoff taker stands alone at the centre spot.

        DEF_X  = 280            # how deep the defensive line sits
        ATT_X  = 550            # attacking-midfield line (in front of defenders)
        DEF_Y  = 170            # vertical spacing for defenders
        ATT_Y  = 100            # vertical spacing for attackers

        if kicking_team == "blue":
            # ── Blue kicks off ───────────────────────────────────────
            # Blue defensive line
            player7.x = DEF_X
            player7.y = HEIGHT // 2 - DEF_Y
            player9.x = DEF_X
            player9.y = HEIGHT // 2 + DEF_Y

            # Blue attacker (the non-kicking playmaker)
            player5.x = ATT_X
            player5.y = HEIGHT // 2 + ATT_Y

            # Blue kickoff taker at the centre spot
            player3.x = WIDTH // 2
            player3.y = HEIGHT // 2

            # Red defensive line (mirrored)
            player8.x  = WIDTH - DEF_X
            player8.y  = HEIGHT // 2 - DEF_Y
            player10.x = WIDTH - DEF_X
            player10.y = HEIGHT // 2 + DEF_Y

            # Red attackers
            player4.x = WIDTH - ATT_X
            player4.y = HEIGHT // 2 - ATT_Y
            player6.x = WIDTH - ATT_X
            player6.y = HEIGHT // 2 + ATT_Y

        else:  # kicking_team == "red"
            # ── Red kicks off ─────────────────────────────────────────
            # Blue defensive line
            player7.x = DEF_X
            player7.y = HEIGHT // 2 - DEF_Y
            player9.x = DEF_X
            player9.y = HEIGHT // 2 + DEF_Y

            # Blue attackers
            player3.x = ATT_X
            player3.y = HEIGHT // 2 - ATT_Y
            player5.x = ATT_X
            player5.y = HEIGHT // 2 + ATT_Y

            # Red defensive line (mirrored)
            player8.x  = WIDTH - DEF_X
            player8.y  = HEIGHT // 2 - DEF_Y
            player10.x = WIDTH - DEF_X
            player10.y = HEIGHT // 2 + DEF_Y

            # Red attacker (the non-kicking playmaker)
            player6.x = WIDTH - ATT_X
            player6.y = HEIGHT // 2 - ATT_Y

            # Red kickoff taker at the centre spot
            player4.x = WIDTH // 2
            player4.y = HEIGHT // 2

    ball_x = WIDTH // 2
    ball_y = HEIGHT // 2

    ball_vx = 0
    ball_vy = 0

    last_kicker = None
    interception_timer = 0

    for p in all_players:
        p.holding_ball = False
        p.kick_power = 0
        p.kick_cooldown = 0
        p.steal_shield = 0
        p.stunned = 0
        p.slow_timer = 0

    # ── Kickoff: the kicking team's playmaker stands at the centre spot ────
    if kicking_team == "blue":
        player3.holding_ball = True
        player3.steal_shield = 40
        kickoff_timer = 25
        kickoff_passer = player3
    elif kicking_team == "red":
        player4.holding_ball = True
        player4.steal_shield = 40
        kickoff_timer = 25
        kickoff_passer = player4
    else:
        kickoff_timer = 0
        kickoff_passer = None


def draw_field():
    screen.fill(FIELD_GREEN)

    pygame.draw.rect(
        screen,
        WHITE,
        (0, 0, WIDTH, HEIGHT),
        5
    )

    pygame.draw.line(
        screen,
        WHITE,
        (WIDTH // 2, 0),
        (WIDTH // 2, HEIGHT),
        5
    )

    pygame.draw.circle(
        screen,
        WHITE,
        (WIDTH // 2, HEIGHT // 2),
        120,
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (0, HEIGHT // 2 - 200, 250, 400),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (WIDTH - 250, HEIGHT // 2 - 200, 250, 400),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (0, HEIGHT // 2 - GOAL_HEIGHT // 2, GOAL_WIDTH, GOAL_HEIGHT),
        5
    )

    pygame.draw.rect(
        screen,
        WHITE,
        (WIDTH - GOAL_WIDTH, HEIGHT // 2 - GOAL_HEIGHT // 2, GOAL_WIDTH, GOAL_HEIGHT),
        5
    )

running = True

# Start with countdown so the first kickoff happens after "3…2…1…GO!"
game_state = "countdown"
countdown_timer = 180   # 3 seconds at 60 FPS

goal_timer = 0
next_kicking_team = "blue"  # who kicks off after the countdown ends

# Kickoff script — a playmaker passes back to a defender
kickoff_timer = 0       # frames remaining in scripted kickoff
kickoff_passer = None   # the PM executing the scripted pass-back

# Teleport everyone to their starting spots NOW so the countdown shows the
# kickoff taker already standing at the centre circle with the ball.
reset_positions(kicking_team="blue")

# ── Replay system ─────────────────────────────────────────────────
REPLAY_MAX_FRAMES = 60          # record last 1 second at 60 FPS
REPLAY_SPEED_DIV = 5            # 25% speed → each recorded frame shown 4 times
replay_buffer = []              # list of dicts, newest at the end
replay_index = 0                # which recorded frame we're showing
replay_subframe = 0             # 0..REPLAY_SPEED_DIV-1, counts how long we've shown current frame
replay_goal_team = None         # "left" or "right" — who scored


def record_frame():
    """Snapshot every player and the ball into the circular replay buffer."""
    global replay_buffer
    frame = {
        "players": [],
        "ball": (ball_x, ball_y),
    }
    for p in all_players:
        frame["players"].append({
            "x": p.x, "y": p.y,
            "face_x": p.face_x, "face_y": p.face_y,
            "holding": p.holding_ball,
            "stunned": p.stunned,
            "color": p.color,
            "name": p.display_name,
        })
    replay_buffer.append(frame)
    # Keep only the last N frames
    if len(replay_buffer) > REPLAY_MAX_FRAMES:
        replay_buffer.pop(0)


def goal_scored(team):
    global score_left, score_right
    global game_state, goal_timer
    global replay_index, replay_subframe, replay_goal_team
    global next_kicking_team

    if team == "left":
        score_left += 1
        next_kicking_team = "red"   # blue scored → red kicks off
    else:
        score_right += 1
        next_kicking_team = "blue"  # red scored → blue kicks off

    # Capture replay buffer before resetting
    replay_index = 0
    replay_subframe = 0
    replay_goal_team = team
    game_state = "replay"

    # Reset positions but DON'T set up kickoff yet — that happens after the
    # countdown.  The ball just sits at centre during the replay + goal pause.
    reset_positions(kicking_team=None)

    # Reset AI state
    for p in all_players:
        if p.ai is not None:
            p.ai.reset()


while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.KEYDOWN:
            # ——— AI toggle keys ————————————————————————
            #  1-6 : toggle AI on/off for that player
            #  0   : cycle AI type (for players that have AI on)
            # ————————————————————————————————————————————
            if event.key == pygame.K_1:
                player1.ai = cycle_ai(player1.ai)
            elif event.key == pygame.K_2:
                player2.ai = cycle_ai(player2.ai)
            elif event.key == pygame.K_3:
                player3.ai = cycle_ai(player3.ai)
            elif event.key == pygame.K_4:
                player4.ai = cycle_ai(player4.ai)
            elif event.key == pygame.K_5:
                player5.ai = cycle_ai(player5.ai)
            elif event.key == pygame.K_6:
                player6.ai = cycle_ai(player6.ai)
            elif event.key == pygame.K_7:
                player7.ai = cycle_ai(player7.ai)
            elif event.key == pygame.K_8:
                player8.ai = cycle_ai(player8.ai)
            elif event.key == pygame.K_9:
                player9.ai = cycle_ai(player9.ai)
            elif event.key == pygame.K_0:
                player10.ai = cycle_ai(player10.ai)
            elif event.key == pygame.K_MINUS:
                # Cycle AI type for every AI-controlled player
                for p in all_players:
                    if p.ai is not None:
                        p.ai = cycle_ai(p.ai)

    keys = pygame.key.get_pressed()

    if game_state == "playing" and game_timer > 0:

        # Game timer
        game_timer -= 1

        # ── Kickoff script: forced pass to the nearest teammate ────────
        if kickoff_timer > 0 and kickoff_passer is not None:
            kickoff_timer -= 1
            p = kickoff_passer

            # Find the nearest teammate (excluding goalkeepers and self)
            teammates = blue_team if p in blue_team else red_team
            best = None
            best_dist = float("inf")
            for t in teammates:
                if t is p:
                    continue
                # Skip goalkeepers — pass to an outfield player
                if t is player1 or t is player2:
                    continue
                d = math.hypot(t.x - p.x, t.y - p.y)
                if d < best_dist:
                    best_dist = d
                    best = t

            if best is not None:
                target_x = best.x
                target_y = best.y
                dx = target_x - p.x
                dy = target_y - p.y
                dist = math.hypot(dx, dy)
                if dist > 0.01:
                    p.face_x = dx / dist
                    p.face_y = dy / dist
            if kickoff_timer > 15:
                p.kick_power = 7  # soft pass
            elif kickoff_timer == 0 and p.holding_ball:
                # Execute the forced pass — player has no control
                p.holding_ball = False
                ball_vx = p.face_x * p.kick_power
                ball_vy = p.face_y * p.kick_power
                p.kick_power = 0
                p.kick_cooldown = KICK_COOLDOWN_TIME
                last_kicker = p
                interception_timer = 90
                kickoff_passer = None
            # Passer is frozen at the centre spot until the pass is released
            p.move({k: False for k in p.keys.values()})

        # Update players
        for p in all_players:
            # Skip AI for the kickoff passer during scripted sequence
            if p is kickoff_passer and kickoff_timer > 0:
                continue
            if p.ai is not None:
                # ——— AI-controlled ————————————————
                teammates = blue_team if p in blue_team else red_team
                opponents = red_team if p in blue_team else blue_team
                attacking_right = (p in blue_team)

                decision = p.ai.decide(
                    p, ball_x, ball_y, ball_vx, ball_vy,
                    teammates, opponents, attacking_right,
                )

                ai_keys = ai_decision_to_keys(decision, p)

                p.move(ai_keys)

                # Override face direction for kick aiming
                face = decision.get("face")
                if face is not None:
                    p.face_x, p.face_y = face

                p.charge_kick(ai_keys)
                p.release_kick(ai_keys)
            else:
                # ——— Keyboard-controlled ———————————
                p.move(keys)
                p.charge_kick(keys)
                p.release_kick(keys)

        if steal_cooldown > 0:
            steal_cooldown -= 1

        # Tick down shields, stuns, slow, and interception window
        for p in all_players:
            if p.steal_shield > 0:
                p.steal_shield -= 1
            if p.stunned > 0:
                p.stunned -= 1
            if p.slow_timer > 0:
                p.slow_timer -= 1
        if interception_timer > 0:
            interception_timer -= 1

        # ——— Player collision — push apart overlapping players ———
        # Stunned players are ghosts (no collision).
        # Teammates get a softer push so they don't fight each other.
        for i in range(len(all_players)):
            for j in range(i + 1, len(all_players)):
                a = all_players[i]
                b = all_players[j]
                if a.stunned > 0 or b.stunned > 0:
                    continue   # stunned players don't collide
                dx = a.x - b.x
                dy = a.y - b.y
                dist = math.hypot(dx, dy)
                min_dist = a.radius + b.radius
                if dist < min_dist and dist > 0.01:
                    overlap = min_dist - dist
                    nx = dx / dist
                    ny = dy / dist
                    # Same team → light push.  Opponents → full push.
                    same_team = (a in blue_team and b in blue_team) or (a in red_team and b in red_team)
                    force = 0.15 if same_team else 0.5
                    a.x += nx * overlap * force
                    a.y += ny * overlap * force
                    b.x -= nx * overlap * force
                    b.y -= ny * overlap * force
                elif dist < 0.01:
                    a.x += 1
                    b.x -= 1

        # Ball pickup — closest player gets it, not first in list order
        if not any(p.holding_ball for p in all_players):
            # Sort by distance to ball so the closest player always wins
            # GKs always eligible; others need to not be stunned
            candidates = [p for p in all_players
                          if p.stunned == 0 or (hasattr(p, 'ai') and p.ai is not None
                                                and p.ai.name in ('Goalkeeper', 'Custom GK'))]
            candidates.sort(key=lambda p: math.hypot(ball_x - p.x, ball_y - p.y))
            for p in candidates:
                p.pickup_ball()
                if p.holding_ball:
                    break   # ball claimed, stop

        # Ball carrying
        for p in all_players:
            p.carry_ball()

        # ── Prevent own-goal: non-GK ball-carrier cannot enter own net ────
        for p in all_players:
            if p.holding_ball and p is not player1 and p is not player2:
                in_own_goal_y = abs(p.y - HEIGHT // 2) < GOAL_HEIGHT // 2 + p.radius
                if p in blue_team:
                    # Blue defends left — can't enter own goal on the left
                    if p.x < GOAL_WIDTH + p.radius and in_own_goal_y:
                        p.x = GOAL_WIDTH + p.radius
                else:
                    # Red defends right — can't enter own goal on the right
                    if p.x > WIDTH - GOAL_WIDTH - p.radius and in_own_goal_y:
                        p.x = WIDTH - GOAL_WIDTH - p.radius

        # Steal — pops the ball loose instead of transferring possession.
        # This prevents ping-pong A→B→A→B stealing.
        # Only works from the FRONT — opponent must be on the ball-side of the holder.
        if steal_cooldown == 0:
            for holder in all_players:
                if holder.holding_ball and holder.steal_shield == 0:
                    opponents = red_team if holder in blue_team else blue_team
                    for opponent in opponents:
                        if opponent.stunned > 0:
                            continue   # stunned players can't tackle
                        # Must not be directly behind the holder
                        to_opp_x = opponent.x - holder.x
                        to_opp_y = opponent.y - holder.y
                        dot = holder.face_x * to_opp_x + holder.face_y * to_opp_y
                        if dot <= -0.5:   # only block if well behind
                            continue

                        distance = math.hypot(ball_x - opponent.x, ball_y - opponent.y)
                        if distance < opponent.radius + ball_radius + 4:
                            # Pop the ball loose — away from both players
                            mid_x = (holder.x + opponent.x) / 2
                            mid_y = (holder.y + opponent.y) / 2
                            pop_dir_x = ball_x - mid_x
                            pop_dir_y = ball_y - mid_y
                            pop_dist = math.hypot(pop_dir_x, pop_dir_y)
                            if pop_dist < 0.01:
                                pop_dir_x = 1
                                pop_dir_y = 0
                                pop_dist = 1

                            holder.holding_ball = False
                            ball_vx = (pop_dir_x / pop_dist) * 8
                            ball_vy = (pop_dir_y / pop_dist) * 8
                            steal_cooldown = STEAL_COOLDOWN_TIME
                            break
                    if steal_cooldown > 0:
                        break

                
        # Ball movement
        if not any(p.holding_ball for p in all_players):
            ball_x += ball_vx
            ball_y += ball_vy

            ball_vx *= FRICTION
            ball_vy *= FRICTION

            if abs(ball_vx) < 0.05:
                ball_vx = 0

            if abs(ball_vy) < 0.05:
                ball_vy = 0

        # Goal detection — only counts if ball enters from the field side
        in_goal_y = abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2

        if ball_x < GOAL_WIDTH and in_goal_y:
            if ball_vx < 0:  # ball moving into goal from field
                goal_scored("right")

        if ball_x > WIDTH - GOAL_WIDTH and in_goal_y:
            if ball_vx > 0:  # ball moving into goal from field
                goal_scored("left")

        # Field collision — allow ball through goal area
        if ball_y <= ball_radius:
            ball_y = ball_radius
            ball_vy *= -1

        if ball_y >= HEIGHT - ball_radius:
            ball_y = HEIGHT - ball_radius
            ball_vy *= -1

        # Side walls: only bounce if NOT in the goal area
        if ball_x <= ball_radius and not in_goal_y:
            ball_x = ball_radius
            ball_vx *= -1

        if ball_x >= WIDTH - ball_radius and not in_goal_y:
            ball_x = WIDTH - ball_radius
            ball_vx *= -1

        # Record frame for goal replay (only if still playing — goal_scored may have fired)
        if game_state == "playing":
            record_frame()

    elif game_state == "replay":
        # Slow-motion replay: advance one recorded frame every REPLAY_SPEED_DIV ticks
        replay_subframe += 1
        if replay_subframe >= REPLAY_SPEED_DIV:
            replay_subframe = 0
            replay_index += 1
        if replay_index >= len(replay_buffer):
            # Replay finished → normal goal sequence
            game_state = "goal"
            goal_timer = 180

    elif game_state == "goal":

        goal_timer -= 1

        if goal_timer <= 0:
            game_state = "countdown"
            countdown_timer = 300
            # Teleport the kickoff taker to the centre circle right now,
            # so they're visible there during the "3…2…1…" countdown.
            reset_positions(kicking_team=next_kicking_team)

    elif game_state == "countdown":

        countdown_timer -= 1

        if countdown_timer <= 0:
            game_state = "playing"
            # Kickoff script takes over — passer is already at the centre spot

    # Draw field
    draw_field()

    # ── Draw players & ball (replay or live) ──────────────────────────
    if game_state == "replay" and replay_index < len(replay_buffer):
        frame = replay_buffer[replay_index]
        # Draw recorded player positions
        for pd in frame["players"]:
            pygame.draw.circle(
                screen,
                pd["color"],
                (int(pd["x"]), int(pd["y"])),
                20,  # player radius
            )
            name_label = ai_font.render(pd["name"], True, WHITE)
            screen.blit(
                name_label,
                (pd["x"] - name_label.get_width() // 2, pd["y"] - 20 - 22),
            )
            if pd["stunned"] > 0:
                stun_label = ai_font.render("!", True, (255, 80, 80))
                screen.blit(stun_label,
                            (pd["x"] - stun_label.get_width() // 2, pd["y"] - 20 - 38))
        # Draw recorded ball position
        pygame.draw.circle(
            screen,
            ORANGE,
            (int(frame["ball"][0]), int(frame["ball"][1])),
            ball_radius
        )
    else:
        for p in all_players:
            p.draw()
            # Player name
            name_label = ai_font.render(p.display_name, True, WHITE)
            screen.blit(
                name_label,
                (p.x - name_label.get_width() // 2, p.y - p.radius - 22),
            )
            # Stunned indicator — just a mark showing they can't pick up the ball
            if p.stunned > 0:
                stun_label = ai_font.render("!", True, (255, 80, 80))
                screen.blit(stun_label,
                            (p.x - stun_label.get_width() // 2, p.y - p.radius - 38))

        # Draw ball
        pygame.draw.circle(
            screen,
            ORANGE,
            (int(ball_x), int(ball_y)),
            ball_radius
        )

        # Kick bar for any player holding the ball
        for p in all_players:
            if p.holding_ball:
                bar_width = 60
                bar_height = 8

                bar_x = p.x - bar_width / 2
                bar_y = p.y + p.radius + 10

                pygame.draw.rect(
                    screen,
                    BLACK,
                    (bar_x, bar_y, bar_width, bar_height)
                )

                power = p.kick_power / MAX_KICK_POWER
                power = min(power, 1)

                if power < 0.5:
                    r = int(255 * power * 2)
                    g = 255
                else:
                    r = 255
                    g = int(255 * (1 - (power - 0.5) * 2))

                pygame.draw.rect(
                    screen,
                    (r, g, 0),
                    (bar_x, bar_y, bar_width * power, bar_height)
                )

    # Score
    score_text = score_font.render(
        f"{score_left} - {score_right}",
        True,
        BLACK
    )

    screen.blit(
        score_text,
        (40, 30)
    )

    # Timer
    seconds_left = max(0, math.ceil(game_timer / 60))
    timer_color = WHITE if seconds_left > 10 else RED
    timer_text = timer_font.render(
        f"{seconds_left}s",
        True,
        timer_color
    )
    screen.blit(
        timer_text,
        (WIDTH - timer_text.get_width() - 40, 30)
    )

    # Game Over
    if game_timer <= 0 and game_state == "playing":
        over_text = font.render("GAME OVER", True, BLACK)
        screen.blit(
            over_text,
            (
                WIDTH // 2 - over_text.get_width() // 2,
                HEIGHT // 2 - over_text.get_height() // 2 - 80,
            )
        )

    # Replay overlay
    if game_state == "replay":
        replay_text = font.render("REPLAY", True, (255, 255, 255))
        # Dark semi-transparent backdrop for readability
        backdrop = pygame.Surface((replay_text.get_width() + 40, replay_text.get_height() + 20))
        backdrop.set_alpha(140)
        backdrop.fill((0, 0, 0))
        screen.blit(backdrop,
                    (WIDTH // 2 - backdrop.get_width() // 2,
                     HEIGHT // 2 - backdrop.get_height() // 2 - 80))
        screen.blit(
            replay_text,
            (WIDTH // 2 - replay_text.get_width() // 2,
             HEIGHT // 2 - replay_text.get_height() // 2 - 80)
        )
    # Goal message
    if game_state == "goal":

        text = font.render(
            "GOAL!",
            True,
            BLACK
        )

        screen.blit(
            text,
            (
                WIDTH // 2 - text.get_width() // 2,
                HEIGHT // 2 - text.get_height() // 2
            )
        )

    # Countdown
    if game_state == "countdown":

        seconds = math.ceil(countdown_timer / 60)

        text = count_font.render(
            str(seconds),
            True,
            BLACK
        )

        screen.blit(
            text,
            (
                WIDTH // 2 - text.get_width() // 2,
                HEIGHT // 2 - text.get_height() // 2
            )
        )

    pygame.display.flip()

pygame.quit()