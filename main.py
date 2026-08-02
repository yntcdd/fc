import pygame
import math
from ai import create_ai, cycle_ai, AI_REGISTRY

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
#  Available AIs: "striker", "playmaker", "goalkeeper", "trickster"
#  (Press 1/2/3/4 during play to toggle AI on/off per player,
#   press 0 to cycle the AI type of the toggled players.)

PLAYER1_AI = create_ai("playmaker")                    # WASD      – keyboard
PLAYER2_AI = create_ai("trickster")                    # Arrows    – keyboard
PLAYER3_AI = create_ai("striker")                    # IJKL      – keyboard
PLAYER4_AI = create_ai("playmaker")    # Numpad    – AI
# ————————————————————————————————————————————————

# Field
GOAL_WIDTH = 40
GOAL_HEIGHT = 250

# Ball
STEAL_COOLDOWN_TIME = 30  # 30 frames = 0.5 seconds at 60 FPS
steal_cooldown = 0

ball_radius = 12
ball_x = WIDTH // 2
ball_y = HEIGHT // 2

ball_vx = 0
ball_vy = 0

FRICTION = 0.98

# Kick
MAX_KICK_POWER = 25
KICK_CHARGE_RATE = 0.5
KICK_COOLDOWN_TIME = 20

# Score
score_left = 0
score_right = 0


class Player:
    def __init__(self, x, y, color, keys, kick_key):
        self.x = x
        self.y = y
        self.color = color

        self.radius = 20

        self.base_speed = 5
        self.sprint_speed = 7

        self.face_x = 1
        self.face_y = 0

        self.keys = keys
        self.kick_key = kick_key

        self.holding_ball = False
        self.steal_shield = 0     # frames of immunity after acquiring the ball

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
            self.kick_power += KICK_CHARGE_RATE

            if self.kick_power > MAX_KICK_POWER:
                self.kick_power = MAX_KICK_POWER

    def release_kick(self, pressed):
        global ball_vx, ball_vy

        if not pressed[self.kick_key] and self.kick_power > 0 and self.holding_ball:
            self.holding_ball = False

            ball_vx = self.face_x * self.kick_power
            ball_vy = self.face_y * self.kick_power

            self.kick_power = 0
            self.kick_cooldown = KICK_COOLDOWN_TIME

    def pickup_ball(self):
        global ball_vx, ball_vy

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
    WIDTH // 4,
    HEIGHT // 2 - 80,
    BLUE,
    {
        "up": pygame.K_w,
        "down": pygame.K_s,
        "left": pygame.K_a,
        "right": pygame.K_d,
        "sprint": pygame.K_LSHIFT
    },
    pygame.K_SPACE
)

player2 = Player(
    WIDTH * 3 // 4,
    HEIGHT // 2 - 80,
    RED,
    {
        "up": pygame.K_UP,
        "down": pygame.K_DOWN,
        "left": pygame.K_LEFT,
        "right": pygame.K_RIGHT,
        "sprint": pygame.K_RSHIFT
    },
    pygame.K_0
)

player3 = Player(
    WIDTH // 4,
    HEIGHT // 2 + 80,
    BLUE,
    {
        "up": pygame.K_i,
        "down": pygame.K_k,
        "left": pygame.K_j,
        "right": pygame.K_l,
        "sprint": pygame.K_u
    },
    pygame.K_o
)

player4 = Player(
    WIDTH * 3 // 4,
    HEIGHT // 2 + 80,
    RED,
    {
        "up": pygame.K_KP8,
        "down": pygame.K_KP5,
        "left": pygame.K_KP4,
        "right": pygame.K_KP6,
        "sprint": pygame.K_KP7
    },
    pygame.K_KP9
)

blue_team = [player1, player3]
red_team = [player2, player4]
all_players = [player1, player2, player3, player4]

# ——— Assign AIs to players ———
player1.ai = PLAYER1_AI
player2.ai = PLAYER2_AI
player3.ai = PLAYER3_AI
player4.ai = PLAYER4_AI


def ai_decision_to_keys(decision, player):
    """Convert an AI decision dict into a pressed-keys dict keyed by the
    player's actual pygame keycodes so the existing Player methods work."""
    keys = {}
    for action in ("up", "down", "left", "right", "sprint"):
        keys[player.keys[action]] = decision.get(action, False)

    kick_wanted = decision.get("kick", False)
    keys[player.kick_key] = (kick_wanted is True)  # held
    return keys


