import pygame
import math
import random
from ai import create_ai
import custom_ai  # registers "custom_gk", "custom_pm", "custom_def", "custom_str"
import gemini_ai  # registers "gemini_gk", "gemini_pm", "gemini_def", "gemini_str"

pygame.init()

WIDTH, HEIGHT = 1912, 1045
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Soccer Game")

clock = pygame.time.Clock()

# Load player avatar images
_IMG_SIZE = 44

def _make_circular(img):
    """Crop an image to a circle using an alpha mask."""
    size = img.get_width()
    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    pygame.draw.circle(mask, (255, 255, 255, 255), (size // 2, size // 2), size // 2)
    result = img.copy()
    result.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return result

_claude_img = pygame.image.load("images/claude.png").convert_alpha()
_claude_img = pygame.transform.smoothscale(_claude_img, (_IMG_SIZE, _IMG_SIZE))
_claude_img = _make_circular(_claude_img)

_deepseek_img = pygame.image.load("images/deepseek.png").convert_alpha()
_deepseek_img = pygame.transform.smoothscale(_deepseek_img, (_IMG_SIZE, _IMG_SIZE))
_deepseek_img = _make_circular(_deepseek_img)

try:
    _gemini_img = pygame.image.load("images/gemini.png").convert_alpha()
    _gemini_img = pygame.transform.smoothscale(_gemini_img, (_IMG_SIZE, _IMG_SIZE))
    _gemini_img = _make_circular(_gemini_img)
except Exception:
    _gemini_img = _deepseek_img

def _player_image(player):
    """Return the avatar image for a player based on their AI type."""
    if player.ai is None:
        return None
    name = getattr(player.ai, "name", "")
    if name.startswith("Gemini"):
        return _gemini_img
    if name.startswith("Custom"):
        return _claude_img
    return _deepseek_img

# set up sound effects
pygame.mixer.init()

# ambient crowd murmur, loops the whole game at 30%
_crowd = pygame.mixer.Sound("sounds/crowd.mp3")
_crowd.set_volume(0.20)
_crowd_ch = pygame.mixer.Channel(0)
_crowd_ch.play(_crowd, loops=-1, fade_ms=600)

# goal event sting, plays on top of ambient
_goal_snd = pygame.mixer.Sound("sounds/goal.mp3")
_goal_snd.set_volume(0.0)

# kick sound, throttled to once every 0.25s
_kick_snd = pygame.mixer.Sound("sounds/kick.mp3")
_kick_snd.set_volume(0.60)
_kick_cooldown = 0

def _kick():
    """Play kick.mp3, but at most once every 0.25 s (15 frames)."""
    global _kick_cooldown
    if _kick_cooldown <= 0:
        _kick_snd.play()
        _kick_cooldown = 15

_goal_vol   = 0.0     # current event volume
_goal_decay = 0.0     # per-frame drop toward silence

def _event_sound(peak, seconds):
    """Play goal.mp3 at *peak* volume, then linearly decay to silence
    over *seconds*.  Stops any previous event playback first."""
    global _goal_vol, _goal_decay
    _goal_snd.stop()
    _goal_vol = peak
    _goal_decay = peak / max(1, seconds * 60)
    _goal_snd.set_volume(_goal_vol)
    _goal_snd.play()

def _event_tick():
    """Call once per frame — decay event volume and kick cooldown."""
    global _goal_vol, _kick_cooldown
    if _goal_vol > 0.0:
        _goal_vol = max(0.0, _goal_vol - _goal_decay)
        _goal_snd.set_volume(_goal_vol)
    if _kick_cooldown > 0:
        _kick_cooldown -= 1

# colors
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

# AI configuration
# every player starts AI-controlled.  press 1 to add a blue human player
# (WASD, LShift sprint, Space shoot) or 2 to add a red human player
# (arrow keys, RShift sprint, Ctrl shoot).
# original AIs: "goalkeeper" "playmaker" "striker" "defender" "trickster"
# custom AIs:   "custom_gk" "custom_pm" "custom_def" "custom_str"
# gemini AIs:   "gemini_gk" "gemini_pm" "gemini_def" "gemini_str"

# blue team (attacks right) — Gemini AI Team
PLAYER1_AI = create_ai("gemini_gk")    # blue GK
PLAYER3_AI = create_ai("gemini_pm")    # blue PM
PLAYER5_AI = create_ai("gemini_str")   # blue STR
PLAYER7_AI = create_ai("gemini_def")   # blue DEF1
PLAYER9_AI = create_ai("gemini_def")   # blue DEF2


# red team (attacks left) — Custom / Original AI mix
PLAYER2_AI = create_ai("goalkeeper")   # red GK
PLAYER4_AI = create_ai("playmaker")    # red PM
PLAYER6_AI = create_ai("playmaker")   # red STR
PLAYER8_AI = create_ai("defender")   # red DEF1
PLAYER10_AI = create_ai("defender")    # red DEF2

# swap any line to mix AIs, e.g.:
#   PLAYER3_AI = create_ai("striker")
#   PLAYER7_AI = create_ai("trickster")
#   PLAYER1_AI = create_ai("goalkeeper")

# field dimensions
GOAL_WIDTH = 40
GOAL_HEIGHT = 250

# ball and steal settings
STEAL_COOLDOWN_TIME = 120
steal_cooldown = 0

# pass interception tracking
last_kicker = None
interception_timer = 0

ball_radius = 12
ball_x = WIDTH // 2
ball_y = HEIGHT // 2

ball_vx = 0
ball_vy = 0

FRICTION = 0.98

# kick settings
MAX_KICK_POWER = 20
KICK_CHARGE_RATE = 2.0
KICK_COOLDOWN_TIME = 20

# score variables
score_left = 0
score_right = 0

# game timer, 2 minutes at 60 fps
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
        self.steal_shield = 0
        self.stunned = 0
        self.slow_timer = 0

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
            self.kick_power = min(MAX_KICK_POWER, self.kick_power + KICK_CHARGE_RATE)

    def release_kick(self, pressed):
        global ball_vx, ball_vy, last_kicker, interception_timer

        if not pressed[self.kick_key] and self.kick_power > 0 and self.holding_ball:
            self.holding_ball = False

            # shot inaccuracy, higher power = more deviation
            power_ratio = self.kick_power / MAX_KICK_POWER
            angle_error = random.uniform(-0.12, 0.12) * power_ratio
            cos_err = math.cos(angle_error)
            sin_err = math.sin(angle_error)
            accurate_vx = self.face_x * self.kick_power
            accurate_vy = self.face_y * self.kick_power
            ball_vx = accurate_vx * cos_err - accurate_vy * sin_err
            ball_vy = accurate_vx * sin_err + accurate_vy * cos_err

            _kick()

            self.kick_power = 0
            self.kick_cooldown = KICK_COOLDOWN_TIME

            # track for interception detection
            last_kicker = self
            interception_timer = 90

    def pickup_ball(self):
        global ball_vx, ball_vy, last_kicker, interception_timer

        if not self.holding_ball:
            distance = math.hypot(
                ball_x - self.x,
                ball_y - self.y
            )

            if distance < self.radius + ball_radius:
                self.holding_ball = True
                self.steal_shield = 25

                ball_vx = 0
                ball_vy = 0

                # interception: opponent claims the ball right after a kick
                if (last_kicker is not None and
                    interception_timer > 0 and
                    last_kicker is not self and
                    ((self in blue_team) != (last_kicker in blue_team))):
                    # goalkeeper never gets stunned on interceptions
                    is_gk = (hasattr(last_kicker, 'ai') and last_kicker.ai is not None
                             and last_kicker.ai.name in ('Goalkeeper', 'Custom GK'))
                    if not is_gk:
                        last_kicker.stunned = 60
                    self.slow_timer = 120
                last_kicker = None
                interception_timer = 0

    def carry_ball(self):
        global ball_x, ball_y

        if self.holding_ball:
            ball_x = self.x + self.face_x * (self.radius + ball_radius + 5)
            ball_y = self.y + self.face_y * (self.radius + ball_radius + 5)

    def draw(self):
        img = _player_image(self)
        if img is not None:
            screen.blit(img, (int(self.x - _IMG_SIZE // 2), int(self.y - _IMG_SIZE // 2)))
        else:
            pygame.draw.circle(
                screen,
                self.color,
                (int(self.x), int(self.y)),
                self.radius
            )


# AI players never read the keyboard, so they share a placeholder keys dict.
# The values are only used as dict keys by move/charge_kick/release_kick and
# are never compared against a real keypress.
_AI_KEYS = {"up": "up", "down": "down", "left": "left", "right": "right", "sprint": "sprint"}
_AI_KICK_KEY = "kick"

player1 = Player(GOAL_WIDTH + 20, HEIGHT // 2, BLUE, _AI_KEYS, _AI_KICK_KEY, "Goalkeeper")
player2 = Player(WIDTH - GOAL_WIDTH - 20, HEIGHT // 2, RED, _AI_KEYS, _AI_KICK_KEY, "Goalkeeper")

player3 = Player(280, HEIGHT // 2 - 60, BLUE, _AI_KEYS, _AI_KICK_KEY, "Attacker")
player4 = Player(WIDTH - 280, HEIGHT // 2 + 60, RED, _AI_KEYS, _AI_KICK_KEY, "Attacker")

player5 = Player(280, HEIGHT // 2, BLUE, _AI_KEYS, _AI_KICK_KEY, "Attacker")
player6 = Player(WIDTH - 280, HEIGHT // 2, RED, _AI_KEYS, _AI_KICK_KEY, "Attacker")

player7 = Player(280, HEIGHT // 2 + 60, BLUE, _AI_KEYS, _AI_KICK_KEY, "Defender")
player8 = Player(WIDTH - 280, HEIGHT // 2 - 60, RED, _AI_KEYS, _AI_KICK_KEY, "Defender")

player9 = Player(200, HEIGHT // 2 + 90, BLUE, _AI_KEYS, _AI_KICK_KEY, "Defender")
player10 = Player(WIDTH - 200, HEIGHT // 2 - 90, RED, _AI_KEYS, _AI_KICK_KEY, "Defender")

blue_team = [player1, player3, player5, player7, player9]
red_team = [player2, player4, player6, player8, player10]
all_players = [player1, player2, player3, player4, player5, player6, player7, player8, player9, player10]

# assign AIs to players
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
    player's own keys so the shared Player methods work."""
    keys = {}
    for action in ("up", "down", "left", "right", "sprint"):
        keys[player.keys[action]] = decision.get(action, False)

    kick_wanted = decision.get("kick", False)
    keys[player.kick_key] = (kick_wanted is True)  # held
    return keys


def add_human_player(team):
    """Spawn a keyboard-controlled player onto the given team.

    team == "blue" -> WASD, LShift sprint, Space shoot
    team == "red"  -> arrow keys, RShift sprint, Ctrl shoot
    """
    if team == "blue":
        color = BLUE
        x = WIDTH // 4  # middle of blue's own (left) half
        keys = {
            "up": pygame.K_w,
            "down": pygame.K_s,
            "left": pygame.K_a,
            "right": pygame.K_d,
            "sprint": pygame.K_LSHIFT,
        }
        kick_key = pygame.K_SPACE
        name = "Blue Player"
    else:
        color = RED
        x = WIDTH * 3 // 4  # middle of red's own (right) half
        keys = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "sprint": pygame.K_RSHIFT,
        }
        kick_key = pygame.K_LCTRL
        name = "Red Player"

    p = Player(x, HEIGHT // 2, color, keys, kick_key, name)
    p.ai = None  # no AI -> keyboard controlled
    # humans move faster than the AIs (base 5 / sprint 7)
    p.base_speed = 7
    p.sprint_speed = 9
    (blue_team if team == "blue" else red_team).append(p)
    all_players.append(p)
    return p


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
        # normal play positions, no kickoff
        # blue outfield
        player3.x = 350
        player3.y = HEIGHT // 2 - 60

        player5.x = 350
        player5.y = HEIGHT // 2 + 60

        player7.x = 240
        player7.y = HEIGHT // 2 + 90

        player9.x = 200
        player9.y = HEIGHT // 2 - 50

        # red outfield
        player4.x = WIDTH - 350
        player4.y = HEIGHT // 2 + 60

        player6.x = WIDTH - 350
        player6.y = HEIGHT // 2 - 60

        player8.x = WIDTH - 240
        player8.y = HEIGHT // 2 - 90

        player10.x = WIDTH - 200
        player10.y = HEIGHT // 2 + 50

    else:
        # kickoff formation
        # both teams line up in their own half with defenders and attackers
        # in lines parallel to halfway, kickoff taker at the centre spot

        DEF_X  = 280            # how deep the defensive line sits
        ATT_X  = 550            # attacking-midfield line (in front of defenders)
        DEF_Y  = 170            # vertical spacing for defenders
        ATT_Y  = 100            # vertical spacing for attackers

        if kicking_team == "blue":
            # blue kicks off
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
            # red kicks off
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

    # give the ball to the kicking team's playmaker at the centre spot
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

# kickoff script state
kickoff_timer = 0
kickoff_passer = None

# Teleport everyone to their starting spots NOW so the countdown shows the
# kickoff taker already standing at the centre circle with the ball.
reset_positions(kicking_team="blue")

# replay system, records the last second at 60 fps
REPLAY_MAX_FRAMES = 60
REPLAY_SPEED_DIV = 7
replay_buffer = []
replay_index = 0
replay_subframe = 0
replay_goal_team = None


def record_frame():
    """Snapshot every player and the ball into the circular replay buffer."""
    global replay_buffer
    frame = {
        "players": [],
        "ball": (ball_x, ball_y),
    }
    for p in all_players:
        img_type = "circle"
        if p.ai is not None:
            name = getattr(p.ai, "name", "")
            if name.startswith("Gemini"):
                img_type = "gemini"
            elif name.startswith("Custom"):
                img_type = "claude"
            else:
                img_type = "deepseek"
        frame["players"].append({
            "x": p.x, "y": p.y,
            "face_x": p.face_x, "face_y": p.face_y,
            "holding": p.holding_ball,
            "stunned": p.stunned,
            "color": p.color,
            "name": p.display_name,
            "img_type": img_type,
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

    _event_sound(1.0, 13)

    # Capture replay buffer before resetting
    replay_index = 0
    replay_subframe = 0
    replay_goal_team = team
    game_state = "replay"

    # reset positions without kickoff, ball sits at centre during replay
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
            # 1 = add a blue human player, 2 = add a red human player
            if event.key == pygame.K_1:
                add_human_player("blue")
            elif event.key == pygame.K_2:
                add_human_player("red")

    keys = pygame.key.get_pressed()

    _event_tick()

    if game_state == "playing" and game_timer > 0:

        # Game timer
        game_timer -= 1

        # kickoff script: forced pass to the nearest teammate
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
                _kick()
                p.kick_power = 0
                p.kick_cooldown = KICK_COOLDOWN_TIME
                last_kicker = p
                interception_timer = 90
                kickoff_passer = None
            # Passer is frozen at the centre spot until the pass is released
            p.move({k: False for k in p.keys.values()})

        # Update players
        for p in all_players:
            # During kickoff, freeze ALL players until the ball is passed
            if kickoff_timer > 0:
                continue
            if p.ai is not None:
                # AI controlled
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
                # keyboard controlled
                p.move(keys)
                p.charge_kick(keys)
                p.release_kick(keys)

        if steal_cooldown > 0:
            steal_cooldown -= 1

        # tick down status timers
        for p in all_players:
            if p.steal_shield > 0:
                p.steal_shield -= 1
            if p.stunned > 0:
                p.stunned -= 1
            if p.slow_timer > 0:
                p.slow_timer -= 1
        if interception_timer > 0:
            interception_timer -= 1

        # player collision, push apart overlapping players
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

        # ball pickup, closest player gets it
        if not any(p.holding_ball for p in all_players):
            # Sort by distance to ball so the closest player always wins
            # goalkeepers always eligible, outfield must not be stunned
            candidates = [p for p in all_players
                          if p.stunned == 0 or (hasattr(p, 'ai') and p.ai is not None
                                                and p.ai.name in ('Goalkeeper', 'Custom GK'))]
            candidates.sort(key=lambda p: math.hypot(ball_x - p.x, ball_y - p.y))
            for p in candidates:
                p.pickup_ball()
                if p.holding_ball:
                    if p is player1 or p is player2:
                        _event_sound(0.50, 4)
                    break   # ball claimed, stop

        # Ball carrying
        for p in all_players:
            p.carry_ball()

        # prevent own goal: non-GK ball carrier cannot enter own net
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

        # steal: pops the ball loose instead of transferring possession
        # only works from the front, opponent must be ball-side of the holder
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
                            # pop the ball loose away from both players
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

        # goal detection — the WHOLE ball must pass through the edge of the map
        # at the goal mouth; wall collision is already disabled there
        in_goal_y = abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2

        if ball_x <= -ball_radius and in_goal_y:
            if ball_vx < 0:  # ball moving into goal from field
                goal_scored("right")

        if ball_x >= WIDTH + ball_radius and in_goal_y:
            if ball_vx > 0:  # ball moving into goal from field
                goal_scored("left")

        # field collision, allow ball through goal area
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

        # record frame for goal replay
        if game_state == "playing":
            record_frame()

    elif game_state == "replay":
        # slow motion replay
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

    # draw players and ball, replay or live
    if game_state == "replay" and replay_index < len(replay_buffer):
        frame = replay_buffer[replay_index]
        # Draw recorded player positions
        for pd in frame["players"]:
            img_type = pd.get("img_type", "circle")
            if img_type == "gemini":
                screen.blit(_gemini_img, (int(pd["x"] - _IMG_SIZE // 2), int(pd["y"] - _IMG_SIZE // 2)))
            elif img_type == "claude":
                screen.blit(_claude_img, (int(pd["x"] - _IMG_SIZE // 2), int(pd["y"] - _IMG_SIZE // 2)))
            elif img_type == "deepseek":
                screen.blit(_deepseek_img, (int(pd["x"] - _IMG_SIZE // 2), int(pd["y"] - _IMG_SIZE // 2)))
            else:
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
            # stunned indicator removed
        # Ball trail — small square particles fading back through time
        trail_length = 18
        for t in range(1, trail_length + 1):
            idx = replay_index - t
            if idx < 0:
                break
            prev_frame = replay_buffer[idx]
            bx, by = prev_frame["ball"]
            # Particles shrink and fade the further back they are
            ratio = 1.0 - (t / (trail_length + 1))
            size = max(1, int(ball_radius * 0.7 * ratio))
            alpha = int(120 * ratio)
            if size <= 0:
                continue
            trail_surf = pygame.Surface((size, size), pygame.SRCALPHA)
            trail_surf.fill((220, 120, 20, alpha))
            trail_surf.set_alpha(alpha)
            screen.blit(trail_surf, (int(bx - size / 2), int(by - size / 2)))

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
            # stunned indicator removed

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