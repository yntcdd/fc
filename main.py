import pygame
import math

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
    HEIGHT // 2,
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
    HEIGHT // 2,
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


def reset_positions():
    global ball_x, ball_y
    global ball_vx, ball_vy

    player1.x = WIDTH // 4
    player1.y = HEIGHT // 2

    player2.x = WIDTH * 3 // 4
    player2.y = HEIGHT // 2

    ball_x = WIDTH // 2
    ball_y = HEIGHT // 2

    ball_vx = 0
    ball_vy = 0

    player1.holding_ball = False
    player2.holding_ball = False


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


while running:
    clock.tick(60)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    keys = pygame.key.get_pressed()

    if game_state == "playing":

        # Update players
        player1.move(keys)
        player2.move(keys)

        player1.charge_kick(keys)
        player2.charge_kick(keys)

        player1.release_kick(keys)
        player2.release_kick(keys)

        if steal_cooldown > 0:
            steal_cooldown -= 1

        # Ball pickup
        if not player1.holding_ball and not player2.holding_ball:
            player1.pickup_ball()
            player2.pickup_ball()

        # Ball carrying
        player1.carry_ball()
        player2.carry_ball()

        # Steal ball

        if steal_cooldown == 0:
            if player1.holding_ball:
                distance = math.hypot(ball_x - player2.x, ball_y - player2.y)

                if distance < player2.radius + ball_radius:
                    player1.holding_ball = False
                    player2.holding_ball = True
                    ball_vx = 0
                    ball_vy = 0

                    steal_cooldown = STEAL_COOLDOWN_TIME


            if player2.holding_ball:
                distance = math.hypot(ball_x - player1.x, ball_y - player1.y)

                if distance < player1.radius + ball_radius:
                    player2.holding_ball = False
                    player1.holding_ball = True
                    ball_vx = 0
                    ball_vy = 0

                    steal_cooldown = STEAL_COOLDOWN_TIME

                
        # Ball movement
        if not player1.holding_ball and not player2.holding_ball:
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
    player1.draw()
    player2.draw()

    # Draw ball
    pygame.draw.circle(
        screen,
        ORANGE,
        (int(ball_x), int(ball_y)),
        ball_radius
    )

    # Player 1 kick bar
    if player1.holding_ball:
        bar_width = 60
        bar_height = 8

        bar_x = player1.x - bar_width / 2
        bar_y = player1.y + player1.radius + 10

        pygame.draw.rect(
            screen,
            BLACK,
            (bar_x, bar_y, bar_width, bar_height)
        )

        power = player1.kick_power / MAX_KICK_POWER
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

    # Player 2 kick bar
    if player2.holding_ball:
        bar_width = 60
        bar_height = 8

        bar_x = player2.x - bar_width / 2
        bar_y = player2.y + player2.radius + 10

        pygame.draw.rect(
            screen,
            BLACK,
            (bar_x, bar_y, bar_width, bar_height)
        )

        power = player2.kick_power / MAX_KICK_POWER
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

    pygame.display.flip()

pygame.quit()