def reset_positions():
    global ball_x, ball_y
    global ball_vx, ball_vy

    player1.x = WIDTH // 4
    player1.y = HEIGHT // 2 - 80

    player2.x = WIDTH * 3 // 4
    player2.y = HEIGHT // 2 - 80

    player3.x = WIDTH // 4
    player3.y = HEIGHT // 2 + 80

    player4.x = WIDTH * 3 // 4
    player4.y = HEIGHT // 2 + 80

    ball_x = WIDTH // 2
    ball_y = HEIGHT // 2

    ball_vx = 0
    ball_vy = 0

    for p in all_players:
        p.holding_ball = False
        p.kick_power = 0
        p.kick_cooldown = 0
        p.steal_shield = 0


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

game_state = "playing"

goal_timer = 0
countdown_timer = 0


def goal_scored(team):
    global score_left, score_right
    global game_state, goal_timer

    if team == "left":
        score_left += 1
    else:
        score_right += 1

    game_state = "goal"
    goal_timer = 180

    reset_positions()

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
            #  1-4 : toggle AI on/off for that player
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
            elif event.key == pygame.K_0:
                # Cycle AI type for every AI-controlled player
                for p in all_players:
                    if p.ai is not None:
                        p.ai = cycle_ai(p.ai)

    keys = pygame.key.get_pressed()

    if game_state == "playing":

        # Update players
        for p in all_players:
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

        # Tick down shields
        for p in all_players:
            if p.steal_shield > 0:
                p.steal_shield -= 1

        # Ball pickup
        if not any(p.holding_ball for p in all_players):
            for p in all_players:
                p.pickup_ball()

        # Ball carrying
        for p in all_players:
            p.carry_ball()

        # Steal — pops the ball loose instead of transferring possession.
        # This prevents ping-pong A→B→A→B stealing.
        # Only works from the FRONT — opponent must be on the ball-side of the holder.
        if steal_cooldown == 0:
            for holder in all_players:
                if holder.holding_ball and holder.steal_shield == 0:
                    opponents = red_team if holder in blue_team else blue_team
                    for opponent in opponents:
                        # Must be in front of the holder (same side as the ball)
                        to_opp_x = opponent.x - holder.x
                        to_opp_y = opponent.y - holder.y
                        dot = holder.face_x * to_opp_x + holder.face_y * to_opp_y
                        if dot <= 0:
                            continue   # opponent is behind — can't steal

                        distance = math.hypot(ball_x - opponent.x, ball_y - opponent.y)
                        if distance < opponent.radius + ball_radius - 2:
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

        # Goal detection
        if ball_x < GOAL_WIDTH:
            if abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2:
                goal_scored("right")

        if ball_x > WIDTH - GOAL_WIDTH:
            if abs(ball_y - HEIGHT // 2) < GOAL_HEIGHT // 2:
                goal_scored("left")

        # Field collision
        if ball_y <= ball_radius:
            ball_y = ball_radius
            ball_vy *= -1

        if ball_y >= HEIGHT - ball_radius:
            ball_y = HEIGHT - ball_radius
            ball_vy *= -1

        if ball_x <= ball_radius:
            ball_x = ball_radius
            ball_vx *= -1

        if ball_x >= WIDTH - ball_radius:
            ball_x = WIDTH - ball_radius
            ball_vx *= -1

    elif game_state == "goal":

        goal_timer -= 1

        if goal_timer <= 0:
            game_state = "countdown"
            countdown_timer = 300

    elif game_state == "countdown":

        countdown_timer -= 1

        if countdown_timer <= 0:
            game_state = "playing"

    # Draw field
    draw_field()

    # Draw players
    for p in all_players:
        p.draw()

    # Draw AI indicator above AI-controlled players
    for p in all_players:
        if p.ai is not None:
            label = ai_font.render(p.ai.name, True, (255, 255, 0))
            screen.blit(
                label,
                (p.x - label.get_width() // 2, p.y - p.radius - 22),
            )

    # Draw shield ring around immune players
    for p in all_players:
        if p.steal_shield > 0:
            alpha = p.steal_shield / 25  # fades out
            r = int(200 * alpha)
            g = int(200 * alpha)
            b = int(255 * alpha)
            pygame.draw.circle(
                screen,
                (r, g, b),
                (int(p.x), int(p.y)),
                p.radius + 5,
                2,
            )

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

    # ——— HUD: AI status bar at the bottom ———————————
    y_base = HEIGHT - 50
    slot_w = 280
    for i, p in enumerate(all_players):
        px = 30 + i * (slot_w + 30)
        status = p.ai.name if p.ai is not None else "Keyboard"
        color = (255, 255, 0) if p.ai is not None else (180, 180, 180)
        label = ai_font.render(f"P{i+1}: {status}", True, color)
        screen.blit(label, (px, y_base))

    # Cycle hint
    hint = ai_font.render(
        "Keys 1-4: cycle AI per player  |  0: cycle all AI types",
        True, (200, 200, 200),
    )
    screen.blit(hint, (WIDTH - hint.get_width() - 20, y_base))

    pygame.display.flip()

pygame.quit()